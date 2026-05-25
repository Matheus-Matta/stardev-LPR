import logging

import redis
from django.conf import settings
from django.db import connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from common.mlops import promote_model
from common.models import (
    AIModelArtifact,
    DataProcessingRecord,
    DataSubjectRequest,
    DeadLetterTask,
    SecurityIncident,
    WebhookDelivery,
    WebhookSubscription,
)
from common.serializers import (
    AIModelArtifactSerializer,
    DataProcessingRecordSerializer,
    DataSubjectRequestSerializer,
    DeadLetterTaskSerializer,
    SecurityIncidentSerializer,
    WebhookDeliverySerializer,
    WebhookSubscriptionSerializer,
)
from tenants.utils import get_request_tenant, tenant_queryset_for_user

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get(self, request):
        checks = {"database": False, "redis": False, "celery": True}
        modes = {
            "cache": "locmem" if settings.DEBUG and not settings.USE_REDIS_IN_DEBUG else "redis",
            "celery": "eager" if settings.CELERY_TASK_ALWAYS_EAGER else "worker",
        }

        try:
            connection.ensure_connection()
            checks["database"] = True
        except Exception:
            logger.exception("Database health check failed")

        if settings.REDIS_REQUIRED:
            try:
                client = redis.from_url(settings.REDIS_URL, socket_timeout=1)
                checks["redis"] = bool(client.ping())
            except Exception:
                logger.exception("Redis health check failed")
        else:
            checks["redis"] = True

        is_healthy = all(checks.values())
        return Response(
            {
                "status": "ok" if is_healthy else "degraded",
                "checks": checks,
                "modes": modes,
                "timestamp": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class TokenLogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response(
                {"detail": "Refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class DeadLetterListAPIView(generics.ListAPIView):
    queryset = DeadLetterTask.objects.all()
    serializer_class = DeadLetterTaskSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )


class DeadLetterReprocessAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        dead_letter = get_object_or_404(
            tenant_queryset_for_user(DeadLetterTask.objects.all(), request.user),
            pk=pk,
        )
        event_id = dead_letter.payload.get("event_id")
        if not event_id:
            return Response(
                {"detail": "Dead-letter task does not contain an event_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from plates.tasks import reprocess_plate_event

        reprocess_plate_event.delay(event_id)
        dead_letter.status = DeadLetterTask.Status.REPROCESSED
        dead_letter.reprocessed_at = timezone.now()
        dead_letter.save(update_fields=["status", "reprocessed_at", "updated_at"])
        return Response(DeadLetterTaskSerializer(dead_letter).data)


class WebhookSubscriptionListCreateAPIView(generics.ListCreateAPIView):
    queryset = WebhookSubscription.objects.all()
    serializer_class = WebhookSubscriptionSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=get_request_tenant(self.request))


class WebhookSubscriptionDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = WebhookSubscription.objects.all()
    serializer_class = WebhookSubscriptionSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class WebhookDeliveryListAPIView(generics.ListAPIView):
    queryset = WebhookDelivery.objects.select_related("subscription")
    serializer_class = WebhookDeliverySerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )


class AIModelArtifactListCreateAPIView(generics.ListCreateAPIView):
    queryset = AIModelArtifact.objects.all()
    serializer_class = AIModelArtifactSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=get_request_tenant(self.request))


class AIModelArtifactDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = AIModelArtifact.objects.all()
    serializer_class = AIModelArtifactSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class AIModelPromoteAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        model = get_object_or_404(
            tenant_queryset_for_user(AIModelArtifact.objects.all(), request.user),
            pk=pk,
        )
        promote_model(model)
        return Response(AIModelArtifactSerializer(model).data)


class DataProcessingRecordListCreateAPIView(generics.ListCreateAPIView):
    queryset = DataProcessingRecord.objects.all()
    serializer_class = DataProcessingRecordSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=get_request_tenant(self.request))


class DataProcessingRecordDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = DataProcessingRecord.objects.all()
    serializer_class = DataProcessingRecordSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class DataSubjectRequestListCreateAPIView(generics.ListCreateAPIView):
    queryset = DataSubjectRequest.objects.all()
    serializer_class = DataSubjectRequestSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=get_request_tenant(self.request))


class DataSubjectRequestDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = DataSubjectRequest.objects.all()
    serializer_class = DataSubjectRequestSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class SecurityIncidentListCreateAPIView(generics.ListCreateAPIView):
    queryset = SecurityIncident.objects.all()
    serializer_class = SecurityIncidentSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=get_request_tenant(self.request))


class SecurityIncidentDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = SecurityIncident.objects.all()
    serializer_class = SecurityIncidentSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class MonitoringSummaryAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        queue_lengths = _redis_queue_lengths()
        return Response(
            {
                "thresholds": {
                    "ocr_queue_pending": settings.ALERT_OCR_QUEUE_PENDING,
                    "cpu_percent": settings.ALERT_CPU_PERCENT,
                    "disk_percent": settings.ALERT_DISK_PERCENT,
                    "ocr_error_rate_percent": settings.ALERT_OCR_ERROR_RATE_PERCENT,
                },
                "queues": queue_lengths,
                "alerts": _queue_alerts(queue_lengths),
            }
        )


def _redis_queue_lengths() -> dict:
    try:
        client = redis.from_url(settings.REDIS_URL, socket_timeout=1)
        return {
            queue: client.llen(queue)
            for queue in ["capture", "ocr", "reports", "dead"]
        }
    except Exception:
        logger.exception("Queue monitoring failed")
        return {}


def _queue_alerts(queue_lengths: dict) -> list[dict]:
    alerts = []
    ocr_pending = queue_lengths.get("ocr", 0)
    if ocr_pending > settings.ALERT_OCR_QUEUE_PENDING:
        alerts.append(
            {
                "metric": "ocr_queue_pending",
                "value": ocr_pending,
                "threshold": settings.ALERT_OCR_QUEUE_PENDING,
                "severity": "alert",
            }
        )
    return alerts
