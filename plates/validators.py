import io
import uuid
from pathlib import Path

import magic
from django.conf import settings
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

ALLOWED_MIME_TYPES = {
    "image/jpeg": ("JPEG", ".jpg"),
    "image/png":  ("PNG",  ".png"),
    "image/webp": ("WEBP", ".webp"),
}

# Qualidade JPEG de saída para imagens externas (uploads via API).
# Todos os formatos aceitos são normalizados para JPEG para economizar disco.
_UPLOAD_JPEG_QUALITY = 82


def sanitize_uploaded_image(uploaded_file) -> ContentFile:
    if uploaded_file.size > settings.UPLOAD_MAX_SIZE_BYTES:
        raise serializers.ValidationError(
            f"Image exceeds the {settings.UPLOAD_MAX_SIZE_MB} MB limit."
        )

    header = uploaded_file.read(4096)
    uploaded_file.seek(0)
    mime_type = magic.from_buffer(header, mime=True)
    if mime_type not in ALLOWED_MIME_TYPES:
        raise serializers.ValidationError("Unsupported image type.")

    try:
        image = Image.open(uploaded_file)
        image.load()
    except UnidentifiedImageError as exc:
        raise serializers.ValidationError("Invalid or corrupted image.") from exc

    # Normaliza para JPEG independente do formato de entrada (economia de disco).
    # PNG/WebP com canal alpha: converte para RGB antes de codificar.
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=_UPLOAD_JPEG_QUALITY, optimize=True)
    output.seek(0)

    original_stem = Path(uploaded_file.name).stem[:40] if uploaded_file.name else "upload"
    safe_name = f"{original_stem}-{uuid.uuid4().hex}.jpg"
    return ContentFile(output.read(), name=safe_name)

