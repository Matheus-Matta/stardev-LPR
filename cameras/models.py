import uuid
from urllib.parse import quote

from django.db import models
from django.utils import timezone

from common.crypto import decrypt_text, encrypt_text
from common.tokens import generate_token, hash_token, verify_token


def _public_key() -> str:
    return uuid.uuid4().hex


class Gateway(models.Model):
    class Status(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"

    name = models.CharField(max_length=120)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="gateways",
    )
    gateway_key = models.CharField(max_length=64, unique=True, default=_public_key)
    token_hash = models.CharField(max_length=128, blank=True)
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.UNKNOWN)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    version = models.CharField(max_length=80, blank=True)
    pending_events = models.PositiveIntegerField(default=0)
    cameras_online = models.PositiveIntegerField(default=0)
    cameras_offline = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def rotate_token(self) -> str:
        token = generate_token()
        self.token_hash = hash_token(token)
        self.save(update_fields=["token_hash", "updated_at"])
        return token

    def verify_token(self, token: str) -> bool:
        return verify_token(token, self.token_hash)

    def mark_seen(
        self,
        *,
        version: str = "",
        pending_events: int | None = None,
        cameras_online: int | None = None,
        cameras_offline: int | None = None,
    ) -> None:
        self.status = self.Status.ONLINE
        self.last_seen_at = timezone.now()
        if version:
            self.version = version
        if pending_events is not None:
            self.pending_events = pending_events
        if cameras_online is not None:
            self.cameras_online = cameras_online
        if cameras_offline is not None:
            self.cameras_offline = cameras_offline
        self.save(
            update_fields=[
                "status",
                "last_seen_at",
                "version",
                "pending_events",
                "cameras_online",
                "cameras_offline",
                "updated_at",
            ]
        )


class Camera(models.Model):
    class ConnectionMode(models.TextChoices):
        DIRECT_RTSP = "direct_rtsp", "Direct RTSP"
        RTMP_PUSH   = "rtmp_push",   "RTMP Push"
        PUSH        = "push",        "Push"
        GATEWAY     = "gateway",     "Gateway"

    class DirectionDefault(models.TextChoices):
        ENTRY = "entry", "Entry"
        EXIT = "exit", "Exit"
        UNKNOWN = "unknown", "Unknown"

    name = models.CharField(max_length=120)
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="cameras",
    )
    camera_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    connection_mode = models.CharField(
        max_length=32,
        choices=ConnectionMode.choices,
        default=ConnectionMode.DIRECT_RTSP,
    )
    direction_default = models.CharField(
        max_length=32,
        choices=DirectionDefault.choices,
        default=DirectionDefault.UNKNOWN,
    )
    location = models.CharField(max_length=255, blank=True)
    ingest_token_hash = models.CharField(max_length=128, blank=True)
    gateway = models.ForeignKey(
        Gateway,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cameras",
    )
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(default=554)
    rtsp_path = models.CharField(max_length=500, default="/")
    username = models.CharField(max_length=120, blank=True)
    password_encrypted = models.TextField(blank=True)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.camera_key:
            self.camera_key = _public_key()
        super().save(*args, **kwargs)

    def set_password(self, raw_password: str) -> None:
        self.password_encrypted = encrypt_text(raw_password)

    def get_password(self) -> str:
        return decrypt_text(self.password_encrypted)

    def rotate_ingest_token(self) -> str:
        token = generate_token()
        self.ingest_token_hash = hash_token(token)
        self.save(update_fields=["ingest_token_hash", "updated_at"])
        return token

    def verify_ingest_token(self, token: str) -> bool:
        return verify_token(token, self.ingest_token_hash)

    def mark_seen(self) -> None:
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at", "updated_at"])

    @property
    def rtsp_url(self) -> str:
        auth = ""
        password = self.get_password()
        if self.username:
            auth = quote(self.username)
            if password:
                auth = f"{auth}:{quote(password)}"
            auth = f"{auth}@"
        path = self.rtsp_path if self.rtsp_path.startswith("/") else f"/{self.rtsp_path}"
        return f"rtsp://{auth}{self.host}:{self.port}{path}"

    @property
    def capture_rtsp_url(self) -> str:
        """URL RTSP para o worker de captura ler via MediaMTX.

        Câmeras RTMP_PUSH e GATEWAY só existem como stream dentro do MediaMTX
        (a câmera física faz push, não expõe RTSP próprio). Para DIRECT_RTSP o
        MediaMTX já fez pull e re-expõe — usar o MediaMTX evita manter duas
        conexões com a câmera física e aproveita o buffer interno do servidor.
        """
        from django.conf import settings
        return (
            f"rtsp://{settings.MEDIAMTX_HOST}"
            f":{settings.MEDIAMTX_RTSP_PORT}"
            f"/live/{self.camera_key}"
        )

    @property
    def masked_rtsp_url(self) -> str:
        path = self.rtsp_path if self.rtsp_path.startswith("/") else f"/{self.rtsp_path}"
        if not self.username:
            return f"rtsp://{self.host}:{self.port}{path}"
        return f"rtsp://{quote(self.username)}:***@{self.host}:{self.port}{path}"
