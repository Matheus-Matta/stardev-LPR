import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.generic import TemplateView
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from cameras.models import Camera
from common.audit import write_audit_log
from plates.access import finalize_access_event, normalize_plate
from plates.models import AccessEvent, Alert, PlateEvent, PlateRegistry, VehiclePresence
from plates.serializers import (
    AccessEventCorrectionSerializer,
    AccessEventDecisionSerializer,
    AccessEventSerializer,
    AlertResolveSerializer,
    AlertSerializer,
    PlateEventSerializer,
    PlateRegistrySerializer,
    PlateUploadSerializer,
    VehiclePresenceCorrectionSerializer,
    VehiclePresenceSerializer,
)
from plates.tasks import process_plate_event
from plates.throttles import UploadBurstRateThrottle
from tenants.utils import get_request_tenant, tenant_queryset_for_user

logger = logging.getLogger(__name__)


class AccessEventDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "plates/access_events_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        queryset = AccessEvent.objects.select_related("camera", "gateway").order_by("-captured_at")
        queryset = tenant_queryset_for_user(
            queryset,
            self.request.user,
            params.get("tenant_id"),
        )
        if decision := params.get("decision"):
            queryset = queryset.filter(decision=decision)
        if plate := params.get("plate"):
            queryset = queryset.filter(normalized_plate__icontains=normalize_plate(plate))
        if camera_id := params.get("camera"):
            queryset = queryset.filter(camera_id=camera_id)

        context["events"] = queryset[:100]
        context["cameras"] = tenant_queryset_for_user(
            Camera.objects.order_by("name"),
            self.request.user,
            params.get("tenant_id"),
        )
        context["filters"] = params
        return context


class PlateUploadAPIView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle, UploadBurstRateThrottle]
    throttle_scope = "upload"

    def throttled(self, request, wait):
        write_audit_log(
            request,
            "upload.throttled",
            {"retry_after_seconds": wait},
        )
        return super().throttled(request, wait)

    def post(self, request):
        serializer = PlateUploadSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            write_audit_log(
                request,
                "upload.invalid",
                {"errors": serializer.errors},
            )
            logger.warning(
                "Invalid upload attempt by user_id=%s errors=%s",
                getattr(request.user, "id", None),
                serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        event = serializer.save()
        write_audit_log(request, "upload.accepted", {"event_id": event.id})
        process_plate_event.delay(event.id)
        return Response(PlateEventSerializer(event).data, status=status.HTTP_201_CREATED)


class PlateEventListAPIView(generics.ListAPIView):
    queryset = PlateEvent.objects.select_related("camera")
    serializer_class = PlateEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )
        params = self.request.query_params

        if camera_id := params.get("camera"):
            queryset = queryset.filter(camera_id=camera_id)
        if status_value := params.get("status"):
            queryset = queryset.filter(status=status_value)
        if plate := params.get("plate"):
            queryset = queryset.filter(plate_text__icontains=plate)
        if captured_from := _parse_aware_datetime(params.get("captured_from")):
            queryset = queryset.filter(captured_at__gte=captured_from)
        if captured_to := _parse_aware_datetime(params.get("captured_to")):
            queryset = queryset.filter(captured_at__lte=captured_to)

        local_date = parse_date(params.get("local_date", ""))
        local_timezone = params.get("timezone")
        if local_date and local_timezone:
            start, end = _local_day_bounds(local_date, local_timezone)
            queryset = queryset.filter(captured_at__gte=start, captured_at__lt=end)

        return queryset


class PlateEventDetailAPIView(generics.RetrieveAPIView):
    queryset = PlateEvent.objects.select_related("camera")
    serializer_class = PlateEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class PlateRegistryListCreateAPIView(generics.ListCreateAPIView):
    queryset = PlateRegistry.objects.all()
    serializer_class = PlateRegistrySerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        queryset = tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )
        params = self.request.query_params
        if list_type := params.get("list_type"):
            queryset = queryset.filter(list_type=list_type)
        if status_value := params.get("status"):
            queryset = queryset.filter(status=status_value)
        if plate := params.get("plate"):
            queryset = queryset.filter(normalized_plate__icontains=normalize_plate(plate))
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save(tenant=get_request_tenant(self.request))
        write_audit_log(
            self.request,
            f"plate_registry.{instance.list_type}.created",
            tenant=instance.tenant,
            entity_type="PlateRegistry",
            entity_id=str(instance.id),
            new_value=PlateRegistrySerializer(instance).data,
        )


class PlateRegistryDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = PlateRegistry.objects.all()
    serializer_class = PlateRegistrySerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)

    def perform_update(self, serializer):
        old_value = PlateRegistrySerializer(self.get_object()).data
        instance = serializer.save()
        write_audit_log(
            self.request,
            "plate_registry.updated",
            tenant=instance.tenant,
            entity_type="PlateRegistry",
            entity_id=str(instance.id),
            old_value=old_value,
            new_value=PlateRegistrySerializer(instance).data,
        )

    def perform_destroy(self, instance):
        old_value = PlateRegistrySerializer(instance).data
        instance.status = PlateRegistry.Status.INACTIVE
        instance.save(update_fields=["status", "updated_at"])
        write_audit_log(
            self.request,
            "plate_registry.inactivated",
            tenant=instance.tenant,
            entity_type="PlateRegistry",
            entity_id=str(instance.id),
            old_value=old_value,
            new_value=PlateRegistrySerializer(instance).data,
        )


class PlateRegistryMoveAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int, list_type: str):
        source = get_object_or_404(
            tenant_queryset_for_user(PlateRegistry.objects.all(), request.user),
            pk=pk,
        )
        target, _ = PlateRegistry.objects.update_or_create(
            tenant=source.tenant,
            normalized_plate=source.normalized_plate,
            list_type=list_type,
            defaults={
                "plate": source.plate,
                "status": PlateRegistry.Status.ACTIVE,
                "owner_name": source.owner_name,
                "owner_document": source.owner_document,
                "vehicle_model": source.vehicle_model,
                "vehicle_color": source.vehicle_color,
                "vehicle_type": source.vehicle_type,
                "notes": source.notes,
                "updated_by": request.user,
            },
        )
        write_audit_log(
            request,
            f"plate_registry.moved_to_{list_type}",
            tenant=target.tenant,
            entity_type="PlateRegistry",
            entity_id=str(target.id),
            old_value=PlateRegistrySerializer(source).data,
            new_value=PlateRegistrySerializer(target).data,
        )
        return Response(PlateRegistrySerializer(target).data)


class AccessEventListAPIView(generics.ListAPIView):
    queryset = AccessEvent.objects.select_related("camera", "gateway", "plate_registry")
    serializer_class = AccessEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )
        params = self.request.query_params
        if camera_id := params.get("camera"):
            queryset = queryset.filter(camera_id=camera_id)
        if gateway_id := params.get("gateway"):
            queryset = queryset.filter(gateway_id=gateway_id)
        if decision := params.get("decision"):
            queryset = queryset.filter(decision=decision)
        if movement_type := params.get("movement_type"):
            queryset = queryset.filter(movement_type=movement_type)
        if plate := params.get("plate"):
            queryset = queryset.filter(normalized_plate__icontains=normalize_plate(plate))
        if captured_from := _parse_aware_datetime(params.get("captured_from")):
            queryset = queryset.filter(captured_at__gte=captured_from)
        if captured_to := _parse_aware_datetime(params.get("captured_to")):
            queryset = queryset.filter(captured_at__lte=captured_to)
        return queryset


class AccessEventDetailAPIView(generics.RetrieveAPIView):
    queryset = AccessEvent.objects.select_related("camera", "gateway", "plate_registry")
    serializer_class = AccessEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class AccessEventCorrectPlateAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        event = get_object_or_404(
            tenant_queryset_for_user(AccessEvent.objects.all(), request.user),
            pk=pk,
        )
        serializer = AccessEventCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_value = AccessEventSerializer(event).data
        event.plate_text = serializer.validated_data["plate"]
        event.normalized_plate = normalize_plate(event.plate_text)
        event.reviewed_by = request.user
        event.reviewed_at = timezone.now()
        event.save(
            update_fields=[
                "plate_text",
                "normalized_plate",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )
        finalize_access_event(event)
        event.refresh_from_db()
        write_audit_log(
            request,
            "access_event.plate_corrected",
            tenant=event.tenant,
            entity_type="AccessEvent",
            entity_id=str(event.id),
            old_value=old_value,
            new_value=AccessEventSerializer(event).data,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(AccessEventSerializer(event).data)


class AccessEventMarkReviewedAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        event = get_object_or_404(
            tenant_queryset_for_user(AccessEvent.objects.all(), request.user),
            pk=pk,
        )
        event.reviewed_by = request.user
        event.reviewed_at = timezone.now()
        event.save(update_fields=["reviewed_by", "reviewed_at", "updated_at"])
        write_audit_log(
            request,
            "access_event.reviewed",
            tenant=event.tenant,
            entity_type="AccessEvent",
            entity_id=str(event.id),
            reason=request.data.get("reason", ""),
        )
        return Response(AccessEventSerializer(event).data)


class AccessEventChangeDecisionAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        event = get_object_or_404(
            tenant_queryset_for_user(AccessEvent.objects.all(), request.user),
            pk=pk,
        )
        serializer = AccessEventDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_value = AccessEventSerializer(event).data
        event.decision = serializer.validated_data["decision"]
        event.decision_reason = serializer.validated_data.get("reason", "")
        event.reviewed_by = request.user
        event.reviewed_at = timezone.now()
        event.save(
            update_fields=[
                "decision",
                "decision_reason",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )
        write_audit_log(
            request,
            "access_event.decision_changed",
            tenant=event.tenant,
            entity_type="AccessEvent",
            entity_id=str(event.id),
            old_value=old_value,
            new_value=AccessEventSerializer(event).data,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(AccessEventSerializer(event).data)


class VehiclePresenceListAPIView(generics.ListAPIView):
    queryset = VehiclePresence.objects.select_related("plate_registry")
    serializer_class = VehiclePresenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )


class VehiclePresenceCurrentInsideAPIView(generics.ListAPIView):
    serializer_class = VehiclePresenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return tenant_queryset_for_user(
            VehiclePresence.objects.filter(current_status=VehiclePresence.CurrentStatus.INSIDE),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )


class VehiclePresenceManualCorrectionAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        presence = get_object_or_404(
            tenant_queryset_for_user(VehiclePresence.objects.all(), request.user),
            pk=pk,
        )
        serializer = VehiclePresenceCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_value = VehiclePresenceSerializer(presence).data
        presence.current_status = serializer.validated_data["current_status"]
        presence.inconsistency_reason = ""
        presence.save(update_fields=["current_status", "inconsistency_reason", "updated_at"])
        write_audit_log(
            request,
            "vehicle_presence.manual_correction",
            tenant=presence.tenant,
            entity_type="VehiclePresence",
            entity_id=str(presence.id),
            old_value=old_value,
            new_value=VehiclePresenceSerializer(presence).data,
            reason=serializer.validated_data["reason"],
        )
        return Response(VehiclePresenceSerializer(presence).data)


class AlertListAPIView(generics.ListAPIView):
    queryset = Alert.objects.select_related("camera", "gateway", "access_event")
    serializer_class = AlertSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )
        params = self.request.query_params
        if status_value := params.get("status"):
            queryset = queryset.filter(status=status_value)
        if alert_type := params.get("alert_type"):
            queryset = queryset.filter(alert_type=alert_type)
        return queryset


class AlertResolveAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        alert = get_object_or_404(
            tenant_queryset_for_user(Alert.objects.all(), request.user),
            pk=pk,
        )
        serializer = AlertResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        alert.status = Alert.Status.RESOLVED
        alert.notes = serializer.validated_data.get("notes", "")
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.save(update_fields=["status", "notes", "resolved_by", "resolved_at", "updated_at"])
        write_audit_log(
            request,
            "alert.resolved",
            tenant=alert.tenant,
            entity_type="Alert",
            entity_id=str(alert.id),
            reason=alert.notes,
        )
        return Response(AlertSerializer(alert).data)


def _parse_aware_datetime(value: str | None):
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, UTC)
    return parsed


def _local_day_bounds(local_date, timezone_name: str):
    try:
        local_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_tz = ZoneInfo("UTC")

    start = datetime.combine(local_date, time.min, tzinfo=local_tz)
    end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=local_tz)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))
