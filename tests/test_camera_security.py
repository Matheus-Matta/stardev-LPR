import pytest

from cameras.models import Camera


@pytest.mark.django_db
def test_camera_password_is_encrypted_at_rest(settings):
    settings.FIELD_ENCRYPTION_KEY = "test-secret"
    camera = Camera.objects.create(
        name="Gate",
        host="10.0.0.10",
        username="admin",
    )
    camera.set_password("super-secret")
    camera.save()

    camera.refresh_from_db()

    assert camera.password_encrypted
    assert camera.password_encrypted != "super-secret"
    assert camera.get_password() == "super-secret"
    assert "super-secret" not in camera.masked_rtsp_url

