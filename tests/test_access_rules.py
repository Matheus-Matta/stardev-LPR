import pytest
from django.test import override_settings

from cameras.models import Camera
from plates.access import create_access_event, normalize_plate
from plates.models import AccessEvent, Alert, PlateRegistry, VehiclePresence


def test_normalize_plate_removes_formatting():
    assert normalize_plate(" abc-1d23 ") == "ABC1D23"


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_whitelist_plate_is_allowed_and_updates_presence():
    camera = Camera.objects.create(name="Gate", direction_default="entry")
    PlateRegistry.objects.create(
        plate="ABC1D23",
        normalized_plate="ABC1D23",
        list_type=PlateRegistry.ListType.WHITELIST,
    )

    event = create_access_event(
        camera=camera,
        payload={"plate": "ABC1D23", "direction": "entry", "confidence": 0.95},
        idempotency_key="evt-1",
    )

    assert event.decision == AccessEvent.Decision.ALLOWED
    presence = VehiclePresence.objects.get(normalized_plate="ABC1D23")
    assert presence.current_status == VehiclePresence.CurrentStatus.INSIDE


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_blacklist_plate_is_blocked_and_generates_alert():
    camera = Camera.objects.create(name="Gate")
    PlateRegistry.objects.create(
        plate="ZZZ9Z99",
        normalized_plate="ZZZ9Z99",
        list_type=PlateRegistry.ListType.BLACKLIST,
        block_reason="Security hold",
    )

    event = create_access_event(
        camera=camera,
        payload={"plate": "ZZZ9Z99", "confidence": 0.95},
        idempotency_key="evt-2",
    )

    assert event.decision == AccessEvent.Decision.BLOCKED
    assert Alert.objects.filter(alert_type=Alert.AlertType.BLACKLIST_DETECTED).exists()

