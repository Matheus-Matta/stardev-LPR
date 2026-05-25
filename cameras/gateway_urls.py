from django.urls import path

from cameras.views import GatewayDetailAPIView, GatewayListCreateAPIView, GatewayRotateTokenAPIView

urlpatterns = [
    path("", GatewayListCreateAPIView.as_view(), name="gateway-list"),
    path("<int:pk>/", GatewayDetailAPIView.as_view(), name="gateway-detail"),
    path(
        "<int:pk>/rotate-token/",
        GatewayRotateTokenAPIView.as_view(),
        name="gateway-rotate-token",
    ),
]
