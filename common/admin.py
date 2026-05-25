from django.contrib import admin
from unfold.admin import ModelAdmin

from common.models import (
    AIModelArtifact,
    AuditLog,
    DataProcessingRecord,
    DataSubjectRequest,
    DeadLetterTask,
    SecurityIncident,
    WebhookDelivery,
    WebhookSubscription,
)
from tenants.admin_mixins import TenantScopedAdminMixin


@admin.register(DeadLetterTask)
class DeadLetterTaskAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = (
        "tenant",
        "task_name",
        "queue",
        "status",
        "retries",
        "created_at",
        "reprocessed_at",
    )
    list_filter = ("tenant", "queue", "status", "created_at")
    search_fields = ("task_name", "task_id", "exception_message")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuditLog)
class AuditLogAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = ("tenant", "action", "user", "ip_address", "path", "created_at")
    list_filter = ("tenant", "action", "created_at")
    search_fields = ("action", "path", "user__username")
    readonly_fields = ("action", "user", "ip_address", "path", "metadata", "created_at")


@admin.register(WebhookSubscription)
class WebhookSubscriptionAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = ("tenant", "event_type", "url", "is_active", "created_at")
    list_filter = ("tenant", "event_type", "is_active")
    search_fields = ("url",)
    exclude = ("secret_encrypted",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = (
        "tenant",
        "event_type",
        "status",
        "response_status_code",
        "attempts",
        "created_at",
    )
    list_filter = ("tenant", "event_type", "status", "created_at")
    search_fields = ("subscription__url", "error_message", "response_body")
    readonly_fields = (
        "subscription",
        "event_type",
        "payload",
        "status",
        "response_status_code",
        "response_body",
        "error_message",
        "attempts",
        "created_at",
        "delivered_at",
        "updated_at",
    )


@admin.register(AIModelArtifact)
class AIModelArtifactAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = (
        "tenant",
        "kind",
        "version",
        "is_active",
        "file_sha256",
        "promoted_at",
        "created_at",
    )
    list_filter = ("tenant", "kind", "is_active", "created_at")
    search_fields = ("version", "storage_uri", "file_sha256")
    readonly_fields = ("created_at", "updated_at", "promoted_at")


@admin.register(DataProcessingRecord)
class DataProcessingRecordAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = ("tenant", "name", "legal_basis", "retention_days", "is_active")
    list_filter = ("tenant", "is_active", "legal_basis")
    search_fields = ("name", "purpose", "legal_basis")


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = ("tenant", "request_type", "requester_name", "status", "due_at", "created_at")
    list_filter = ("tenant", "request_type", "status", "created_at")
    search_fields = ("requester_name", "requester_contact", "plate_text")


@admin.register(SecurityIncident)
class SecurityIncidentAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = ("tenant", "title", "status", "detected_at", "anpd_due_at", "anpd_notified_at")
    list_filter = ("tenant", "status", "detected_at")
    search_fields = ("title", "description", "mitigation_notes")
