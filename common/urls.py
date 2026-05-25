from django.urls import path

from common.views import (
    AIModelArtifactDetailAPIView,
    AIModelArtifactListCreateAPIView,
    AIModelPromoteAPIView,
    DataProcessingRecordDetailAPIView,
    DataProcessingRecordListCreateAPIView,
    DataSubjectRequestDetailAPIView,
    DataSubjectRequestListCreateAPIView,
    DeadLetterListAPIView,
    DeadLetterReprocessAPIView,
    MonitoringSummaryAPIView,
    SecurityIncidentDetailAPIView,
    SecurityIncidentListCreateAPIView,
    WebhookDeliveryListAPIView,
    WebhookSubscriptionDetailAPIView,
    WebhookSubscriptionListCreateAPIView,
)

urlpatterns = [
    path("dead-letter/", DeadLetterListAPIView.as_view(), name="dead-letter-list"),
    path(
        "dead-letter/<int:pk>/reprocess/",
        DeadLetterReprocessAPIView.as_view(),
        name="dead-letter-reprocess",
    ),
    path(
        "webhooks/",
        WebhookSubscriptionListCreateAPIView.as_view(),
        name="webhook-subscription-list",
    ),
    path(
        "webhooks/<int:pk>/",
        WebhookSubscriptionDetailAPIView.as_view(),
        name="webhook-subscription-detail",
    ),
    path(
        "webhook-deliveries/",
        WebhookDeliveryListAPIView.as_view(),
        name="webhook-delivery-list",
    ),
    path("models/", AIModelArtifactListCreateAPIView.as_view(), name="ai-model-list"),
    path("models/<int:pk>/", AIModelArtifactDetailAPIView.as_view(), name="ai-model-detail"),
    path("models/<int:pk>/promote/", AIModelPromoteAPIView.as_view(), name="ai-model-promote"),
    path("lgpd/ropt/", DataProcessingRecordListCreateAPIView.as_view(), name="ropt-list"),
    path("lgpd/ropt/<int:pk>/", DataProcessingRecordDetailAPIView.as_view(), name="ropt-detail"),
    path(
        "lgpd/requests/",
        DataSubjectRequestListCreateAPIView.as_view(),
        name="data-subject-request-list",
    ),
    path(
        "lgpd/requests/<int:pk>/",
        DataSubjectRequestDetailAPIView.as_view(),
        name="data-subject-request-detail",
    ),
    path("lgpd/incidents/", SecurityIncidentListCreateAPIView.as_view(), name="incident-list"),
    path(
        "lgpd/incidents/<int:pk>/",
        SecurityIncidentDetailAPIView.as_view(),
        name="incident-detail",
    ),
    path("monitoring/", MonitoringSummaryAPIView.as_view(), name="monitoring-summary"),
]
