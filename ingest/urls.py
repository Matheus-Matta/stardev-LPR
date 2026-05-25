from django.urls import path

from ingest.views import (
    CameraEventIngestAPIView,
    GatewayEventIngestAPIView,
    GatewayHeartbeatAPIView,
)

urlpatterns = [
    path(
        "cameras/<str:camera_key>/events/",
        CameraEventIngestAPIView.as_view(),
        name="camera-event-ingest",
    ),
    path(
        "gateways/<str:gateway_key>/events/",
        GatewayEventIngestAPIView.as_view(),
        name="gateway-event-ingest",
    ),
    path(
        "gateways/<str:gateway_key>/heartbeat/",
        GatewayHeartbeatAPIView.as_view(),
        name="gateway-heartbeat",
    ),
]

