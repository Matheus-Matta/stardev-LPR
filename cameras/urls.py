from django.urls import path

from cameras.views import (
    CameraDetailAPIView,
    CameraListCreateAPIView,
    CameraRotateTokenAPIView,
    GatewayDetailAPIView,
    GatewayListCreateAPIView,
    GatewayRotateTokenAPIView,
)

urlpatterns = [
    path("", CameraListCreateAPIView.as_view(), name="camera-list"),
    path("<int:pk>/", CameraDetailAPIView.as_view(), name="camera-detail"),
    path("<int:pk>/rotate-token/", CameraRotateTokenAPIView.as_view(), name="camera-rotate-token"),
    path("gateways/", GatewayListCreateAPIView.as_view(), name="gateway-list"),
    path("gateways/<int:pk>/", GatewayDetailAPIView.as_view(), name="gateway-detail"),
    path(
        "gateways/<int:pk>/rotate-token/",
        GatewayRotateTokenAPIView.as_view(),
        name="gateway-rotate-token",
    ),
]
