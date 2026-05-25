import logging
import subprocess

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from cameras.models import Camera
from plates.access import create_access_event

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    queue="capture",
    acks_late=True,
    time_limit=settings.RTSP_READ_TIMEOUT + 5,
    soft_time_limit=settings.RTSP_READ_TIMEOUT,
)
def capture_camera_frame(self, camera_id: int) -> dict:
    camera = Camera.objects.get(id=camera_id)

    if camera.connection_mode == Camera.ConnectionMode.PUSH:
        return {"camera_id": camera.id, "status": "skipped", "reason": "PUSH mode"}

    url = camera.capture_rtsp_url
    logger.info("capture camera_id=%s url=%s", camera.id, url)

    try:
        image_bytes = _grab_frame(url, timeout=settings.RTSP_READ_TIMEOUT)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning("frame capture failed camera_id=%s: %s", camera.id, exc)
        raise self.retry(exc=exc, countdown=5, max_retries=2) from exc

    ts = timezone.now().strftime("%Y%m%d_%H%M%S")
    image_file = ContentFile(image_bytes, name=f"cap_{camera.camera_key}_{ts}.png")

    event = create_access_event(
        camera=camera,
        payload={
            "source": "rtsp_capture",
            "captured_at": timezone.now().isoformat(),
        },
        image=image_file,
    )

    logger.info(
        "captured camera_id=%s event_id=%s event_uuid=%s",
        camera.id,
        event.id,
        event.event_uuid,
    )
    return {
        "camera_id": camera.id,
        "status": "captured",
        "event_id": event.id,
        "event_uuid": str(event.event_uuid),
    }


def _grab_frame(rtsp_url: str, timeout: int) -> bytes:
    """Captura um único frame via ffmpeg e retorna os bytes PNG."""
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-frames:v", "1",
            "-f", "image2pipe",
            "-vcodec", "png",
            "pipe:1",
        ],
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr_tail = result.stderr[-500:].decode("utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg exit {result.returncode}: {stderr_tail}")
    if not result.stdout:
        raise RuntimeError("ffmpeg returned empty output")
    return result.stdout
