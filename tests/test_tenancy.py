import pytest
from django.test import override_settings

from cameras.models import Camera
from plates.access import create_access_event
from plates.models import AccessEvent, PlateRegistry
from tenants.models import Business, Tenant


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_plate_registry_is_scoped_by_tenant():
    business = Business.objects.create(name="Operadora")
    tenant_a = Tenant.objects.create(business=business, name="Condominio A", slug="cond-a")
    tenant_b = Tenant.objects.create(business=business, name="Condominio B", slug="cond-b")
    camera_a = Camera.objects.create(name="A entrada", tenant=tenant_a)
    camera_b = Camera.objects.create(name="B entrada", tenant=tenant_b)
    PlateRegistry.objects.create(
        tenant=tenant_a,
        plate="ABC1D23",
        normalized_plate="ABC1D23",
        list_type=PlateRegistry.ListType.WHITELIST,
    )

    event_a = create_access_event(
        camera=camera_a,
        payload={"plate": "ABC1D23", "confidence": 0.95},
        idempotency_key="tenant-a-event",
    )
    event_b = create_access_event(
        camera=camera_b,
        payload={"plate": "ABC1D23", "confidence": 0.95},
        idempotency_key="tenant-b-event",
    )

    assert event_a.decision == AccessEvent.Decision.ALLOWED
    assert event_b.decision == AccessEvent.Decision.UNKNOWN

