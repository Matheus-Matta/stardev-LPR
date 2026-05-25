import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from cameras.models import Camera
from plates.models import AccessEvent


@pytest.mark.django_db
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_camera_ingest_requires_valid_token():
    cache.clear()
    camera = Camera.objects.create(name="Gate", direction_default="entry")
    token = camera.rotate_ingest_token()
    client = APIClient()

    rejected = client.post(
        f"/api/v1/ingest/cameras/{camera.camera_key}/events/",
        {"plate": "ABC1D23", "direction": "entry"},
        format="json",
        HTTP_X_CAMERA_TOKEN="bad-token",
    )
    accepted = client.post(
        f"/api/v1/ingest/cameras/{camera.camera_key}/events/",
        {"plate": "ABC1D23", "direction": "entry"},
        format="json",
        HTTP_X_CAMERA_TOKEN=token,
        HTTP_IDEMPOTENCY_KEY="camera-event-1",
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 202
    assert AccessEvent.objects.filter(idempotency_key="camera-event-1").exists()

