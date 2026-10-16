import json
import os
import re
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


def bool_env(name: str, default: bool = False) -> bool:
    return env(name, "true" if default else "false").casefold() in {"1", "true", "yes", "on"}


def json_env(name: str, default: str = "{}") -> dict[str, object]:
    value = json.loads(env(name, default))
    if not isinstance(value, dict):
        raise RuntimeError(f"Environment variable must contain a JSON object: {name}")
    return value


SECRET_KEY = env("DJANGO_SECRET_KEY", "unsafe-local-only-key-change-before-deploy")
DEBUG = False
ALLOWED_HOSTS = csv_env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,django")
CSRF_TRUSTED_ORIGINS = csv_env("DJANGO_TRUSTED_ORIGINS")

APP_VERSION = env("APP_VERSION", "0.15.0-p15")
OPENAPI_REVISION = env("OPENAPI_REVISION", "v2-p15")
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
    "DESCRIPTION": "P15 student experiment workbench and platform operations.",
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
    "apps.workspaces.execute_workspace_storage_job": {"queue": "q_workspace_storage"},
    "apps.workspaces.execute_workspace_execution_run": {"queue": "q_provision"},
    "apps.workspaces.reconcile_workspace_storage_jobs": {"queue": "q_default"},
    "apps.workspaces.*": {"queue": "q_default"},
    "apps.reports.*": {"queue": "q_provision"},
    "apps.reviews.run_auto_check": {"queue": "q_provision"},
    "apps.reviews.run_similarity_check": {"queue": "q_analytics"},
    "apps.reviews.purge_similarity_evidence": {"queue": "q_default"},
}
CELERY_BEAT_SCHEDULE = {
    "p11-scan-task-deadlines": {
        "task": "apps.archives.scan_due_tasks",
        "schedule": 60.0,
    },
    "p11-reconcile-archives-and-runtime": {
        "task": "apps.archives.reconcile",
        "schedule": 60.0,
    },
    "p11-run-compensations": {
        "task": "apps.core.run_compensations",
        "schedule": 30.0,
    },
    "p14-purge-archive-retention": {
        "task": "apps.archives.purge_retention",
        "schedule": 3600.0,
    },
    "p16-reconcile-workspace-storage": {
        "task": "apps.workspaces.reconcile_workspace_storage_jobs",
        "schedule": 30.0,
    },
    "p13-refresh-analytics": {
        "task": "apps.analytics.refresh_projection",
        "schedule": 300.0,
    },
    "p13-consume-notifications": {
        "task": "apps.notifications.consume_outbox",
        "schedule": 30.0,
    },
    "p13-deliver-webhooks": {
        "task": "apps.integrations.deliver_due_webhooks",
        "schedule": 15.0,
    },
    "p14-probe-runtime-adapters": {
        "task": "apps.governance.probe_runtime_adapters",
        "schedule": 30.0,
    },
}
SIMILARITY_ALGORITHM_VERSION = env(
    "SIMILARITY_ALGORITHM_VERSION", "char-5gram-jaccard-v1"
)
SIMILARITY_THRESHOLD = env("SIMILARITY_THRESHOLD", "0.30")
SIMILARITY_RETENTION_DAYS = int(env("SIMILARITY_RETENTION_DAYS", "180"))
P10_AUTO_CHECK_MAX_ATTEMPTS = int(env("P10_AUTO_CHECK_MAX_ATTEMPTS", "3"))
WORKSPACE_TOKEN_HMAC_KEY = env("WORKSPACE_TOKEN_HMAC_KEY", SECRET_KEY)
WORKSPACE_SESSION_TTL_SECONDS = int(env("WORKSPACE_SESSION_TTL_SECONDS", "900"))
WORKSPACE_COOKIE_NAME = env("WORKSPACE_COOKIE_NAME", "workspace_ticket")
WORKSPACE_ALLOWED_ORIGINS = csv_env("WORKSPACE_ALLOWED_ORIGINS", ",".join(CSRF_TRUSTED_ORIGINS))
WORKSPACE_UPSTREAM_TIMEOUT_SECONDS = int(env("WORKSPACE_UPSTREAM_TIMEOUT_SECONDS", "60"))
WORKSPACE_INTERNAL_KEY = env("WORKSPACE_INTERNAL_KEY", SECRET_KEY)
WORKSPACE_UPSTREAM_HMAC_KEY = env("WORKSPACE_UPSTREAM_HMAC_KEY", SECRET_KEY)
WORKSPACE_AUTHORITY_URL = env("WORKSPACE_AUTHORITY_URL", "http://django:8000")
WORKSPACE_SNAPSHOT_MAX_BYTES = int(env("WORKSPACE_SNAPSHOT_MAX_BYTES", str(20 * 1024 * 1024)))
WORKSPACE_STORAGE_STALE_AFTER_SECONDS = max(
    60, int(env("WORKSPACE_STORAGE_STALE_AFTER_SECONDS", "900"))
)
WORKSPACE_STORAGE_REDISPATCH_SECONDS = max(
    30, int(env("WORKSPACE_STORAGE_REDISPATCH_SECONDS", "300"))
)
WORKSPACE_FINALIZE_TIMEOUT_SECONDS = max(
    1, int(env("WORKSPACE_FINALIZE_TIMEOUT_SECONDS", "1200"))
)
WORKSPACE_VOLUME_RETENTION_SECONDS = max(
    60, int(env("WORKSPACE_VOLUME_RETENTION_SECONDS", "900"))
)
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
ARCHIVE_RETENTION_DAYS = int(env("ARCHIVE_RETENTION_DAYS", "365"))
ARCHIVE_SAFE_RECYCLE_SECONDS = int(env("ARCHIVE_SAFE_RECYCLE_SECONDS", "900"))
ARCHIVE_EXPORT_TTL_SECONDS = int(env("ARCHIVE_EXPORT_TTL_SECONDS", "300"))
ARCHIVE_MAX_ATTEMPTS = int(env("ARCHIVE_MAX_ATTEMPTS", "5"))
RUNTIME_EXECUTION_RETENTION_DAYS = int(env("RUNTIME_EXECUTION_RETENTION_DAYS", "30"))
RUNTIME_CLEANUP_MAX_ATTEMPTS = int(env("RUNTIME_CLEANUP_MAX_ATTEMPTS", "10"))
RUNTIME_ADAPTER_CONFIGS = json_env("RUNTIME_ADAPTER_CONFIGS")
RUNTIME_MODE = env("RUNTIME_MODE", "local").strip().lower()
if RUNTIME_MODE not in {"fake", "local", "swarm"}:
    raise RuntimeError("RUNTIME_MODE must be fake, local, or swarm")
RUNTIME_ADAPTER_CODE = env("RUNTIME_ADAPTER_CODE", "runtime/local-docker")
LOCAL_RUNTIME_IMAGE = env("LOCAL_RUNTIME_IMAGE", "edu-platform-algorithm-workspace:local")
LOCAL_RUNTIME_NETWORK = env("LOCAL_RUNTIME_NETWORK", "edu-platform-p14_runtime")
LOCAL_DOCKER_HOST = env("LOCAL_DOCKER_HOST", "unix:///var/run/docker.sock")
LOCAL_RUNTIME_MODE = env("LOCAL_RUNTIME_MODE", "REAL").upper()
if LOCAL_RUNTIME_MODE not in {"STUB", "REAL"}:
    raise RuntimeError("LOCAL_RUNTIME_MODE must be STUB or REAL")
if not LOCAL_RUNTIME_IMAGE.strip() or any(char.isspace() for char in LOCAL_RUNTIME_IMAGE):
    raise RuntimeError("LOCAL_RUNTIME_IMAGE must be a non-empty image reference")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", LOCAL_RUNTIME_NETWORK):
    raise RuntimeError("LOCAL_RUNTIME_NETWORK must be a Docker network name")
if not LOCAL_DOCKER_HOST.startswith(("unix://", "npipe://")):
    raise RuntimeError("LOCAL_DOCKER_HOST must reference a local Docker Engine socket")
SWARM_DOCKER_HOST = env("SWARM_DOCKER_HOST", "unix:///var/run/docker.sock")
SWARM_DOCKER_API_VERSION = env("SWARM_DOCKER_API_VERSION", "auto")
SWARM_DOCKER_TLS_VERIFY = bool_env("SWARM_DOCKER_TLS_VERIFY")
SWARM_DOCKER_CA_PATH = env("SWARM_DOCKER_CA_PATH", "/run/secrets/swarm_docker_ca")
SWARM_DOCKER_CERT_PATH = env("SWARM_DOCKER_CERT_PATH", "/run/secrets/swarm_docker_cert")
SWARM_DOCKER_KEY_PATH = env("SWARM_DOCKER_KEY_PATH", "/run/secrets/swarm_docker_key")
SWARM_REQUEST_TIMEOUT_SECONDS = int(env("SWARM_REQUEST_TIMEOUT_SECONDS", "30"))
SWARM_BOOT_TIMEOUT_SECONDS = int(env("SWARM_BOOT_TIMEOUT_SECONDS", "120"))
SWARM_POLL_INTERVAL_SECONDS = float(env("SWARM_POLL_INTERVAL_SECONDS", "2"))
SWARM_RUNTIME_NETWORK = env("SWARM_RUNTIME_NETWORK", "edu-runtime")
if os.getenv("DJANGO_SETTINGS_MODULE", "").endswith(".prod"):
    if RUNTIME_MODE != "swarm" or not RUNTIME_ADAPTER_CODE.strip():
        raise RuntimeError("Production requires RUNTIME_MODE=swarm and RUNTIME_ADAPTER_CODE")
    if RUNTIME_ADAPTER_CODE not in RUNTIME_ADAPTER_CONFIGS:
        raise RuntimeError("Production runtime adapter configuration is missing")
RUNTIME_DEFAULT_TTL_SECONDS = int(env("RUNTIME_DEFAULT_TTL_SECONDS", "14400"))
RUNTIME_WORKSPACE_PORT = int(env("RUNTIME_WORKSPACE_PORT", "8080"))
RUNTIME_HEALTHCHECK_PATH = env("RUNTIME_HEALTHCHECK_PATH", "/healthz")
AGENT_DEFAULT_MAX_TOKENS = int(env("AGENT_DEFAULT_MAX_TOKENS", "2048"))
AGENT_DEFAULT_DAILY_TOKENS = int(env("AGENT_DEFAULT_DAILY_TOKENS", "100000"))
AGENT_DEFAULT_REQUESTS_PER_MINUTE = int(env("AGENT_DEFAULT_REQUESTS_PER_MINUTE", "30"))
AGENT_RETRIEVAL_LIMIT = int(env("AGENT_RETRIEVAL_LIMIT", "5"))
AGENT_TOOL_APPROVAL_TTL_SECONDS = int(env("AGENT_TOOL_APPROVAL_TTL_SECONDS", "300"))
AGENT_SOURCE_MAX_BYTES = int(env("AGENT_SOURCE_MAX_BYTES", str(2 * 1024 * 1024)))
AGENT_SOURCE_UPLOAD_EXPIRES_SECONDS = int(env("AGENT_SOURCE_UPLOAD_EXPIRES_SECONDS", "300"))

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
