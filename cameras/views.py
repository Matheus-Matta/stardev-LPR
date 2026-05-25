from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from cameras.models import Camera, Gateway
from cameras.serializers import CameraSerializer, GatewaySerializer
from common.audit import write_audit_log
from tenants.utils import get_request_tenant, tenant_queryset_for_user


class CameraListCreateAPIView(generics.ListCreateAPIView):
    queryset = Camera.objects.all()
    serializer_class = CameraSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=get_request_tenant(self.request))


class CameraDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Camera.objects.all()
    serializer_class = CameraSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class CameraRotateTokenAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        camera = get_object_or_404(
            tenant_queryset_for_user(Camera.objects.all(), request.user),
            pk=pk,
        )
        token = camera.rotate_ingest_token()
        write_audit_log(
            request,
            "camera.token_rotated",
            tenant=camera.tenant,
            entity_type="Camera",
            entity_id=str(camera.id),
            new_value={"camera_key": camera.camera_key, "rotated_at": timezone.now().isoformat()},
        )
        return Response({"camera_key": camera.camera_key, "token": token})


class GatewayListCreateAPIView(generics.ListCreateAPIView):
    queryset = Gateway.objects.all()
    serializer_class = GatewaySerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(
            super().get_queryset(),
            self.request.user,
            self.request.headers.get("X-Tenant-ID") or self.request.query_params.get("tenant_id"),
        )

    def perform_create(self, serializer):
        serializer.save(tenant=get_request_tenant(self.request))


class GatewayDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Gateway.objects.all()
    serializer_class = GatewaySerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        return tenant_queryset_for_user(super().get_queryset(), self.request.user)


class GatewayRotateTokenAPIView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk: int):
        gateway = get_object_or_404(
            tenant_queryset_for_user(Gateway.objects.all(), request.user),
            pk=pk,
        )
        token = gateway.rotate_token()
        write_audit_log(
            request,
            "gateway.token_rotated",
            tenant=gateway.tenant,
            entity_type="Gateway",
            entity_id=str(gateway.id),
            new_value={
                "gateway_key": gateway.gateway_key,
                "rotated_at": timezone.now().isoformat(),
            },
        )
        return Response(
            {"gateway_key": gateway.gateway_key, "token": token},
            status=status.HTTP_200_OK,
        )
