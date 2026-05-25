from pathlib import Path

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient

from cameras.models import Camera
from plates.access import normalize_plate
from plates.models import AccessEvent, PlateEvent, VehiclePresence
from plates.services import run_ocr_pipeline
from plates.validators import sanitize_uploaded_image

IMAGE_DIR = Path(__file__).resolve().parent / "image"


def sample_images():
    return sorted(
        path
        for path in IMAGE_DIR.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


def expected_plate(path: Path) -> str:
    return normalize_plate(path.stem.removeprefix("plate_").removeprefix("plate-"))[:7]


@pytest.mark.parametrize("image_path", sample_images(), ids=lambda path: path.name)
def test_sample_image_filenames_contain_expected_plate(image_path):
    assert expected_plate(image_path)
    assert len(expected_plate(image_path)) == 7


@pytest.mark.django_db
@pytest.mark.parametrize("image_path", sample_images(), ids=lambda path: path.name)
def test_sanitize_real_sample_images_preserves_plate_filename(image_path):
    uploaded = SimpleUploadedFile(
        image_path.name,
        image_path.read_bytes(),
        content_type="image/png" if image_path.suffix.lower() == ".png" else "image/jpeg",
    )

    sanitized = sanitize_uploaded_image(uploaded)

    assert expected_plate(image_path) in sanitized.name.upper()
    assert sanitized.size > 0


@pytest.mark.django_db
@pytest.mark.parametrize("image_path", sample_images(), ids=lambda path: path.name)
def test_ocr_pipeline_reads_plate_from_sample_image_filename(image_path):
    camera = Camera.objects.create(name=f"Camera {expected_plate(image_path)}")
    image = ContentFile(image_path.read_bytes(), name=image_path.name)
    event = PlateEvent.objects.create(camera=camera, image=image)

    result = run_ocr_pipeline(event)

    assert result["plate_text"] == expected_plate(image_path)
    assert result["confidence"] is not None
    assert result["raw_payload"]["engine"] == "filename_stub"
    assert result["raw_payload"]["image_sha256"].startswith("sha256:")


@pytest.mark.django_db
@pytest.mark.parametrize("image_path", sample_images(), ids=lambda path: path.name)
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_camera_ingest_image_finishes_access_event_with_plate(image_path, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    cache.clear()
    camera = Camera.objects.create(name="Gate", direction_default="entry")
    token = camera.rotate_ingest_token()
    client = APIClient()
    uploaded = SimpleUploadedFile(
        image_path.name,
        image_path.read_bytes(),
        content_type="image/png" if image_path.suffix.lower() == ".png" else "image/jpeg",
    )

    response = client.post(
        f"/api/v1/ingest/cameras/{camera.camera_key}/events/",
        {
            "direction": "entry",
            "captured_at": "2026-05-23T10:42:00-03:00",
            "image": uploaded,
        },
        format="multipart",
        HTTP_X_CAMERA_TOKEN=token,
        HTTP_IDEMPOTENCY_KEY=f"image-{expected_plate(image_path)}",
    )

    assert response.status_code == 202

    access_event = AccessEvent.objects.get(idempotency_key=f"image-{expected_plate(image_path)}")
    plate_event = access_event.plate_event
    plate_event.refresh_from_db()
    access_event.refresh_from_db()

    assert plate_event.status == PlateEvent.Status.COMPLETED
    assert plate_event.plate_text == expected_plate(image_path)
    assert access_event.status == AccessEvent.Status.PROCESSED
    assert access_event.normalized_plate == expected_plate(image_path)
    assert access_event.raw_payload["direction"] == "entry"
    assert access_event.raw_payload.get("image") is None
    assert VehiclePresence.objects.filter(normalized_plate=expected_plate(image_path)).exists()
