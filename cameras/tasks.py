import logging
import re
import threading
import time
from decimal import Decimal

import cv2
import numpy as np

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from cameras.models import Camera
from plates.access import create_access_event

logger = logging.getLogger(__name__)
detection_logger = logging.getLogger("lpr.detections")

_cap_lock = threading.Lock()
_cap_cache: dict[str, cv2.VideoCapture] = {}

# ── Deduplicação no banco ────────────────────────────────────────────────────
# Janela usada para evitar dois AccessEvents para a mesma placa+câmera quando
# o pipeline emite eventos em frames consecutivos (ex.: provisional → confirmado).
_DB_DEDUP_SECONDS = 3


def _is_recent_plate_dup(camera, normalized_plate: str) -> bool:
    """
    True se já existe AccessEvent para esta câmera + placa normalizada
    nos últimos _DB_DEDUP_SECONDS segundos.

    Evita duplicatas mesmo se o processo for reiniciado ou o ingest externo
    também criar eventos para a mesma leitura.
    """
    from datetime import timedelta
    from plates.models import AccessEvent
    if not normalized_plate:
        return False
    cutoff = timezone.now() - timedelta(seconds=_DB_DEDUP_SECONDS)
    return AccessEvent.objects.filter(
        camera=camera,
        normalized_plate=normalized_plate,
        received_at__gte=cutoff,
    ).exists()


def _save_plate_event(event: dict, frame: np.ndarray):
    """
    Persiste evento LPR no banco — provisional e confirmado.

    Todos os eventos emitidos pelo pipeline (provisional ≥ 0.70 e confirmed
    ≥ 0.90) geram um AccessEvent e, consequentemente, alertas (blacklist,
    unknown, manual_review).

    Deduplicação de 3 s por câmera + placa normalizada evita criar dois
    registros para o mesmo veículo em frames consecutivos.

    Retorna o AccessEvent criado, ou None se dedup/erro.
    """
    status = event.get("status", "confirmed")
    plate_text = event["plate"]
    camera_id = event["camera_id"]

    camera = Camera.objects.get(id=camera_id)

    # ── Dedup de banco (3 s) ──────────────────────────────────────────────────
    normalized = re.sub(r"[^A-Z0-9]", "", plate_text.upper())
    if _is_recent_plate_dup(camera, normalized):
        logger.debug(
            "[plate] dedup-3s ignorado  camera_id=%s  plate=%s  status=%s",
            camera_id, plate_text, status,
        )
        return None

    # ── Crop específico de cada placa (bbox do evento) ────────────────────────
    x1, y1, x2, y2 = event.get("bbox", (0, 0, frame.shape[1], frame.shape[0]))
    fh, fw = frame.shape[:2]
    crop = frame[max(0, y1):min(fh, y2), max(0, x1):min(fw, x2)]
    save_frame = crop if crop.size > 0 else frame

    _q = getattr(settings, "CAPTURE_IMAGE_QUALITY", 85)
    ok, buf = cv2.imencode(".jpg", save_frame, [cv2.IMWRITE_JPEG_QUALITY, _q])
    if not ok:
        logger.warning("[plate] cv2.imencode falhou  camera_id=%s", camera_id)
        return None

    ts = timezone.now().strftime("%Y%m%d_%H%M%S")
    image_file = ContentFile(
        buf.tobytes(),
        name=f"plate_{camera.camera_key}_{ts}.jpg",
    )

    event_obj = create_access_event(
        camera=camera,
        payload={
            "source":         "lpr_pipeline",
            "captured_at":    timezone.now().isoformat(),
            "plate":          plate_text,
            "confidence":     str(Decimal(str(event["confidence"]))),
            "track_id":       event.get("track_id"),
            "readings_count": event.get("readings_count", 1),
            "tier":           event.get("tier"),
            "lpr_status":     status,
        },
        image=image_file,
    )

    log_ts = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
    detection_logger.info(
        f"{log_ts} | plate={plate_text:<10} | conf={event['confidence']:.4f}"
        f" | tier={event.get('tier')} | status={status} | camera_id={camera_id}"
        f" | track_id={event.get('track_id')} | event_id={event_obj.id}"
    )
    logger.debug(
        "[plate] %s  camera_id=%s  plate=%s  conf=%s  track_id=%s  event_id=%s",
        status, camera_id, plate_text, f"{event['confidence']:.2f}",
        event.get("track_id"), event_obj.id,
    )
    return event_obj


def _process_frame(camera_id: int, frame: np.ndarray) -> dict:
    """
    OCR em todas as placas do frame + salva um AccessEvent por placa.

    Suporta múltiplas placas visíveis simultaneamente.
    Dedup de 3 s por câmera + placa evita duplicatas entre chamadas do Celery.
    """
    from plates.services import _get_alpr

    alpr = _get_alpr()
    results = alpr.predict(frame)

    # Coleta todas as detecções válidas
    plates_found: list[tuple[str, float]] = []
    for r in results:
        if not r.ocr or not r.ocr.text:
            continue
        text = re.sub(r"[^A-Z0-9]", "", r.ocr.text.upper())
        if not text:
            continue
        raw_conf = r.ocr.confidence
        conf = (
            float(sum(raw_conf) / len(raw_conf))
            if isinstance(raw_conf, list)
            else float(raw_conf)
        )
        plates_found.append((text, conf))

    if not plates_found:
        return {"camera_id": camera_id, "status": "no_plate"}

    # Só busca câmera do banco quando há placa (evita query desnecessária)
    camera = Camera.objects.get(id=camera_id)
    _q = getattr(settings, "CAPTURE_IMAGE_QUALITY", 85)
    ts = timezone.now().strftime("%Y%m%d_%H%M%S")

    created_events = []
    for plate_text, confidence in plates_found:
        normalized = re.sub(r"[^A-Z0-9]", "", plate_text.upper())
        if _is_recent_plate_dup(camera, normalized):
            logger.debug(
                "[frame] dedup-3s ignorado  camera_id=%s  plate=%s", camera_id, plate_text
            )
            continue

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _q])
        if not ok:
            raise RuntimeError("cv2.imencode falhou")

        image_file = ContentFile(
            buf.tobytes(),
            name=f"cap_{camera.camera_key}_{ts}.jpg",
        )

        event = create_access_event(
            camera=camera,
            payload={
                "source":      "rtsp_capture",
                "captured_at": timezone.now().isoformat(),
                "plate":       plate_text,
                "confidence":  str(round(confidence, 4)),
            },
            image=image_file,
        )
        created_events.append(event)

        log_ts = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        detection_logger.info(
            f"{log_ts} | plate={plate_text:<10} | conf={confidence:.4f}"
            f" | camera_id={camera_id} | event_id={event.id}"
        )
        logger.debug(
            "[frame] plate found  camera_id=%s  plate=%s  conf=%.4f  event_id=%s",
            camera_id, plate_text, confidence, event.id,
        )

    if not created_events:
        return {"camera_id": camera_id, "status": "dedup_skipped"}

    # Mantém compatibilidade com código que usa "plate"/"event_id" únicos
    return {
        "camera_id":  camera_id,
        "status":     "captured",
        "plate":      created_events[0].plate_text,          # compat
        "event_id":   created_events[0].id,                  # compat
        "event_uuid": str(created_events[0].event_uuid),     # compat
        "plates":     [e.plate_text for e in created_events],
        "event_ids":  [e.id for e in created_events],
        "count":      len(created_events),
    }


def _do_capture(camera_id: int) -> dict:
    """Grab + OCR em sequência — usado pelo Celery task."""
    camera = Camera.objects.get(id=camera_id)

    if camera.connection_mode == Camera.ConnectionMode.PUSH:
        return {"camera_id": camera.id, "status": "skipped", "reason": "PUSH mode"}

    url = camera.capture_rtsp_url
    try:
        frame = _grab_frame(url)
    except Exception as exc:
        msg = str(exc)
        if "unavailable" in msg or "404" in msg or "400 Bad" in msg:
            return {"camera_id": camera.id, "status": "skipped", "reason": "stream not available"}
        raise

    return _process_frame(camera_id, frame)


@shared_task(
    bind=True,
    queue="capture",
    acks_late=True,
    time_limit=settings.RTSP_READ_TIMEOUT + 5,
    soft_time_limit=settings.RTSP_READ_TIMEOUT,
)
def capture_camera_frame(self, camera_id: int) -> dict:
    try:
        return _do_capture(camera_id)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning("[frame] capture failed  camera_id=%s: %s", camera_id, exc)
        raise self.retry(exc=exc, countdown=5, max_retries=2) from exc


def _grab_frame(rtsp_url: str) -> np.ndarray:
    """
    Retorna o frame mais recente do stream, drenando frames obsoletos acumulados
    no buffer entre chamadas do Celery.

    cap.grab() lê o pacote H.264 comprimido sem decodificar (rápido/barato).
    cap.retrieve() decodifica apenas o último frame retido — chamado uma única vez.

    Estratégia de dreno:
      - Obtemos o FPS declarado do stream para saber o intervalo entre frames.
      - Chamamos grab() em loop; enquanto o grab for instantâneo (elapsed < half_frame_s),
        o frame já estava no buffer — descartamos e continuamos.
      - Quando grab() bloqueia aguardando o próximo pacote da rede (elapsed >= half_frame_s),
        chegamos ao live edge: este é o frame mais recente.
      - Limitamos o dreno a max_drain frames (10 s de vídeo) para evitar loop infinito.
    """
    cap = _get_cap(rtsp_url)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fps = max(fps, 1.0)
    half_frame_s = 0.5 / fps          # ~16 ms para 30 fps, ~500 ms para 1 fps
    max_drain = int(fps * 10)         # no máximo 10 s de frames acumulados

    grabbed = False
    for _ in range(max_drain):
        t0 = time.perf_counter()
        ok = cap.grab()
        elapsed = time.perf_counter() - t0

        if not ok:
            break
        grabbed = True
        # grab() esperou pela rede → live edge atingido → frame mais atual
        if elapsed >= half_frame_s:
            break

    if not grabbed:
        _release_cap(rtsp_url)
        raise RuntimeError(f"stream unavailable: {rtsp_url}")

    ret, frame = cap.retrieve()
    if not ret or frame is None:
        _release_cap(rtsp_url)
        raise RuntimeError(f"stream unavailable: {rtsp_url}")
    return frame


def _get_cap(rtsp_url: str) -> cv2.VideoCapture:
    # Verificação rápida sem criar conexão (hot path)
    with _cap_lock:
        cap = _cap_cache.get(rtsp_url)
        if cap is not None and cap.isOpened():
            return cap

    # Conexão fora do lock — câmeras diferentes conectam em paralelo.
    # cv2.VideoCapture pode levar vários segundos (RTSP handshake / timeout),
    # por isso não deve segurar o lock global durante esse tempo.
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"stream unavailable: {rtsp_url}")

    with _cap_lock:
        # Outro thread pode ter conectado enquanto aguardávamos — usa o dele
        existing = _cap_cache.get(rtsp_url)
        if existing is not None and existing.isOpened():
            cap.release()
            return existing
        _cap_cache[rtsp_url] = cap
        logger.info("[cap] conexão RTSP estabelecida  url=%s", rtsp_url)
    return cap


def _release_cap(rtsp_url: str) -> None:
    with _cap_lock:
        cap = _cap_cache.pop(rtsp_url, None)
        if cap:
            cap.release()
