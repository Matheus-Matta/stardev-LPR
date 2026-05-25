from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.models import AIModelArtifact


def get_active_model(kind: str) -> AIModelArtifact | None:
    return AIModelArtifact.objects.filter(kind=kind, is_active=True).first()


def promote_model(model: AIModelArtifact) -> AIModelArtifact:
    with transaction.atomic():
        AIModelArtifact.objects.filter(kind=model.kind, is_active=True).exclude(
            id=model.id
        ).update(is_active=False)
        model.is_active = True
        model.promoted_at = timezone.now()
        model.save(update_fields=["is_active", "promoted_at", "updated_at"])
    return model


def active_model_metadata() -> dict:
    yolo = get_active_model(AIModelArtifact.Kind.YOLO)
    ocr = get_active_model(AIModelArtifact.Kind.OCR)

    return {
        "yolo_model": yolo.version if yolo else settings.YOLO_MODEL_VERSION,
        "yolo_model_hash": yolo.file_sha256 if yolo else "",
        "yolo_model_uri": yolo.storage_uri if yolo else "",
        "ocr_engine": ocr.version if ocr else "stub",
        "ocr_version": ocr.version if ocr else settings.OCR_ENGINE_VERSION,
        "ocr_model_hash": ocr.file_sha256 if ocr else "",
        "ocr_model_uri": ocr.storage_uri if ocr else "",
    }
