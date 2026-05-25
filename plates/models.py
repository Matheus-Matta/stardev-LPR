import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class PlateEvent(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        ERROR = "error", "Error"

    class EventType(models.TextChoices):
        ENTRY = "entry", "Entry"
        EXIT = "exit", "Exit"
        UNKNOWN = "unknown", "Unknown"

    camera = models.ForeignKey("cameras.Camera", on_delete=models.PROTECT, related_name="events")
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="plate_events",
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        default=EventType.UNKNOWN,
    )
    image = models.ImageField(upload_to="plate-events/%Y/%m/%d/")
    captured_at = models.DateTimeField(default=timezone.now)
    plate_text = models.CharField(max_length=16, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    raw_payload = models.JSONField(default=dict, blank=True)
    pipeline_metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-captured_at", "-id"]
        indexes = [
            models.Index(fields=["plate_text"]),
            models.Index(fields=["status", "captured_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.plate_text or 'unread'} @ {self.camera_id}"


class PlateRegistry(models.Model):
    class ListType(models.TextChoices):
        WHITELIST = "whitelist", "Whitelist"
        BLACKLIST = "blacklist", "Blacklist"
        UNKNOWN = "unknown", "Unknown"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        IGNORED = "ignored", "Ignored"

    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    plate = models.CharField(max_length=16)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="plate_registries",
    )
    normalized_plate = models.CharField(max_length=16)
    list_type = models.CharField(max_length=32, choices=ListType.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.ACTIVE)
    owner_name = models.CharField(max_length=160, blank=True)
    owner_document = models.CharField(max_length=80, blank=True)
    vehicle_model = models.CharField(max_length=120, blank=True)
    vehicle_color = models.CharField(max_length=80, blank=True)
    vehicle_type = models.CharField(max_length=80, blank=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    block_reason = models.CharField(max_length=255, blank=True)
    risk_level = models.CharField(
        max_length=32,
        choices=RiskLevel.choices,
        default=RiskLevel.MEDIUM,
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_plate_registries",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_plate_registries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["normalized_plate", "list_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "normalized_plate", "list_type"],
                name="unique_plate_per_registry_type",
            )
        ]
        indexes = [
            models.Index(fields=["normalized_plate", "list_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.normalized_plate} ({self.list_type})"

    def is_valid_now(self, at=None) -> bool:
        at = at or timezone.now()
        if self.status != self.Status.ACTIVE:
            return False
        if self.valid_from and self.valid_from > at:
            return False
        if self.valid_until and self.valid_until < at:
            return False
        return True


class AccessEvent(models.Model):
    class MovementType(models.TextChoices):
        ENTRY = "entry", "Entry"
        EXIT = "exit", "Exit"
        UNKNOWN = "unknown", "Unknown"

    class Decision(models.TextChoices):
        ALLOWED = "allowed", "Allowed"
        BLOCKED = "blocked", "Blocked"
        UNKNOWN = "unknown", "Unknown"
        MANUAL_REVIEW = "manual_review", "Manual review"
        ERROR = "error", "Error"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        ERROR = "error", "Error"

    event_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="access_events",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="access_events",
    )
    gateway = models.ForeignKey(
        "cameras.Gateway",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_events",
    )
    plate_event = models.OneToOneField(
        PlateEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_event",
    )
    plate_registry = models.ForeignKey(
        PlateRegistry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_events",
    )
    plate_text = models.CharField(max_length=16, blank=True)
    normalized_plate = models.CharField(max_length=16, blank=True)
    list_type_result = models.CharField(max_length=32, blank=True)
    decision = models.CharField(
        max_length=32,
        choices=Decision.choices,
        default=Decision.UNKNOWN,
    )
    decision_reason = models.TextField(blank=True)
    movement_type = models.CharField(
        max_length=32,
        choices=MovementType.choices,
        default=MovementType.UNKNOWN,
    )
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    captured_at = models.DateTimeField(default=timezone.now)
    received_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)
    image = models.ImageField(upload_to="access-events/%Y/%m/%d/", blank=True)
    crop_image = models.ImageField(upload_to="access-events/crops/%Y/%m/%d/", blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.RECEIVED)
    error_message = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=120, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_access_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-captured_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["camera", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_camera_idempotency_key",
            ),
            models.UniqueConstraint(
                fields=["gateway", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="unique_gateway_idempotency_key",
            )
        ]
        indexes = [
            models.Index(fields=["normalized_plate", "captured_at"]),
            models.Index(fields=["camera", "captured_at"]),
            models.Index(fields=["decision", "captured_at"]),
            models.Index(fields=["movement_type", "captured_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.normalized_plate or 'unread'} ({self.decision})"


class VehiclePresence(models.Model):
    class CurrentStatus(models.TextChoices):
        INSIDE = "inside", "Inside"
        OUTSIDE = "outside", "Outside"
        INCONSISTENT = "inconsistent", "Inconsistent"
        UNKNOWN = "unknown", "Unknown"

    normalized_plate = models.CharField(max_length=16)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vehicle_presence_records",
    )
    plate_registry = models.ForeignKey(
        PlateRegistry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="presence_records",
    )
    current_status = models.CharField(
        max_length=32,
        choices=CurrentStatus.choices,
        default=CurrentStatus.UNKNOWN,
    )
    last_entry_event = models.ForeignKey(
        AccessEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    last_exit_event = models.ForeignKey(
        AccessEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    entered_at = models.DateTimeField(null=True, blank=True)
    exited_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    inconsistency_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["normalized_plate"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "normalized_plate"],
                name="unique_vehicle_presence_per_tenant",
            )
        ]

    def __str__(self) -> str:
        return f"{self.normalized_plate} ({self.current_status})"


class Alert(models.Model):
    class AlertType(models.TextChoices):
        BLACKLIST_DETECTED = "blacklist_detected", "Blacklist detected"
        UNKNOWN_PLATE_DETECTED = "unknown_plate_detected", "Unknown plate detected"
        MANUAL_REVIEW_REQUIRED = "manual_review_required", "Manual review required"
        GATEWAY_OFFLINE = "gateway_offline", "Gateway offline"
        CAMERA_OFFLINE = "camera_offline", "Camera offline"
        DUPLICATE_ENTRY = "duplicate_entry", "Duplicate entry"
        EXIT_WITHOUT_ENTRY = "exit_without_entry", "Exit without entry"

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    alert_type = models.CharField(max_length=64, choices=AlertType.choices)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="alerts",
    )
    access_event = models.ForeignKey(
        AccessEvent,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    plate = models.CharField(max_length=16, blank=True)
    camera = models.ForeignKey(
        "cameras.Camera",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts",
    )
    gateway = models.ForeignKey(
        "cameras.Gateway",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts",
    )
    severity = models.CharField(max_length=32, choices=Severity.choices, default=Severity.WARNING)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    message = models.TextField()
    notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_alerts",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["alert_type", "status", "created_at"]),
            models.Index(fields=["plate", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.alert_type} ({self.status})"
