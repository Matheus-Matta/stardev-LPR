"""
LPR Pipeline — processamento completo por câmera.

Camadas:
  ROI → Detecção de placas → Tracking (IoU) → Confiança → Dedup → Eventos

Regras de confiança:
  < 0.70              → descartado
  0.70 – 0.89         → provisório (aguarda 2+ frames)
  ≥ 0.90              → confirmado imediatamente
  ≥ 0.95              → forte (prioridade sobre leituras conflitantes)

Múltiplas placas no mesmo frame:
  Cada detecção segue para um PlateTrack próprio (por IoU de bounding box).
  Placas com confiança ≥ 0.90 geram eventos independentes.
  Duplicidade no mesmo track → escolhe a de maior confiança.
  Deduplicação temporal evita múltiplos eventos da mesma placa/câmera.

Placas suportadas:
  Padrão antigo  : ABC1234
  Mercosul       : ABC1D23
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# ── Limiares de confiança ────────────────────────────────────────────────────

CONF_REJECT      = 0.70   # abaixo: descarta
CONF_PROVISIONAL = 0.70   # [0.70, 0.90) → provisório
CONF_CONFIRM     = 0.90   # [0.90, 0.95) → confirmado imediatamente
CONF_STRONG      = 0.95   # ≥ 0.95 → forte, prioridade máxima

# ── Parâmetros de tracking / dedup ───────────────────────────────────────────

TRACK_IOU_MIN    = 0.25   # IoU mínimo para associar leitura a track existente
TRACK_MAX_AGE    = 3.0    # s sem aparecer → track expirado → emite evento final
DEDUP_WINDOW     = 4.0    # s — suprime re-emissão do pipeline para o mesmo track
#                           (dedup de 3 s no banco é a barreira final contra duplicatas)
MAX_READINGS     = 60     # cap de leituras por track (evita vazamento de memória)

# ── Padrões de placa brasileira ───────────────────────────────────────────────

_RE_OLD      = re.compile(r'^[A-Z]{3}[0-9]{4}$')          # ABC1234
_RE_MERCOSUL = re.compile(r'^[A-Z]{3}[0-9][A-Z][0-9]{2}$')  # ABC1D23


# ── Helpers ──────────────────────────────────────────────────────────────────

def _avg_conf(raw) -> float:
    if isinstance(raw, (list, tuple)) and raw:
        return float(sum(raw) / len(raw))
    return float(raw)


def tier_for(conf: float) -> str | None:
    """Retorna o tier de confiança ou None se abaixo do mínimo."""
    if conf >= CONF_STRONG:      return "strong"
    if conf >= CONF_CONFIRM:     return "confirmed"
    if conf >= CONF_PROVISIONAL: return "provisional"
    return None


def validate_plate(text: str) -> bool:
    """True se o texto corresponde a formato de placa brasileira válido."""
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
    return bool(_RE_OLD.match(cleaned) or _RE_MERCOSUL.match(cleaned))


def _iou(a: tuple, b: tuple) -> float:
    """Intersection-over-Union de dois bboxes (x1,y1,x2,y2)."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


def _extract_bbox(result, shape: tuple) -> tuple[int, int, int, int]:
    """Extrai (x1,y1,x2,y2) em pixels de um resultado fast-alpr."""
    h, w = shape[:2]
    try:
        bb = result.detection.bounding_box
        x1, y1, x2, y2 = int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])
        return (max(0, x1), max(0, y1), min(w, x2), min(h, y2))
    except Exception:
        return (0, 0, w, h)


def _crop_plate(frame: np.ndarray, bbox: tuple) -> np.ndarray:
    """Recorta a região da placa do frame. Retorna o frame inteiro como fallback."""
    x1, y1, x2, y2 = bbox
    fh, fw = frame.shape[:2]
    crop = frame[max(0, y1):min(fh, y2), max(0, x1):min(fw, x2)]
    return crop if crop.size > 0 else frame


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PlateReading:
    text: str                          # "ABC1234"
    confidence: float                  # confiança média do OCR
    tier: str                          # provisional | confirmed | strong
    valid_format: bool                 # True = padrão brasileiro válido
    bbox: tuple[int, int, int, int]    # (x1, y1, x2, y2) pixels no crop/frame
    timestamp: float                   # time.time()


@dataclass
class PlateTrack:
    """Rastreamento de uma placa ao longo de múltiplos frames."""
    track_id: int
    camera_id: int
    bbox: tuple[int, int, int, int]
    readings: list[PlateReading] = field(default_factory=list)
    best: PlateReading | None = None
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    confirmed: bool = False            # evento final já emitido


# ── Pipeline ─────────────────────────────────────────────────────────────────

class LPRPipeline:
    """
    Pipeline LPR completo por câmera.

    Instanciar uma vez por câmera e chamar process_frame(frame) em loop.
    Thread-safe: pode ser chamado de threads diferentes para a mesma câmera.

    Parâmetros
    ----------
    camera_id
        ID da câmera no banco.
    roi
        Região de interesse (x, y, largura, altura) em pixels.
        None = frame inteiro.
    dedup_window
        Segundos de supressão da mesma placa na mesma câmera.
    track_max_age
        Segundos sem ver uma placa antes de expirar o track.
    """

    def __init__(
        self,
        camera_id: int,
        roi: tuple[int, int, int, int] | None = None,
        dedup_window: float = DEDUP_WINDOW,
        track_max_age: float = TRACK_MAX_AGE,
    ) -> None:
        self.camera_id = camera_id
        self.roi = roi
        self._dedup_window = dedup_window
        self._track_max_age = track_max_age

        self._tracks: dict[int, PlateTrack] = {}
        self._next_id = 1
        self._dedup: dict[str, float] = {}   # fallback in-memory
        self._redis = self._connect_redis()
        self._lock = threading.Lock()

    @staticmethod
    def _connect_redis():
        """Tenta conectar ao Redis para dedup distribuído. Retorna None se indisponível."""
        try:
            import os
            import redis
            url = os.environ.get("REDIS_URL", "")
            if not url:
                return None
            r = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
            r.ping()
            return r
        except Exception:
            return None

    # ── Ponto de entrada ──────────────────────────────────────────────────────

    def process_frame(self, frame: np.ndarray) -> list[dict]:
        """
        Processa um frame e retorna lista de eventos.

        Cada evento é um dict com:
          camera_id, track_id, plate, confidence, tier, valid_format,
          status, bbox, bbox_crop, readings_count, timestamp

        Nunca lança exceção — erros são capturados e logados.
        """
        now = time.time()
        try:
            crop = self._apply_roi(frame)
            readings = self._detect(crop, now)

            with self._lock:
                self._match_tracks(readings, now)
                events = self._evaluate_all(now)
                expired = self._expire_tracks(now)

            return events + expired
        except Exception as exc:
            logger.warning("[lpr] camera_id=%s process_frame erro: %s", self.camera_id, exc)
            return []

    # ── ROI ──────────────────────────────────────────────────────────────────

    def _apply_roi(self, frame: np.ndarray) -> np.ndarray:
        if not self.roi:
            return frame
        x, y, w, h = self.roi
        fh, fw = frame.shape[:2]
        return frame[max(0, y): min(fh, y + h), max(0, x): min(fw, x + w)]

    # ── Detecção de placas ────────────────────────────────────────────────────

    def _detect(self, crop: np.ndarray, now: float) -> list[PlateReading]:
        from plates.services import _get_alpr

        alpr = _get_alpr()
        results = alpr.predict(crop)
        readings: list[PlateReading] = []

        for r in results:
            if not r.ocr or not r.ocr.text:
                continue

            text = re.sub(r"[^A-Z0-9]", "", r.ocr.text.upper())
            if not text:
                continue

            conf = _avg_conf(r.ocr.confidence)
            tier = tier_for(conf)
            if tier is None:
                continue  # abaixo do limiar mínimo

            readings.append(PlateReading(
                text=text,
                confidence=conf,
                tier=tier,
                valid_format=validate_plate(text),
                bbox=_extract_bbox(r, crop.shape),
                timestamp=now,
            ))

        # Ordena por confiança desc — placas mais fortes processadas primeiro
        readings.sort(key=lambda r: r.confidence, reverse=True)

        if readings:
            logger.debug(
                "[lpr] camera_id=%s  %s placa(s) detectada(s): %s",
                self.camera_id,
                len(readings),
                " | ".join(f"{r.text}({float(r.confidence):.2f})" for r in readings),
            )

        return readings

    # ── Tracking (IoU) ────────────────────────────────────────────────────────

    def _match_tracks(self, readings: list[PlateReading], now: float) -> None:
        """Associa cada leitura ao track existente com maior IoU, ou cria novo."""
        used: set[int] = set()

        for reading in readings:
            best_iou, best_tid = TRACK_IOU_MIN, None

            for tid, track in self._tracks.items():
                if tid in used:
                    continue
                score = _iou(reading.bbox, track.bbox)
                if score > best_iou:
                    best_iou, best_tid = score, tid

            if best_tid is not None:
                self._update_track(best_tid, reading, now)
                used.add(best_tid)
            else:
                tid = self._create_track(reading, now)
                used.add(tid)

    def _create_track(self, reading: PlateReading, now: float) -> int:
        tid = self._next_id
        self._next_id += 1
        self._tracks[tid] = PlateTrack(
            track_id=tid,
            camera_id=self.camera_id,
            bbox=reading.bbox,
            readings=[reading],
            best=reading,
            created_at=now,
            last_seen=now,
        )
        logger.debug(
            "[lpr] track criado  camera_id=%s  track_id=%s  plate=%s  conf=%s  tier=%s",
            self.camera_id, tid, reading.text, round(float(reading.confidence), 4), reading.tier,
        )
        return tid

    def _update_track(self, tid: int, reading: PlateReading, now: float) -> None:
        track = self._tracks[tid]
        track.bbox = reading.bbox
        track.last_seen = now
        track.readings.append(reading)

        # Limite de memória por track
        if len(track.readings) > MAX_READINGS:
            track.readings = track.readings[-MAX_READINGS:]

        # Atualiza melhor leitura
        if track.best is None or reading.confidence > track.best.confidence:
            if track.best and reading.text != track.best.text:
                logger.debug(
                    "[lpr] track %s texto atualizado: %s → %s (conf %s → %s)",
                    tid, track.best.text, reading.text,
                    round(float(track.best.confidence), 4), round(float(reading.confidence), 4),
                )
            track.best = reading

    # ── Avaliação de confiança ────────────────────────────────────────────────

    def _evaluate_all(self, now: float) -> list[dict]:
        events = []
        for track in self._tracks.values():
            ev = self._evaluate_track(track, now)
            if ev:
                events.append(ev)
        return events

    def _evaluate_track(self, track: PlateTrack, now: float) -> dict | None:
        if track.confirmed or not track.best:
            return None

        best = track.best

        # Placa com formato inválido nunca confirma automaticamente
        # (pode ser leitura parcial ou ruído)
        if not best.valid_format and best.confidence < CONF_CONFIRM:
            return None

        # ≥ 0.90 → confirma imediatamente (mesmo formato inválido para revisão)
        if best.confidence >= CONF_CONFIRM:
            if self._is_dup(best.text, now):
                track.confirmed = True  # suprime sem emitir
                return None
            return self._build_event(track, best, "confirmed", now)

        # 0.70–0.89 + formato válido + ≥ 2 leituras → provisório
        if (best.confidence >= CONF_PROVISIONAL
                and best.valid_format
                and len(track.readings) >= 2):
            if self._is_dup(best.text, now):
                return None
            return self._build_event(track, best, "provisional", now)

        return None

    # ── Deduplicação ─────────────────────────────────────────────────────────

    def _redis_key(self, text: str) -> str:
        return f"lpr:dedup:{self.camera_id}:{text}"

    def _is_dup(self, text: str, now: float) -> bool:
        if self._redis is not None:
            try:
                return self._redis.exists(self._redis_key(text)) == 1
            except Exception:
                pass
        # fallback in-memory
        last = self._dedup.get(text)
        return last is not None and (now - last) < self._dedup_window

    def _mark_dup(self, text: str, now: float) -> None:
        if self._redis is not None:
            try:
                self._redis.set(
                    self._redis_key(text), "1",
                    nx=True, ex=int(self._dedup_window),
                )
                return
            except Exception:
                pass
        # fallback in-memory
        self._dedup[text] = now

    # ── Construção do evento ──────────────────────────────────────────────────

    def _build_event(
        self,
        track: PlateTrack,
        reading: PlateReading,
        status: str,
        now: float,
    ) -> dict:
        self._mark_dup(reading.text, now)
        if status in ("confirmed", "strong"):
            track.confirmed = True

        # Melhor texto entre todas as leituras (maioria + confiança)
        best_text = self._best_consensus_text(track)

        return {
            "camera_id":      self.camera_id,
            "track_id":       track.track_id,
            "plate":          best_text,
            "confidence":     round(reading.confidence, 4),
            "tier":           reading.tier,
            "valid_format":   reading.valid_format,
            "status":         status,
            "bbox":           reading.bbox,
            "readings_count": len(track.readings),
            "timestamp":      now,
        }

    def _best_consensus_text(self, track: PlateTrack) -> str:
        """
        Escolhe o texto com maior frequência × confiança entre as leituras.
        Em empate, usa a de maior confiança individual.
        """
        if not track.readings:
            return track.best.text if track.best else ""

        scores: dict[str, float] = {}
        for r in track.readings:
            scores[r.text] = scores.get(r.text, 0.0) + r.confidence

        return max(scores, key=lambda t: scores[t])

    # ── Expiração de tracks ───────────────────────────────────────────────────

    def _expire_tracks(self, now: float) -> list[dict]:
        """
        Remove tracks sem detecção recente.
        Emite evento final para tracks com leitura válida não confirmada.
        """
        stale = [
            tid for tid, t in self._tracks.items()
            if (now - t.last_seen) > self._track_max_age
        ]
        events = []
        for tid in stale:
            track = self._tracks.pop(tid)
            logger.debug(
                "[lpr] track expirado  camera_id=%s  track_id=%s  confirmed=%s",
                self.camera_id, tid, track.confirmed,
            )
            if not track.confirmed and track.best:
                best = track.best
                if (best.confidence >= CONF_PROVISIONAL
                        and best.valid_format
                        and not self._is_dup(best.text, now)):
                    events.append(self._build_event(track, best, "confirmed", now))

        # Limpa entradas antigas de dedup
        self._dedup = {
            k: v for k, v in self._dedup.items()
            if (now - v) < self._dedup_window
        }
        return events
