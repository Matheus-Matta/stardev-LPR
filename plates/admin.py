from django.contrib import admin
from unfold.admin import ModelAdmin

from plates.models import AccessEvent, Alert, PlateEvent, PlateRegistry, VehiclePresence
from tenants.admin_mixins import TenantScopedAdminMixin


@admin.register(PlateEvent)
class PlateEventAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = ("id", "tenant", "camera", "plate_text", "status", "event_type", "captured_at")
    list_filter = ("tenant", "status", "event_type", "captured_at")
    search_fields = ("plate_text", "camera__name", "error_message")
    readonly_fields = ("created_at", "updated_at", "pipeline_metadata", "raw_payload")


@admin.register(PlateRegistry)
class PlateRegistryAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = (
        "tenant",
        "normalized_plate",
        "list_type",
        "status",
        "owner_name",
        "valid_until",
    )
    list_filter = ("tenant", "list_type", "status", "risk_level")
    search_fields = ("plate", "normalized_plate", "owner_name", "owner_document", "notes")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AccessEvent)
class AccessEventAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = (
        "normalized_plate",
        "tenant",
        "camera",
        "gateway",
        "movement_type",
        "decision",
        "captured_at",
    )
    list_filter = ("tenant", "decision", "movement_type", "status", "captured_at")
    search_fields = ("plate_text", "normalized_plate", "idempotency_key", "decision_reason")
    readonly_fields = ("event_uuid", "received_at", "processed_at", "created_at", "updated_at")


@admin.register(VehiclePresence)
class VehiclePresenceAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = ("tenant", "normalized_plate", "current_status", "last_seen_at", "location")
    list_filter = ("tenant", "current_status")
    search_fields = ("normalized_plate", "location", "inconsistency_reason")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Alert)
class AlertAdmin(TenantScopedAdminMixin, ModelAdmin):
    list_display = (
        "tenant",
        "alert_type",
        "plate",
        "severity",
        "status",
        "camera",
        "gateway",
        "created_at",
    )
    list_filter = ("tenant", "alert_type", "severity", "status", "created_at")
    search_fields = ("plate", "message", "notes")
    readonly_fields = ("created_at", "updated_at")
