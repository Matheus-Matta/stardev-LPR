import hashlib
import logging
import socket
import time
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
from django.utils import timezone

from common.mlops import active_model_metadata
from plates.models import PlateEvent

logger = logging.getLogger(__name__)
detection_logger = logging.getLogger("lpr.detections")

def _get_alpr():
    """Retorna a engine LPR ativa (selecionada via LPR_ENGINE no .env)."""
    from plates.engines.factory import get_lpr_engine
    return get_lpr_engine()


def quick_predict(frame: np.ndarray) -> tuple[str, Decimal | None]:
    """Roda ALPR em um frame bruto sem criar nenhum registro no banco."""
    alpr = _get_alpr()
    results = alpr.predict(frame)
    best = _best_result(results)
    if not best or not best.ocr or not best.ocr.text:
        return "", None
    plate_text = best.ocr.text.upper().replace(" ", "")
    raw_conf = best.ocr.confidence
    avg_conf = float(sum(raw_conf) / len(raw_conf)) if isinstance(raw_conf, list) else float(raw_conf)
    return plate_text, Decimal(str(round(avg_conf, 4)))


def run_ocr_pipeline(event: PlateEvent) -> dict:
    started = timezone.now()

    image_hash = _sha256_file(event.image)

    t0 = time.perf_counter()
    frame = _load_frame(event.image)
    detection_ms = int((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    alpr = _get_alpr()
    results = alpr.predict(frame)
    ocr_ms = int((time.perf_counter() - t1) * 1000)

    best = _best_result(results)
    plate_text = ""
    confidence = None

    if best and best.ocr and best.ocr.text:
        plate_text = best.ocr.text.upper().replace(" ", "")
        raw_conf = best.ocr.confidence
        avg_conf = float(sum(raw_conf) / len(raw_conf)) if isinstance(raw_conf, list) else float(raw_conf)
        confidence = Decimal(str(round(avg_conf, 4)))
        ts = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        frame_name = Path(event.image.name).name
        logger.debug(
            "[PLATE DETECTED]  plate=%-10s  conf=%s  event_id=%s  camera_id=%s",
            plate_text, f"{avg_conf:.2f}", event.id, event.camera_id,
        )
        detection_logger.info(
            f"{ts} | plate={plate_text:<10} | conf={avg_conf:.4f}"
            f" | camera_id={event.camera_id} | event_id={event.id} | frame={frame_name}"
        )
    else:
        logger.debug("[PLATE] nenhuma placa encontrada  event_id=%s  camera_id=%s", event.id, event.camera_id)

    finished = timezone.now()
    return {
        "plate_text": plate_text,
        "confidence": confidence,
        "raw_payload": {
            "engine": "fast-alpr",
            "image_sha256": image_hash,
            "detections": [
                {
                    "text": r.ocr.text if r.ocr else None,
                    "confidence": (
                        round(sum(r.ocr.confidence) / len(r.ocr.confidence), 4)
                        if r.ocr and isinstance(r.ocr.confidence, list)
                        else round(float(r.ocr.confidence), 4) if r.ocr else None
                    ),
                }
                for r in results
            ],
            "total_detections": len(results),
        },
        "pipeline_metadata": {
            **active_model_metadata(),
            "preprocessing": ["exif_stripped", "mime_validated"],
            "timings_ms": {
                "detection": detection_ms,
                "ocr": ocr_ms,
                "validation": 0,
            },
            "worker_id": socket.gethostname(),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
        },
    }


def _load_frame(field_file) -> np.ndarray:
    field_file.seek(0)
    raw = np.frombuffer(field_file.read(), dtype=np.uint8)
    frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"cv2.imdecode falhou para {field_file.name}")
    return frame


def _best_result(results):
    best = None
    best_conf = -1.0
    for r in results:
        if not r.ocr or not r.ocr.text:
            continue
        raw = r.ocr.confidence
        conf = sum(raw) / len(raw) if isinstance(raw, list) else float(raw)
        if conf > best_conf:
            best_conf = conf
            best = r
    return best


def _sha256_file(field_file) -> str:
    digest = hashlib.sha256()
    pos = field_file.tell() if hasattr(field_file, "tell") else None
    try:
        field_file.seek(0)
        for chunk in field_file.chunks():
            digest.update(chunk)
    finally:
        if pos is not None:
            field_file.seek(pos)
    return f"sha256:{digest.hexdigest()}"
