"""Explicit HTTP-only configuration for the company intranet validation stage."""
from .base import bool_env
from .prod import *  # noqa: F403

# HTTPS needs a separate reviewed configuration with company DNS and certificates.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Keep file scanning available without giving that worker access to Docker.
_runtime_approved = bool_env('P02_RUNTIME_APPROVED')
_precheck_queue = 'q_provision' if _runtime_approved else 'q_content'
CELERY_TASK_ROUTES = {
    'apps.labtemplates.tasks.run_template_precheck': {'queue': _precheck_queue},
    'apps.labtemplates.tasks.scan_template_asset': {'queue': 'q_scan'},
    'apps.reports.tasks.scan_report_asset': {'queue': 'q_scan'},
    **CELERY_TASK_ROUTES,  # noqa: F405
}
CELERY_TASK_ANNOTATIONS = {
    name: {'queue': route['queue']}
    for name, route in CELERY_TASK_ROUTES.items()
    if name in {
        'apps.labtemplates.tasks.run_template_precheck',
        'apps.labtemplates.tasks.scan_template_asset',
        'apps.reports.tasks.scan_report_asset',
    }
}
if not _runtime_approved:
    CELERY_BEAT_SCHEDULE = {  # noqa: F405
        key: value for key, value in CELERY_BEAT_SCHEDULE.items()  # noqa: F405
        if key not in {'cleanup-assessment-resources', 'dispatch-assessments'}
    }
