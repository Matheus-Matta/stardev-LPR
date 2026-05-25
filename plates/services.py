import hashlib
import re
import socket
import time
from decimal import Decimal
from pathlib import Path

from django.utils import timezone

from common.mlops import active_model_metadata
from plates.models import PlateEvent


def run_ocr_pipeline(event: PlateEvent) -> dict:
    started = timezone.now()
    detection_started = time.perf_counter()

    # Stub intentionally keeps the system usable before the real YOLO/OCR engines are wired.
    image_hash = _sha256_file(event.image)
    detection_ms = int((time.perf_counter() - detection_started) * 1000)

    ocr_started = time.perf_counter()
    ocr_ms = int((time.perf_counter() - ocr_started) * 1000)

    finished = timezone.now()
    model_metadata = active_model_metadata()
    plate_text = _plate_from_filename(event.image)
    confidence = Decimal("0.99") if plate_text else None
    return {
        "plate_text": plate_text,
        "confidence": confidence,
        "raw_payload": {
            "engine": "filename_stub",
            "message": (
                "Plate inferred from filename for dev/test."
                if plate_text
                else "OCR engine not configured yet."
            ),
            "image_sha256": image_hash,
            "filename": event.image.name,
        },
        "pipeline_metadata": {
            **model_metadata,
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


def _sha256_file(field_file) -> str:
    digest = hashlib.sha256()
    position = field_file.tell() if hasattr(field_file, "tell") else None
    try:
        field_file.seek(0)
        for chunk in field_file.chunks():
            digest.update(chunk)
    finally:
        if position is not None:
            field_file.seek(position)
    return f"sha256:{digest.hexdigest()}"


def _plate_from_filename(field_file) -> str:
    stem = Path(field_file.name or "").stem.upper()
    explicit = re.search(r"(?:^|[_-])PLATE[_-]?([A-Z0-9]{7})(?:$|[_-])", stem)
    if explicit:
        return explicit.group(1)

    direct = re.search(r"^([A-Z0-9]{7})(?:$|[_-])", stem)
    if direct:
        return direct.group(1)

    return ""
