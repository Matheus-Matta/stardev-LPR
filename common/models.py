from django.db import models

from common.crypto import decrypt_text, encrypt_text


class DeadLetterTask(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        REPROCESSED = "reprocessed", "Reprocessed"
        IGNORED = "ignored", "Ignored"

    task_name = models.CharField(max_length=255)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dead_letter_tasks",
    )
    task_id = models.CharField(max_length=255, blank=True)
    queue = models.CharField(max_length=64, default="dead")
    payload = models.JSONField(default=dict, blank=True)
    exception_class = models.CharField(max_length=255, blank=True)
    exception_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)
    retries = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    reprocessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.task_name} ({self.status})"


class AuditLog(models.Model):
    action = models.CharField(max_length=120)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    user = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=500, blank=True)
    entity_type = models.CharField(max_length=120, blank=True)
    entity_id = models.CharField(max_length=120, blank=True)
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self) -> str:
        return self.action


class WebhookSubscription(models.Model):
    class EventType(models.TextChoices):
        PLATE_READ = "plate.read", "Plate read"
        PLATE_ERROR = "plate.error", "Plate error"
        ACCESS_EVENT = "access.event", "Access event"
        TASK_DEAD_LETTER = "task.dead_letter", "Task dead letter"

    url = models.URLField(max_length=1000)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="webhook_subscriptions",
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    secret_encrypted = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["event_type", "url"]
        indexes = [
            models.Index(fields=["event_type", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} -> {self.url}"

    def set_secret(self, raw_secret: str) -> None:
        self.secret_encrypted = encrypt_text(raw_secret)

    def get_secret(self) -> str:
        return decrypt_text(self.secret_encrypted)


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    subscription = models.ForeignKey(
        WebhookSubscription,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="webhook_deliveries",
    )
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    response_status_code = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} ({self.status})"


class AIModelArtifact(models.Model):
    class Kind(models.TextChoices):
        YOLO = "yolo", "YOLO"
        OCR = "ocr", "OCR"

    kind = models.CharField(max_length=32, choices=Kind.choices)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ai_model_artifacts",
    )
    version = models.CharField(max_length=120)
    storage_uri = models.CharField(max_length=1000)
    file_sha256 = models.CharField(max_length=80, blank=True)
    baseline_metrics = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=False)
    promoted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "kind", "version"],
                name="unique_ai_model_version",
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.version}"


class DataProcessingRecord(models.Model):
    name = models.CharField(max_length=160)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="data_processing_records",
    )
    purpose = models.TextField()
    legal_basis = models.CharField(max_length=255)
    data_categories = models.JSONField(default=list, blank=True)
    retention_days = models.PositiveIntegerField(default=90)
    third_party_sharing = models.TextField(blank=True)
    owner = models.CharField(max_length=160, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DataSubjectRequest(models.Model):
    class RequestType(models.TextChoices):
        ACCESS = "access", "Access"
        CORRECTION = "correction", "Correction"
        DELETION = "deletion", "Deletion"
        OBJECTION = "objection", "Objection"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        REJECTED = "rejected", "Rejected"

    request_type = models.CharField(max_length=32, choices=RequestType.choices)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="data_subject_requests",
    )
    requester_name = models.CharField(max_length=160)
    requester_contact = models.CharField(max_length=255)
    plate_text = models.CharField(max_length=16, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    response_notes = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.request_type} - {self.requester_name}"


class SecurityIncident(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        INVESTIGATING = "investigating", "Investigating"
        NOTIFIED = "notified", "Notified"
        CLOSED = "closed", "Closed"

    title = models.CharField(max_length=200)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="security_incidents",
    )
    description = models.TextField()
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.OPEN)
    detected_at = models.DateTimeField()
    anpd_due_at = models.DateTimeField(null=True, blank=True)
    anpd_notified_at = models.DateTimeField(null=True, blank=True)
    affected_data = models.JSONField(default=list, blank=True)
    mitigation_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-detected_at"]

    def __str__(self) -> str:
        return self.title
