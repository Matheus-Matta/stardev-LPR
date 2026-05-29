import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.urls import reverse_lazy
from celery.schedules import crontab
from kombu import Queue

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path, overwrite: bool = True) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        if overwrite or key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


# 1. Carrega o perfil de engine (ex: envs/.env.dev.fastalpr.cpu) sem sobrescrever vars já definidas
_profile = os.environ.get("ENV_PROFILE_LPR", "")
if _profile:
    profile_path = BASE_DIR / _profile
    if not profile_path.exists():
        profile_path = BASE_DIR / "envs" / _profile
    load_env_file(profile_path, overwrite=False)

# 2. Carrega o .env principal — sempre tem prioridade sobre o perfil
load_env_file(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DEBUG", default=ENVIRONMENT == "development")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.humanize",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "config.apps.ConfigAppConfig",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "axes",
    "common",
    "cameras",
    "plates",
    "tenants",
    "dashboard",
]

UNFOLD = {
    "SITE_TITLE": "LPR Admin",
    "SITE_HEADER": "LPR Admin",
    "SITE_SUBHEADER": "Operacao e configuracao do sistema LPR/ALPR",
    "SITE_SYMBOL": "camera",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SIDEBAR": {
        "show_search": True,
        "command_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Acesso e Contas",
                "separator": True,
                "items": [
                    {
                        "title": "Usuarios",
                        "icon": "person",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                    {
                        "title": "Grupos",
                        "icon": "groups",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                    {
                        "title": "Empresas",
                        "icon": "business",
                        "link": reverse_lazy("admin:tenants_business_changelist"),
                    },
                    {
                        "title": "Tenants / Clientes",
                        "icon": "apartment",
                        "link": reverse_lazy("admin:tenants_tenant_changelist"),
                    },
                    {
                        "title": "Perfis de Usuario",
                        "icon": "admin_panel_settings",
                        "link": reverse_lazy("admin:tenants_userprofile_changelist"),
                    },
                    {
                        "title": "Acessos por Tenant",
                        "icon": "badge",
                        "link": reverse_lazy("admin:tenants_usertenantaccess_changelist"),
                    },
                ],
            },
            {
                "title": "Dispositivos",
                "separator": True,
                "items": [
                    {
                        "title": "Cameras",
                        "icon": "photo_camera",
                        "link": reverse_lazy("admin:cameras_camera_changelist"),
                    },
                    {
                        "title": "Gateways",
                        "icon": "router",
                        "link": reverse_lazy("admin:cameras_gateway_changelist"),
                    },
                ],
            },
            {
                "title": "Operacao LPR",
                "separator": True,
                "items": [
                    {
                        "title": "Eventos de Placa",
                        "icon": "image_search",
                        "link": reverse_lazy("admin:plates_plateevent_changelist"),
                    },
                    {
                        "title": "Cadastro de Placas",
                        "icon": "format_list_bulleted",
                        "link": reverse_lazy("admin:plates_plateregistry_changelist"),
                    },
                    {
                        "title": "Eventos de Acesso",
                        "icon": "login",
                        "link": reverse_lazy("admin:plates_accessevent_changelist"),
                    },
                    {
                        "title": "Presenca de Veiculos",
                        "icon": "directions_car",
                        "link": reverse_lazy("admin:plates_vehiclepresence_changelist"),
                    },
                    {
                        "title": "Alertas",
                        "icon": "notifications",
                        "link": reverse_lazy("admin:plates_alert_changelist"),
                    },
                ],
            },
            {
                "title": "Integracoes e Processamento",
                "separator": True,
                "items": [
                    {
                        "title": "Webhooks",
                        "icon": "webhook",
                        "link": reverse_lazy("admin:common_webhooksubscription_changelist"),
                    },
                    {
                        "title": "Entregas de Webhook",
                        "icon": "send",
                        "link": reverse_lazy("admin:common_webhookdelivery_changelist"),
                    },
                    {
                        "title": "Fila de Erros",
                        "icon": "sync_problem",
                        "link": reverse_lazy("admin:common_deadlettertask_changelist"),
                    },
                    {
                        "title": "Modelos de IA",
                        "icon": "model_training",
                        "link": reverse_lazy("admin:common_aimodelartifact_changelist"),
                    },
                ],
            },
            {
                "title": "Auditoria e LGPD",
                "separator": True,
                "items": [
                    {
                        "title": "Auditoria",
                        "icon": "history",
                        "link": reverse_lazy("admin:common_auditlog_changelist"),
                    },
                    {
                        "title": "ROPT / Tratamento de Dados",
                        "icon": "policy",
                        "link": reverse_lazy("admin:common_dataprocessingrecord_changelist"),
                    },
                    {
                        "title": "Solicitacoes de Titulares",
                        "icon": "assignment_ind",
                        "link": reverse_lazy("admin:common_datasubjectrequest_changelist"),
                    },
                    {
                        "title": "Incidentes de Seguranca",
                        "icon": "security",
                        "link": reverse_lazy("admin:common_securityincident_changelist"),
                    },
                ],
            },
        ],
    },
    "COLORS": {
        "primary": {
            "50": "240 249 255",
            "100": "224 242 254",
            "200": "186 230 253",
            "300": "125 211 252",
            "400": "56 189 248",
            "500": "14 165 233",
            "600": "2 132 199",
            "700": "3 105 161",
            "800": "7 89 133",
            "900": "12 74 110",
            "950": "8 47 73",
        }
    },
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tenants.middleware.TenantContextMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

USE_POSTGRES_IN_DEBUG = env_bool("USE_POSTGRES_IN_DEBUG", False)
DEFAULT_SQLITE_URL = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASE_URL = os.getenv("DATABASE_URL", "")

if DEBUG and not USE_POSTGRES_IN_DEBUG:
    DATABASES = {"default": dj_database_url.parse(DEFAULT_SQLITE_URL)}
else:
    DATABASES = {"default": dj_database_url.config(default=DEFAULT_SQLITE_URL)}

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
USE_REDIS_IN_DEBUG = env_bool("USE_REDIS_IN_DEBUG", False)
REDIS_REQUIRED = env_bool("REDIS_REQUIRED", not DEBUG or USE_REDIS_IN_DEBUG)

if DEBUG and not USE_REDIS_IN_DEBUG:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "lpr-dev-cache",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

UPLOAD_MAX_SIZE_MB = env_int("UPLOAD_MAX_SIZE_MB", 10)
UPLOAD_MAX_SIZE_BYTES = UPLOAD_MAX_SIZE_MB * 1024 * 1024
EVENT_RETENTION_DAYS = env_int("EVENT_RETENTION_DAYS", 90)
# Imagens são apagadas antes dos registros para economizar disco.
# O arquivo PNG é deletado após IMAGE_RETENTION_HOURS; o registro (plate_text, confidence…)
# permanece até EVENT_RETENTION_DAYS.
# Exemplos: 4 (liberação de porta/automação), 24 (turno), 720 (30 dias, padrão).
IMAGE_RETENTION_HOURS = env_int("IMAGE_RETENTION_HOURS", 720)
# Qualidade JPEG das imagens capturadas pelo pipeline LPR (0–100).
# 85 oferece boa qualidade com ~70–80% de redução vs PNG lossless.
CAPTURE_IMAGE_QUALITY = env_int("CAPTURE_IMAGE_QUALITY", 85)
ALERT_OCR_QUEUE_PENDING = env_int("ALERT_OCR_QUEUE_PENDING", 50)
ALERT_CPU_PERCENT = env_int("ALERT_CPU_PERCENT", 85)
ALERT_DISK_PERCENT = env_int("ALERT_DISK_PERCENT", 80)
ALERT_OCR_ERROR_RATE_PERCENT = env_int("ALERT_OCR_ERROR_RATE_PERCENT", 20)
INGEST_PUBLIC_BASE_URL = os.getenv("INGEST_PUBLIC_BASE_URL", "http://localhost:8000")
INGEST_MAX_IMAGE_SIZE_MB = env_int("INGEST_MAX_IMAGE_SIZE_MB", UPLOAD_MAX_SIZE_MB)
INGEST_MAX_IMAGE_SIZE_BYTES = INGEST_MAX_IMAGE_SIZE_MB * 1024 * 1024
INGEST_REQUIRE_CAMERA_TOKEN = env_bool("INGEST_REQUIRE_CAMERA_TOKEN", True)
INGEST_REQUIRE_GATEWAY_TOKEN = env_bool("INGEST_REQUIRE_GATEWAY_TOKEN", True)
INGEST_RATE_LIMIT_CAMERA_PER_MINUTE = env_int("INGEST_RATE_LIMIT_CAMERA_PER_MINUTE", 60)
INGEST_RATE_LIMIT_GATEWAY_PER_MINUTE = env_int("INGEST_RATE_LIMIT_GATEWAY_PER_MINUTE", 120)
EDGE_GATEWAY_HEARTBEAT_INTERVAL_SECONDS = env_int("EDGE_GATEWAY_HEARTBEAT_INTERVAL_SECONDS", 30)
EDGE_GATEWAY_LOCAL_QUEUE_ENABLED = env_bool("EDGE_GATEWAY_LOCAL_QUEUE_ENABLED", True)
EDGE_GATEWAY_LOCAL_QUEUE_MAX_EVENTS = env_int("EDGE_GATEWAY_LOCAL_QUEUE_MAX_EVENTS", 10000)
EDGE_GATEWAY_RETRY_INTERVAL_SECONDS = env_int("EDGE_GATEWAY_RETRY_INTERVAL_SECONDS", 15)
UNKNOWN_PLATE_AUTO_CREATE = env_bool("UNKNOWN_PLATE_AUTO_CREATE", True)
UNKNOWN_PLATE_MIN_CONFIDENCE = float(os.getenv("UNKNOWN_PLATE_MIN_CONFIDENCE", "0.70"))
BLACKLIST_ALERT_ENABLED = env_bool("BLACKLIST_ALERT_ENABLED", True)
UNKNOWN_ALERT_ENABLED = env_bool("UNKNOWN_ALERT_ENABLED", True)
DEFAULT_CAMERA_TIMEZONE = os.getenv("DEFAULT_CAMERA_TIMEZONE", "America/Sao_Paulo")
PLATE_NORMALIZATION_COUNTRY = os.getenv("PLATE_NORMALIZATION_COUNTRY", "BR")
DATA_UPLOAD_MAX_MEMORY_SIZE = UPLOAD_MAX_SIZE_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = UPLOAD_MAX_SIZE_BYTES

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10/minute",
        "user": "60/minute",
        "upload": f"{env_int('UPLOAD_RATE_LIMIT_PER_HOUR', 60)}/hour",
        "upload_burst": f"{env_int('UPLOAD_RATE_LIMIT_PER_MINUTE', 20)}/minute",
        "camera_ingest": f"{INGEST_RATE_LIMIT_CAMERA_PER_MINUTE}/minute",
        "gateway_ingest": f"{INGEST_RATE_LIMIT_GATEWAY_PER_MINUTE}/minute",
    },
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env_int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", 15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

AXES_FAILURE_LIMIT = env_int("AXES_FAILURE_LIMIT", 5)
AXES_COOLOFF_TIME = 1

CELERY_DEV_EAGER = (
    DEBUG
    and not USE_REDIS_IN_DEBUG
    and env_bool("CELERY_DEV_EAGER", True)
)
CELERY_BROKER_URL = "memory://" if CELERY_DEV_EAGER else REDIS_URL
CELERY_RESULT_BACKEND = "cache+memory://" if CELERY_DEV_EAGER else REDIS_URL
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", CELERY_DEV_EAGER)
CELERY_TASK_EAGER_PROPAGATES = env_bool("CELERY_TASK_EAGER_PROPAGATES", DEBUG)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_OCR_MAX_RETRIES = env_int("CELERY_OCR_MAX_RETRIES", 3)
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_QUEUES = (
    Queue("default"),
    Queue("ocr"),
    Queue("capture"),
    Queue("reports"),
    Queue("dead"),
)
CELERY_TASK_ROUTES = {
    "cameras.tasks.capture_camera_frame": {"queue": "capture"},
    "common.tasks.dispatch_webhooks": {"queue": "reports"},
    "common.tasks.deliver_webhook": {"queue": "reports"},
    "plates.tasks.process_plate_event": {"queue": "ocr"},
    "plates.tasks.notify_dead_letter": {"queue": "dead"},
    "plates.tasks.reprocess_plate_event": {"queue": "ocr"},
    "plates.tasks.purge_plate_images": {"queue": "default"},
    "plates.tasks.purge_old_plate_events": {"queue": "default"},
}

CELERY_BEAT_SCHEDULE = {
    # Apaga arquivos PNG a cada hora — garante que retenções curtas (ex: 4h) funcionem.
    "purge-plate-images-hourly": {
        "task": "plates.tasks.purge_plate_images",
        "schedule": crontab(minute=0),
    },
    # Apaga registros antigos (e qualquer imagem restante) semanalmente.
    "purge-old-plate-events-weekly": {
        "task": "plates.tasks.purge_old_plate_events",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),
    },
}

TASK_TIME_LIMIT_OCR = env_int("TASK_TIME_LIMIT_OCR", 120)
TASK_SOFT_TIME_LIMIT_OCR = env_int("TASK_SOFT_TIME_LIMIT_OCR", 90)
RTSP_CONNECTION_TIMEOUT = env_int("RTSP_CONNECTION_TIMEOUT", 10)
RTSP_READ_TIMEOUT = env_int("RTSP_READ_TIMEOUT", 30)

MEDIAMTX_HOST = os.getenv("MEDIAMTX_HOST", "localhost")
MEDIAMTX_RTSP_PORT = env_int("MEDIAMTX_RTSP_PORT", 8554)
MEDIAMTX_HLS_PORT = env_int("MEDIAMTX_HLS_PORT", 8888)
MEDIAMTX_API_PORT = env_int("MEDIAMTX_API_PORT", 9997)

# URLs públicas via túnel (ngrok ou similar).
# Quando definidas, substituem host:porta locais no player e nas instruções de câmera.
# Exemplos:
#   MEDIAMTX_HLS_PUBLIC_URL=https://xxxx.ngrok-free.app
#   MEDIAMTX_RTMP_PUBLIC_URL=rtmp://0.tcp.sa.ngrok.io:12345
#   MEDIAMTX_RTSP_PUBLIC_URL=rtsp://0.tcp.sa.ngrok.io:12346
MEDIAMTX_HLS_PUBLIC_URL    = os.getenv("MEDIAMTX_HLS_PUBLIC_URL", "").rstrip("/")
MEDIAMTX_RTMP_PUBLIC_URL   = os.getenv("MEDIAMTX_RTMP_PUBLIC_URL", "").rstrip("/")
MEDIAMTX_RTSP_PUBLIC_URL   = os.getenv("MEDIAMTX_RTSP_PUBLIC_URL", "").rstrip("/")

CAPTURE_INTERVAL_SECONDS = env_int("CAPTURE_INTERVAL_SECONDS", 2)

YOLO_MODEL_VERSION = os.getenv("YOLO_MODEL_VERSION", "lpr-v1.pt")
OCR_ENGINE_VERSION = os.getenv("OCR_ENGINE_VERSION", "stub-0.1")

# ── LPR Engine ────────────────────────────────────────────────────────────────
# Seleciona a engine de leitura de placas.
#   mock       — simulado, apenas DEV (bloqueado em APP_ENV=prod)
#   fast_alpr  — ONNX Runtime CPU/GPU (padrão)
#   deepstream — NVIDIA DeepStream (Sprint 5)
APP_ENV     = os.getenv("APP_ENV", ENVIRONMENT)   # dev | staging | prod
LPR_ENGINE  = os.getenv("LPR_ENGINE", "fast_alpr")
LPR_MODE    = os.getenv("LPR_MODE", "real")        # real | mock
LPR_DEVICE  = os.getenv("LPR_DEVICE", "cpu")       # cpu | gpu
LPR_ALLOW_FALLBACK = env_bool("LPR_ALLOW_FALLBACK", True)
DEAD_LETTER_WEBHOOK_URL = os.getenv("DEAD_LETTER_WEBHOOK_URL", "")
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY", SECRET_KEY)

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "mask_secrets": {
            "()": "common.logging.SecretMaskingFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["mask_secrets"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "cameras": {
            "level": os.getenv("LPR_DEBUG_LOG_LEVEL", "INFO"),
            "propagate": True,
        },
        "common": {
            "level": os.getenv("LPR_DEBUG_LOG_LEVEL", "INFO"),
            "propagate": True,
        },
        "plates": {
            "level": os.getenv("LPR_DEBUG_LOG_LEVEL", "INFO"),
            "propagate": True,
        },
    },
}

SENSITIVE_ENV_VARS = [
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_URL",
    "FIELD_ENCRYPTION_KEY",
    "DEAD_LETTER_WEBHOOK_URL",
]
