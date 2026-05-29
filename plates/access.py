import base64
import binascii
import re
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from common.tasks import dispatch_webhooks
from plates.models import AccessEvent, Alert, PlateEvent, PlateRegistry, VehiclePresence
from plates.tasks import process_plate_event
from plates.validators import sanitize_uploaded_image


def normalize_plate(plate: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def parse_captured_at(value: str | None):
    if not value:
        return timezone.now()
    parsed = parse_datetime(value)
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def image_from_base64(value: str | None):
    if not value:
        return None
    try:
        if "," in value:
            value = value.split(",", maxsplit=1)[1]
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise serializers.ValidationError({"image_base64": "Invalid base64 image."}) from exc

    if len(raw) > settings.INGEST_MAX_IMAGE_SIZE_BYTES:
        raise serializers.ValidationError({"image_base64": "Image exceeds ingest size limit."})

    return sanitize_uploaded_image(ContentFile(raw, name="ingest-image"))


def classify_plate(normalized_plate: str, confidence: Decimal | None = None) -> dict:
    return _classify_plate_from_queryset(PlateRegistry.objects.all(), normalized_plate, confidence)


def _classify_plate_from_queryset(
    queryset,
    normalized_plate: str,
    confidence: Decimal | None = None,
):
    if not normalized_plate:
        return {
            "registry": None,
            "list_type": "",
            "decision": AccessEvent.Decision.MANUAL_REVIEW,
            "reason": "Plate was not provided.",
        }

    if confidence is not None and confidence < Decimal(str(settings.UNKNOWN_PLATE_MIN_CONFIDENCE)):
        return {
            "registry": None,
            "list_type": "",
            "decision": AccessEvent.Decision.MANUAL_REVIEW,
            "reason": "Low confidence reading.",
        }

    blacklist = (
        queryset.filter(
            normalized_plate=normalized_plate,
            list_type=PlateRegistry.ListType.BLACKLIST,
            status=PlateRegistry.Status.ACTIVE,
        )
        .order_by("-created_at")
        .first()
    )
    if blacklist and blacklist.is_valid_now():
        return {
            "registry": blacklist,
            "list_type": PlateRegistry.ListType.BLACKLIST,
            "decision": AccessEvent.Decision.BLOCKED,
            "reason": blacklist.block_reason or "Plate is active in blacklist.",
        }

    whitelist = (
        queryset.filter(
            normalized_plate=normalized_plate,
            list_type=PlateRegistry.ListType.WHITELIST,
            status=PlateRegistry.Status.ACTIVE,
        )
        .order_by("-created_at")
        .first()
    )
    if whitelist:
        if whitelist.is_valid_now():
            return {
                "registry": whitelist,
                "list_type": PlateRegistry.ListType.WHITELIST,
                "decision": AccessEvent.Decision.ALLOWED,
                "reason": "Plate is active in whitelist.",
            }
        return {
            "registry": whitelist,
            "list_type": PlateRegistry.ListType.WHITELIST,
            "decision": AccessEvent.Decision.MANUAL_REVIEW,
            "reason": "Whitelist entry is outside validity period.",
        }

    unknown = None
    if settings.UNKNOWN_PLATE_AUTO_CREATE:
        unknown, _ = PlateRegistry.objects.get_or_create(
            tenant=queryset.model.objects.filter(pk__in=queryset.values("pk")).first().tenant
            if queryset.exists()
            else None,
            normalized_plate=normalized_plate,
            list_type=PlateRegistry.ListType.UNKNOWN,
            defaults={
                "plate": normalized_plate,
                "status": PlateRegistry.Status.ACTIVE,
                "notes": "Automatically created from access event.",
            },
        )
    return {
        "registry": unknown,
        "list_type": PlateRegistry.ListType.UNKNOWN,
        "decision": AccessEvent.Decision.UNKNOWN,
        "reason": "Plate is not registered in whitelist or blacklist.",
    }


@transaction.atomic
def create_access_event(
    *,
    camera,
    gateway=None,
    payload: dict,
    image=None,
    idempotency_key: str = "",
) -> AccessEvent:
    existing = _find_existing_event(camera, gateway, idempotency_key)
    if existing:
        return existing

    plate = payload.get("plate", "")
    tenant = camera.tenant or (gateway.tenant if gateway else None)
    normalized_plate = normalize_plate(plate)
    confidence = _decimal_or_none(payload.get("confidence"))
    movement_type = (
        payload.get("direction")
        or payload.get("movement_type")
        or camera.direction_default
    )
    captured_at = parse_captured_at(payload.get("captured_at"))

    plate_event = None
    access_image = image
    if image and not normalized_plate:
        plate_event = PlateEvent.objects.create(
            camera=camera,
            tenant=tenant,
            event_type=movement_type,
            image=image,
            captured_at=captured_at,
            raw_payload=payload,
        )
        access_image = plate_event.image

    decision = classify_plate_for_tenant(normalized_plate, tenant, confidence)
    status = AccessEvent.Status.PROCESSING if plate_event else AccessEvent.Status.PROCESSED

    event = AccessEvent.objects.create(
        camera=camera,
        tenant=tenant,
        gateway=gateway,
        plate_event=plate_event,
        plate_registry=decision["registry"],
        plate_text=plate,
        normalized_plate=normalized_plate,
        list_type_result=decision["list_type"],
        decision=decision["decision"],
        decision_reason=decision["reason"],
        movement_type=(
            movement_type
            if movement_type in AccessEvent.MovementType.values
            else AccessEvent.MovementType.UNKNOWN
        ),
        confidence=confidence,
        captured_at=captured_at,
        received_at=timezone.now(),
        processed_at=None if plate_event else timezone.now(),
        image=access_image,
        raw_payload=payload,
        status=status,
        idempotency_key=idempotency_key,
    )
    camera.mark_seen()
    if gateway:
        gateway.mark_seen(pending_events=gateway.pending_events)

    if not plate_event:
        finalize_access_event(event)
    else:
        process_plate_event.delay(plate_event.id)

    return event


@transaction.atomic
def finalize_access_event(event: AccessEvent) -> AccessEvent:
    if event.plate_text and not event.normalized_plate:
        event.normalized_plate = normalize_plate(event.plate_text)

    decision = classify_plate_for_tenant(event.normalized_plate, event.tenant, event.confidence)
    event.plate_registry = decision["registry"]
    event.list_type_result = decision["list_type"]
    event.decision = decision["decision"]
    event.decision_reason = decision["reason"]
    event.status = AccessEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(
        update_fields=[
            "plate_registry",
            "list_type_result",
            "decision",
            "decision_reason",
            "normalized_plate",
            "status",
            "processed_at",
            "updated_at",
        ]
    )
    update_vehicle_presence(event)
    create_alerts_for_event(event)
    _dispatch_access_webhook(event)
    return event


def update_vehicle_presence(event: AccessEvent) -> VehiclePresence | None:
    if not event.normalized_plate:
        return None

    presence, _ = VehiclePresence.objects.get_or_create(
        tenant=event.tenant,
        normalized_plate=event.normalized_plate,
        defaults={"plate_registry": event.plate_registry},
    )
    previous_status = presence.current_status
    presence.plate_registry = event.plate_registry or presence.plate_registry
    presence.last_seen_at = event.captured_at
    presence.location = event.camera.location if event.camera else presence.location

    if event.movement_type == AccessEvent.MovementType.ENTRY:
        if previous_status == VehiclePresence.CurrentStatus.INSIDE:
            presence.current_status = VehiclePresence.CurrentStatus.INCONSISTENT
            presence.inconsistency_reason = "Duplicate entry without previous exit."
            _create_alert(
                Alert.AlertType.DUPLICATE_ENTRY,
                event,
                Alert.Severity.WARNING,
                "Duplicate entry detected.",
            )
        else:
            presence.current_status = VehiclePresence.CurrentStatus.INSIDE
            presence.inconsistency_reason = ""
        presence.last_entry_event = event
        presence.entered_at = event.captured_at

    elif event.movement_type == AccessEvent.MovementType.EXIT:
        if previous_status not in {
            VehiclePresence.CurrentStatus.INSIDE,
            VehiclePresence.CurrentStatus.INCONSISTENT,
        }:
            presence.current_status = VehiclePresence.CurrentStatus.INCONSISTENT
            presence.inconsistency_reason = "Exit without previous entry."
            _create_alert(
                Alert.AlertType.EXIT_WITHOUT_ENTRY,
                event,
                Alert.Severity.WARNING,
                "Exit without previous entry detected.",
            )
        else:
            presence.current_status = VehiclePresence.CurrentStatus.OUTSIDE
            presence.inconsistency_reason = ""
        presence.last_exit_event = event
        presence.exited_at = event.captured_at

    presence.save()
    return presence


def create_alerts_for_event(event: AccessEvent) -> None:
    if event.decision == AccessEvent.Decision.BLOCKED and settings.BLACKLIST_ALERT_ENABLED:
        _create_alert(
            Alert.AlertType.BLACKLIST_DETECTED,
            event,
            Alert.Severity.CRITICAL,
            f"Blocked plate detected: {event.normalized_plate}",
        )
    elif event.decision == AccessEvent.Decision.UNKNOWN and settings.UNKNOWN_ALERT_ENABLED:
        _create_alert(
            Alert.AlertType.UNKNOWN_PLATE_DETECTED,
            event,
            Alert.Severity.WARNING,
            f"Unknown plate detected: {event.normalized_plate}",
        )
    elif event.decision == AccessEvent.Decision.MANUAL_REVIEW:
        _create_alert(
            Alert.AlertType.MANUAL_REVIEW_REQUIRED,
            event,
            Alert.Severity.WARNING,
            f"Manual review required for plate: {event.normalized_plate or 'unread'}",
        )


def access_event_payload(event: AccessEvent) -> dict:
    return {
        "event": "access.event",
        "timestamp": timezone.now().isoformat(),
        "data": {
            "id": event.id,
            "event_uuid": str(event.event_uuid),
            "plate": event.normalized_plate,
            "camera": event.camera.name if event.camera else "",
            "camera_id": event.camera_id,
            "gateway_id": event.gateway_id,
            "movement_type": event.movement_type,
            "decision": event.decision,
            "confidence": float(event.confidence) if event.confidence is not None else None,
            "captured_at": event.captured_at.isoformat(),
            "decision_reason": event.decision_reason,
        },
    }


def _create_alert(alert_type: str, event: AccessEvent, severity: str, message: str) -> Alert:
    return Alert.objects.create(
        alert_type=alert_type,
        tenant=event.tenant,
        access_event=event,
        plate=event.normalized_plate,
        camera=event.camera,
        gateway=event.gateway,
        severity=severity,
        message=message,
    )


def _find_existing_event(camera, gateway, idempotency_key: str) -> AccessEvent | None:
    if not idempotency_key:
        return None
    queryset = AccessEvent.objects.filter(idempotency_key=idempotency_key)
    if camera:
        queryset = queryset.filter(camera=camera)
    elif gateway:
        queryset = queryset.filter(gateway=gateway)
    return queryset.first()


def _decimal_or_none(value):
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def classify_plate_for_tenant(
    normalized_plate: str,
    tenant,
    confidence: Decimal | None = None,
) -> dict:
    from django.db.models import Q
    # Busca no tenant específico E em registros globais (tenant=None).
    # Registros com tenant=None funcionam como lista global para qualquer câmera.
    if tenant is not None:
        queryset = PlateRegistry.objects.filter(Q(tenant=tenant) | Q(tenant__isnull=True))
    else:
        queryset = PlateRegistry.objects.all()
    result = _classify_plate_from_queryset(queryset, normalized_plate, confidence)
    if (
        result["decision"] == AccessEvent.Decision.UNKNOWN
        and result["registry"] is None
        and normalized_plate
        and settings.UNKNOWN_PLATE_AUTO_CREATE
    ):
        unknown, _ = PlateRegistry.objects.get_or_create(
            tenant=tenant,
            normalized_plate=normalized_plate,
            list_type=PlateRegistry.ListType.UNKNOWN,
            defaults={
                "plate": normalized_plate,
                "status": PlateRegistry.Status.ACTIVE,
                "notes": "Automatically created from access event.",
            },
        )
        result["registry"] = unknown
    return result


def _dispatch_access_webhook(event: AccessEvent) -> None:
    payload = access_event_payload(event)
    if settings.CELERY_TASK_ALWAYS_EAGER:
        dispatch_webhooks("access.event", payload)
        return
    dispatch_webhooks.delay("access.event", payload)
