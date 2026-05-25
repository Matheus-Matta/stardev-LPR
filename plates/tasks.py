import logging
import traceback

import requests
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common.models import DeadLetterTask
from common.tasks import dispatch_webhooks
from plates.models import PlateEvent
from plates.services import run_ocr_pipeline

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=settings.CELERY_OCR_MAX_RETRIES,
    queue="ocr",
    acks_late=True,
    time_limit=settings.TASK_TIME_LIMIT_OCR,
    soft_time_limit=settings.TASK_SOFT_TIME_LIMIT_OCR,
)
def process_plate_event(self, event_id: int) -> None:
    try:
        with transaction.atomic():
            event = PlateEvent.objects.select_for_update().get(id=event_id)
            event.status = PlateEvent.Status.PROCESSING
            event.error_message = ""
            event.save(update_fields=["status", "error_message", "updated_at"])

        result = run_ocr_pipeline(event)

        PlateEvent.objects.filter(id=event_id).update(
            status=PlateEvent.Status.COMPLETED,
            plate_text=result["plate_text"],
            confidence=result["confidence"],
            raw_payload=result["raw_payload"],
            pipeline_metadata=result["pipeline_metadata"],
            error_message="",
            updated_at=timezone.now(),
        )
        _finalize_linked_access_event(event_id, result)
        dispatch_webhooks.delay("plate.read", _plate_payload(event_id))
    except SoftTimeLimitExceeded as exc:
        PlateEvent.objects.filter(id=event_id).update(
            status=PlateEvent.Status.ERROR,
            error_message="Timeout during OCR processing.",
            updated_at=timezone.now(),
        )
        failure = _create_dead_letter(self, event_id, exc)
        notify_dead_letter.delay(failure.id)
        dispatch_webhooks.delay("plate.error", _plate_payload(event_id))
        raise
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            PlateEvent.objects.filter(id=event_id).update(
                status=PlateEvent.Status.ERROR,
                error_message=str(exc),
                updated_at=timezone.now(),
            )
            failure = _create_dead_letter(self, event_id, exc)
            notify_dead_letter.delay(failure.id)
            dispatch_webhooks.delay("plate.error", _plate_payload(event_id))
            raise

        countdown = min((2 ** self.request.retries) * 10, 300)
        logger.warning(
            "Retrying OCR event %s in %s seconds after error: %s",
            event_id,
            countdown,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown) from exc


@shared_task(queue="ocr")
def reprocess_plate_event(event_id: int) -> None:
    PlateEvent.objects.filter(id=event_id).update(
        status=PlateEvent.Status.PENDING,
        error_message="",
        updated_at=timezone.now(),
    )
    process_plate_event.delay(event_id)


@shared_task(queue="dead", max_retries=3, default_retry_delay=60)
def notify_dead_letter(dead_letter_id: int) -> None:
    failure = DeadLetterTask.objects.get(id=dead_letter_id)
    dispatch_webhooks.delay("task.dead_letter", _dead_letter_payload(failure))

    if not settings.DEAD_LETTER_WEBHOOK_URL:
        logger.error("Task moved to DLQ: %s", failure)
        return

    response = requests.post(
        settings.DEAD_LETTER_WEBHOOK_URL,
        json={
            "event": "task.dead_letter",
            "task_name": failure.task_name,
            "task_id": failure.task_id,
            "queue": failure.queue,
            "exception_class": failure.exception_class,
            "exception_message": failure.exception_message,
            "created_at": failure.created_at.isoformat(),
        },
        timeout=5,
    )
    response.raise_for_status()


def _create_dead_letter(task, event_id: int, exc: Exception) -> DeadLetterTask:
    return DeadLetterTask.objects.create(
        task_name=task.name,
        task_id=task.request.id or "",
        queue="dead",
        payload={"event_id": event_id},
        exception_class=exc.__class__.__name__,
        exception_message=str(exc),
        traceback=traceback.format_exc(),
        retries=task.request.retries,
    )


def _plate_payload(event_id: int) -> dict:
    event = PlateEvent.objects.select_related("camera").get(id=event_id)
    return {
        "event": "plate.error" if event.status == PlateEvent.Status.ERROR else "plate.read",
        "timestamp": timezone.now().isoformat(),
        "data": {
            "id": event.id,
            "plate": event.plate_text,
            "camera": event.camera.name,
            "camera_id": event.camera_id,
            "event_type": event.event_type,
            "confidence": float(event.confidence) if event.confidence is not None else None,
            "status": event.status,
            "captured_at": event.captured_at.isoformat(),
            "error_message": event.error_message,
        },
    }


def _dead_letter_payload(failure: DeadLetterTask) -> dict:
    return {
        "event": "task.dead_letter",
        "timestamp": timezone.now().isoformat(),
        "data": {
            "id": failure.id,
            "task_name": failure.task_name,
            "task_id": failure.task_id,
            "queue": failure.queue,
            "payload": failure.payload,
            "exception_class": failure.exception_class,
            "exception_message": failure.exception_message,
            "retries": failure.retries,
            "created_at": failure.created_at.isoformat(),
        },
    }


def _finalize_linked_access_event(event_id: int, result: dict) -> None:
    event = PlateEvent.objects.filter(id=event_id).first()
    if not event or not hasattr(event, "access_event"):
        return

    access_event = event.access_event
    access_event.plate_text = result["plate_text"]
    access_event.confidence = result["confidence"]
    access_event.raw_payload = {
        **access_event.raw_payload,
        "ocr_result": result["raw_payload"],
        "pipeline_metadata": result["pipeline_metadata"],
    }
    access_event.save(update_fields=["plate_text", "confidence", "raw_payload", "updated_at"])

    from plates.access import finalize_access_event

    finalize_access_event(access_event)
