import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    file_path = os.getenv(f"{name}_FILE")
    value: str | None
    if file_path:
        value = Path(file_path).read_text(encoding="utf-8").strip()
    else:
        value = os.getenv(name)
        if value is None:
            value = default
    if required and not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value or ""


def csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "unsafe-local-only-key-change-before-deploy")
DEBUG = False
ALLOWED_HOSTS = csv_env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,django")
CSRF_TRUSTED_ORIGINS = csv_env("DJANGO_TRUSTED_ORIGINS")

APP_VERSION = env("APP_VERSION", "0.9.0-p09")
OPENAPI_REVISION = env("OPENAPI_REVISION", "v2-p09")
GIT_REVISION = env("GIT_REVISION", "development")
BUILD_TIME = env("BUILD_TIME", "development")
TRUSTED_PROXY_CIDRS = csv_env(
    "TRUSTED_PROXY_CIDRS",
    "127.0.0.0/8",
)

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.courses.apps.CoursesConfig",
    "apps.governance.apps.GovernanceConfig",
    "apps.labtemplates.apps.LabTemplatesConfig",
    "apps.experiments.apps.ExperimentsConfig",
    "apps.provisioning.apps.ProvisioningConfig",
    "apps.workspaces.apps.WorkspacesConfig",
    "apps.reports.apps.ReportsConfig",
    "apps.reviews.apps.ReviewsConfig",
    "apps.archives.apps.ArchivesConfig",
    "apps.agents.apps.AgentsConfig",
    "apps.notifications.apps.NotificationsConfig",
    "apps.analytics.apps.AnalyticsConfig",
    "apps.integrations.apps.IntegrationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "education_experiment_platform.middleware.TraceContextMiddleware",
    "education_experiment_platform.middleware.PortalContextMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "education_experiment_platform.middleware.FilePortalContextMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "education_experiment_platform.middleware.IdempotencyKeyMiddleware",
]

ROOT_URLCONF = "education_experiment_platform.urls"
ASGI_APPLICATION = "education_experiment_platform.asgi.application"
WSGI_APPLICATION = "education_experiment_platform.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("MYSQL_DATABASE", "edu_platform"),
        "USER": env("MYSQL_USER", "edu_platform"),
        "PASSWORD": env("MYSQL_PASSWORD", ""),
        "HOST": env("MYSQL_HOST", "mysql"),
        "PORT": env("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK: dict[str, object] = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "education_experiment_platform.api.exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.PortalSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS: dict[str, object] = {
    "TITLE": "Education Agent Platform API",
    "DESCRIPTION": (
        "P09 reports, scanned attachments, immutable submissions, and system artifacts."
    ),
    "VERSION": OPENAPI_REVISION,
    "SERVE_INCLUDE_SCHEMA": False,
    "OAS_VERSION": "3.0.3",
}

REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")
OUTBOX_REDIS_STREAM = env("OUTBOX_REDIS_STREAM", "edu:events:v2")
OUTBOX_REDIS_MAXLEN = int(env("OUTBOX_REDIS_MAXLEN", "10000"))
AUDIT_IP_HASH_SALT = env("AUDIT_IP_HASH_SALT", SECRET_KEY)
IDENTITY_HMAC_KEY = env("IDENTITY_HMAC_KEY", SECRET_KEY)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(env("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
LOGIN_RATE_LIMIT_ATTEMPTS = int(env("LOGIN_RATE_LIMIT_ATTEMPTS", "8"))
USER_SESSION_IDLE_SECONDS = int(env("USER_SESSION_IDLE_SECONDS", "43200"))
TEACHING_SESSION_IDLE_SECONDS = int(env("TEACHING_SESSION_IDLE_SECONDS", "28800"))
PLATFORM_SESSION_IDLE_SECONDS = int(env("PLATFORM_SESSION_IDLE_SECONDS", "3600"))
USER_SESSION_ABSOLUTE_SECONDS = int(env("USER_SESSION_ABSOLUTE_SECONDS", "604800"))
TEACHING_SESSION_ABSOLUTE_SECONDS = int(env("TEACHING_SESSION_ABSOLUTE_SECONDS", "86400"))
PLATFORM_SESSION_ABSOLUTE_SECONDS = int(env("PLATFORM_SESSION_ABSOLUTE_SECONDS", "28800"))
PLATFORM_RECENT_AUTH_SECONDS = int(env("PLATFORM_RECENT_AUTH_SECONDS", "300"))

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://redis:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://redis:6379/2")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_DEFAULT_QUEUE = "q_default"
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_TASK_ROUTES = {
    "apps.core.relay_outbox": {"queue": "q_relay"},
    "apps.core.run_compensations": {"queue": "q_compensate"},
    "apps.provisioning.*": {"queue": "q_provision"},
    "apps.archives.*": {"queue": "q_archive"},
    "apps.agents.*": {"queue": "q_agent"},
    "apps.courses.*": {"queue": "q_content"},
    "apps.governance.*": {"queue": "q_default"},
    "apps.labtemplates.*": {"queue": "q_provision"},
    "apps.analytics.*": {"queue": "q_analytics"},
    "apps.integrations.*": {"queue": "q_integrations"},
    "apps.notifications.*": {"queue": "q_default"},
    "apps.experiments.*": {"queue": "q_default"},
    "apps.workspaces.*": {"queue": "q_default"},
    "apps.reports.*": {"queue": "q_provision"},
}
WORKSPACE_TOKEN_HMAC_KEY = env("WORKSPACE_TOKEN_HMAC_KEY", SECRET_KEY)
WORKSPACE_SESSION_TTL_SECONDS = int(env("WORKSPACE_SESSION_TTL_SECONDS", "900"))
WORKSPACE_SNAPSHOT_MAX_BYTES = int(env("WORKSPACE_SNAPSHOT_MAX_BYTES", str(20 * 1024 * 1024)))
WORKSPACE_SNAPSHOT_ALLOWED_MIME_TYPES = set(
    csv_env(
        "WORKSPACE_SNAPSHOT_ALLOWED_MIME_TYPES",
        "text/plain,application/json,application/octet-stream,application/zip",
    )
)
SSE_HEARTBEAT_SECONDS = int(env("SSE_HEARTBEAT_SECONDS", "20"))
P06_PUBLICATION_SYNC_LIMIT = int(env("P06_PUBLICATION_SYNC_LIMIT", "100"))
P06_PUBLICATION_CHUNK_SIZE = int(env("P06_PUBLICATION_CHUNK_SIZE", "50"))
COURSE_INVITATION_HMAC_KEY = env("COURSE_INVITATION_HMAC_KEY", SECRET_KEY)
GOVERNANCE_CACHE_TTL_SECONDS = int(env("GOVERNANCE_CACHE_TTL_SECONDS", "300"))
GOVERNANCE_HEALTH_STALE_SECONDS = int(env("GOVERNANCE_HEALTH_STALE_SECONDS", "300"))
MINIO_HEALTH_URL = env("MINIO_HEALTH_URL", "http://minio:9000/minio/health/ready")
MINIO_INTERNAL_ENDPOINT = env("MINIO_INTERNAL_ENDPOINT", env("MINIO_ENDPOINT", "http://minio:9000"))
MINIO_PUBLIC_ENDPOINT = env("MINIO_PUBLIC_ENDPOINT", "http://127.0.0.1:9000")
MINIO_BUCKET = env("MINIO_BUCKET", "edu-platform")
MINIO_APP_ACCESS_KEY = env("MINIO_APP_ACCESS_KEY", "edu-platform-app")
MINIO_APP_SECRET_KEY = env("MINIO_APP_SECRET_KEY", "local-minio-app-password")
MINIO_REGION = env("MINIO_REGION", "us-east-1")
CLAMAV_HOST = env("CLAMAV_HOST", "clamav")
CLAMAV_PORT = int(env("CLAMAV_PORT", "3310"))
CLAMAV_TIMEOUT_SECONDS = int(env("CLAMAV_TIMEOUT_SECONDS", "30"))
TEMPLATE_ASSET_MAX_BYTES = int(env("TEMPLATE_ASSET_MAX_BYTES", str(20 * 1024 * 1024)))
TEMPLATE_UPLOAD_EXPIRES_SECONDS = int(env("TEMPLATE_UPLOAD_EXPIRES_SECONDS", "900"))
TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS = int(env("TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS", "300"))
REPORT_ATTACHMENT_MAX_BYTES = int(env("REPORT_ATTACHMENT_MAX_BYTES", str(20 * 1024 * 1024)))
REPORT_UPLOAD_EXPIRES_SECONDS = int(env("REPORT_UPLOAD_EXPIRES_SECONDS", "900"))
FILE_DOWNLOAD_GRANT_TTL_SECONDS = int(env("FILE_DOWNLOAD_GRANT_TTL_SECONDS", "300"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "education_experiment_platform.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_NAME = "sessionid"
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_DOMAIN = None

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]
