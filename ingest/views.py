import logging
import threading
from datetime import timedelta

import cv2
import numpy as np
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from cameras.models import Camera, Gateway
from common.audit import write_audit_log
from common.models import AuditLog
from ingest.throttles import CameraIngestRateThrottle, GatewayIngestRateThrottle
from plates.access import create_access_event, image_from_base64
from plates.validators import sanitize_uploaded_image

logger = logging.getLogger(__name__)

TOKEN_HEADER = "HTTP_X_CAMERA_TOKEN"
GATEWAY_TOKEN_HEADER = "HTTP_X_GATEWAY_TOKEN"
IDEMPOTENCY_HEADER = "HTTP_IDEMPOTENCY_KEY"

# ── LPR pipeline cache (uma instância por câmera) ─────────────────────────────

_pipeline_cache: dict[int, object] = {}
_pipeline_lock = threading.Lock()


def _get_pipeline(camera_id: int):
    with _pipeline_lock:
        if camera_id not in _pipeline_cache:
            from plates.lpr_pipeline import LPRPipeline
            _pipeline_cache[camera_id] = LPRPipeline(camera_id=camera_id)
        return _pipeline_cache[camera_id]


def _image_to_frame(image_field) -> np.ndarray | None:
    """Converte UploadedFile / FieldFile para array numpy BGR."""
    try:
        image_field.seek(0)
        raw = np.frombuffer(image_field.read(), dtype=np.uint8)
        frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        return frame if frame is not None else None
    except Exception as exc:
        logger.debug("[ingest] _image_to_frame erro: %s", exc)
        return None


def _run_pipeline(camera_id: int, image_field) -> list:
    """Roda o LPR pipeline em uma imagem. Retorna lista de PlateEvent criados."""
    from cameras.tasks import _save_plate_event

    frame = _image_to_frame(image_field)
    if frame is None:
        return []

    pipeline = _get_pipeline(camera_id)
    events = pipeline.process_frame(frame)
    saved = []
    for ev in events:
        try:
            obj = _save_plate_event(ev, frame)
            if obj is not None:
                saved.append(obj)
        except Exception as exc:
            logger.warning("[ingest] save_plate_event erro  camera_id=%s: %s", camera_id, exc)
    return saved


class CameraEventIngestAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    throttle_classes = [CameraIngestRateThrottle]

    def post(self, request, camera_key: str):
        camera = _get_active_camera(camera_key)
        if not camera:
            _invalid_attempt(request, "camera_ingest.invalid_camera", {"camera_key": camera_key})
            return Response(
                {"detail": "Camera not found or inactive."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if settings.INGEST_REQUIRE_CAMERA_TOKEN and not camera.verify_ingest_token(
            request.META.get(TOKEN_HEADER, "")
        ):
            _invalid_attempt(
                request,
                "camera_ingest.invalid_token",
                {"camera_key": camera_key},
                camera,
            )
            return Response(
                {"detail": "Invalid camera token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        payload = _event_payload(request)
        image = _extract_image(request)

        # Se chegou imagem, roda o LPR pipeline (OCR + tracking + dedup)
        if image is not None:
            saved = _run_pipeline(camera.id, image)
            if saved:
                first = saved[0]
                return Response(
                    {
                        "status": "accepted",
                        "event_id": first.id,
                        "event_uuid": str(first.event_uuid),
                        "processing_status": first.status,
                        "detections": len(saved),
                    },
                    status=status.HTTP_202_ACCEPTED,
                )
            # Pipeline não gerou eventos confirmados (sem placa ou provisório)
            return Response({"status": "no_plate"}, status=status.HTTP_202_ACCEPTED)

        # Sem imagem → a câmera envia o texto da placa no payload (fluxo legado)
        event = create_access_event(
            camera=camera,
            payload=payload,
            image=None,
            idempotency_key=request.META.get(IDEMPOTENCY_HEADER, ""),
        )
        return Response(
            {
                "status": "accepted",
                "event_id": event.id,
                "event_uuid": str(event.event_uuid),
                "processing_status": event.status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class GatewayEventIngestAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    throttle_classes = [GatewayIngestRateThrottle]

    def post(self, request, gateway_key: str):
        gateway = _get_active_gateway(gateway_key)
        if not gateway:
            _invalid_attempt(
                request,
                "gateway_ingest.invalid_gateway",
                {"gateway_key": gateway_key},
            )
            return Response(
                {"detail": "Gateway not found or inactive."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if settings.INGEST_REQUIRE_GATEWAY_TOKEN and not gateway.verify_token(
            request.META.get(GATEWAY_TOKEN_HEADER, "")
        ):
            _invalid_attempt(
                request,
                "gateway_ingest.invalid_token",
                {"gateway_key": gateway_key},
                gateway=gateway,
            )
            return Response(
                {"detail": "Invalid gateway token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        payload = _event_payload(request)
        camera = _camera_from_gateway_payload(gateway, payload)
        if not camera:
            return Response(
                {"detail": "No active camera matched the gateway payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        image = _extract_image(request)

        # Se chegou imagem, roda o LPR pipeline (OCR + tracking + dedup)
        if image is not None:
            saved = _run_pipeline(camera.id, image)
            if saved:
                first = saved[0]
                return Response(
                    {
                        "status": "accepted",
                        "event_id": first.id,
                        "event_uuid": str(first.event_uuid),
                        "processing_status": first.status,
                        "detections": len(saved),
                    },
                    status=status.HTTP_202_ACCEPTED,
                )
            return Response({"status": "no_plate"}, status=status.HTTP_202_ACCEPTED)

        # Sem imagem → gateway envia texto da placa no payload (fluxo legado)
        event = create_access_event(
            camera=camera,
            gateway=gateway,
            payload=payload,
            image=None,
            idempotency_key=request.META.get(IDEMPOTENCY_HEADER, ""),
        )
        return Response(
            {
                "status": "accepted",
                "event_id": event.id,
                "event_uuid": str(event.event_uuid),
                "processing_status": event.status,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class GatewayHeartbeatAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = [GatewayIngestRateThrottle]

    def post(self, request, gateway_key: str):
        gateway = _get_active_gateway(gateway_key)
        if not gateway:
            _invalid_attempt(
                request,
                "gateway_heartbeat.invalid_gateway",
                {"gateway_key": gateway_key},
            )
            return Response(
                {"detail": "Gateway not found or inactive."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if settings.INGEST_REQUIRE_GATEWAY_TOKEN and not gateway.verify_token(
            request.META.get(GATEWAY_TOKEN_HEADER, "")
        ):
            _invalid_attempt(
                request,
                "gateway_heartbeat.invalid_token",
                {"gateway_key": gateway_key},
                gateway=gateway,
            )
            return Response(
                {"detail": "Invalid gateway token."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        gateway.mark_seen(
            version=request.data.get("version", ""),
            pending_events=_int_or_none(request.data.get("pending_events")),
            cameras_online=_int_or_none(request.data.get("cameras_online")),
            cameras_offline=_int_or_none(request.data.get("cameras_offline")),
        )
        return Response(
            {
                "status": "ok",
                "gateway": gateway.gateway_key,
                "server_time": timezone.now().isoformat(),
            }
        )


def _get_active_camera(camera_key: str) -> Camera | None:
    return Camera.objects.filter(camera_key=camera_key, is_active=True).first()


def _get_active_gateway(gateway_key: str) -> Gateway | None:
    return Gateway.objects.filter(gateway_key=gateway_key, is_active=True).first()


def _camera_from_gateway_payload(gateway: Gateway, payload: dict) -> Camera | None:
    external_id = payload.get("camera_external_id") or payload.get("camera_key")
    queryset = Camera.objects.filter(gateway=gateway, is_active=True)
    if external_id:
        return queryset.filter(
            Q(camera_key=external_id) | Q(name=external_id) | Q(location=external_id)
        ).first()
    if queryset.count() == 1:
        return queryset.first()
    return None


def _extract_image(request):
    if uploaded := request.FILES.get("image"):
        return sanitize_uploaded_image(uploaded)
    return image_from_base64(request.data.get("image_base64"))


def _event_payload(request) -> dict:
    payload = request.data.dict() if hasattr(request.data, "dict") else dict(request.data)
    payload.pop("image", None)
    if "image_base64" in payload:
        payload["image_base64"] = "[redacted]"
    return payload


def _invalid_attempt(request, action: str, metadata: dict, camera=None, gateway=None) -> None:
    entity_type = _entity_type(camera, gateway)
    entity_id = _entity_id(camera, gateway)
    write_audit_log(
        request,
        action,
        metadata=metadata,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    _auto_block_after_failures(action, camera, gateway)


def _auto_block_after_failures(action: str, camera=None, gateway=None) -> None:
    entity_type = _entity_type(camera, gateway)
    entity_id = _entity_id(camera, gateway)
    if not entity_type or not entity_id:
        return
    cutoff = timezone.now() - timedelta(minutes=10)
    failures = AuditLog.objects.filter(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        created_at__gte=cutoff,
    ).count()
    if failures < 10:
        return
    target = camera or gateway
    target.is_active = False
    target.save(update_fields=["is_active", "updated_at"])


def _entity_type(camera=None, gateway=None) -> str:
    if camera:
        return camera.__class__.__name__
    if gateway:
        return gateway.__class__.__name__
    return ""


def _entity_id(camera=None, gateway=None) -> str:
    if camera:
        return str(camera.id)
    if gateway:
        return str(gateway.id)
    return ""


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
