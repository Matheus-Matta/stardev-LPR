from django.urls import path

from plates.views import (
    AccessEventChangeDecisionAPIView,
    AccessEventCorrectPlateAPIView,
    AccessEventDetailAPIView,
    AccessEventListAPIView,
    AccessEventMarkReviewedAPIView,
    AlertListAPIView,
    AlertResolveAPIView,
    PlateEventDetailAPIView,
    PlateEventListAPIView,
    PlateRegistryDetailAPIView,
    PlateRegistryListCreateAPIView,
    PlateRegistryMoveAPIView,
    PlateUploadAPIView,
    VehiclePresenceCurrentInsideAPIView,
    VehiclePresenceListAPIView,
    VehiclePresenceManualCorrectionAPIView,
)

urlpatterns = [
    path("upload/", PlateUploadAPIView.as_view(), name="plate-upload"),
    path("events/", PlateEventListAPIView.as_view(), name="plate-event-list"),
    path("events/<int:pk>/", PlateEventDetailAPIView.as_view(), name="plate-event-detail"),
    path("registry/", PlateRegistryListCreateAPIView.as_view(), name="plate-registry-list"),
    path("registry/<int:pk>/", PlateRegistryDetailAPIView.as_view(), name="plate-registry-detail"),
    path(
        "registry/<int:pk>/move-to-whitelist/",
        PlateRegistryMoveAPIView.as_view(),
        {"list_type": "whitelist"},
        name="plate-registry-move-whitelist",
    ),
    path(
        "registry/<int:pk>/move-to-blacklist/",
        PlateRegistryMoveAPIView.as_view(),
        {"list_type": "blacklist"},
        name="plate-registry-move-blacklist",
    ),
    path("access-events/", AccessEventListAPIView.as_view(), name="access-event-list"),
    path("access-events/<int:pk>/", AccessEventDetailAPIView.as_view(), name="access-event-detail"),
    path(
        "access-events/<int:pk>/correct-plate/",
        AccessEventCorrectPlateAPIView.as_view(),
        name="access-event-correct-plate",
    ),
    path(
        "access-events/<int:pk>/mark-as-reviewed/",
        AccessEventMarkReviewedAPIView.as_view(),
        name="access-event-mark-reviewed",
    ),
    path(
        "access-events/<int:pk>/change-decision/",
        AccessEventChangeDecisionAPIView.as_view(),
        name="access-event-change-decision",
    ),
    path("vehicle-presence/", VehiclePresenceListAPIView.as_view(), name="vehicle-presence-list"),
    path(
        "vehicle-presence/current-inside/",
        VehiclePresenceCurrentInsideAPIView.as_view(),
        name="vehicle-presence-current-inside",
    ),
    path(
        "vehicle-presence/<int:pk>/manual-correction/",
        VehiclePresenceManualCorrectionAPIView.as_view(),
        name="vehicle-presence-manual-correction",
    ),
    path("alerts/", AlertListAPIView.as_view(), name="alert-list"),
    path("alerts/<int:pk>/resolve/", AlertResolveAPIView.as_view(), name="alert-resolve"),
]
