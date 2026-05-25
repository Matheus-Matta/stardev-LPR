import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import serializers

from plates.validators import sanitize_uploaded_image


@pytest.mark.django_db
def test_rejects_fake_image_extension():
    uploaded = SimpleUploadedFile("fake.jpg", b"not a real image", content_type="image/jpeg")

    with pytest.raises(serializers.ValidationError):
        sanitize_uploaded_image(uploaded)

