import json
import urllib.error
import urllib.request
from contextlib import suppress

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from redis import Redis

from .services import expire_reservations, rebuild_quota_cache


def _redis_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


@shared_task(name="apps.governance.probe_object_storage")
def probe_object_storage(*, trace_id: str = "") -> dict[str, str]:
    status = "UNAVAILABLE"
    try:
        request = urllib.request.Request(settings.MINIO_HEALTH_URL, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            if response.status == 200:
                status = "HEALTHY"
    except (OSError, urllib.error.URLError):
        status = "UNAVAILABLE"
    payload = {
        "status": status,
        "checked_at": timezone.now().isoformat(),
        "trace_id": trace_id,
    }
    with suppress(Exception):
        _redis_client().set(
            "governance:health:minio",
            json.dumps(payload, sort_keys=True),
            ex=settings.GOVERNANCE_CACHE_TTL_SECONDS,
        )
    return payload


@shared_task(name="apps.governance.run_maintenance")
def run_maintenance(*, trace_id: str) -> dict[str, int | str]:
    expired = expire_reservations(trace_id=trace_id)
    cached = 0
    try:
        cached = rebuild_quota_cache()
    except Exception:
        cached = 0
    storage = probe_object_storage.run(trace_id=trace_id)
    return {"expired": expired, "cached": cached, "storage": storage["status"]}
