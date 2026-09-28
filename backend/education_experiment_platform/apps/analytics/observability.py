import logging
import os
from typing import Any

from pymongo import MongoClient

from apps.core.models import CompensationTask, OutboxDelivery
from apps.governance.models import QuotaReservation, RuntimeAdapter
from apps.provisioning.models import ProvisioningInstance
from apps.provisioning.services import runtime_inventory_snapshot

from .metrics import RUNTIME_LOG_HEALTH, RUNTIME_LOG_QUERIES

logger = logging.getLogger("runtime.inventory")


def runtime_logs_health() -> dict[str, object]:
    """Check MongoDB without making it a dependency of business requests."""
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        RUNTIME_LOG_HEALTH.set(0)
        return {"status": "DISABLED", "replica_set": False}
    client: MongoClient[dict[str, Any]] | None = None
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=500)
        client.admin.command("ping")
        collection = client[os.getenv("MONGODB_LOG_DATABASE", "observability")][
            os.getenv("MONGODB_LOG_COLLECTION", "runtime_logs")
        ]
        collection.create_index([("created_at", -1)], name="runtime_logs_created_at_idx")
        collection.create_index(
            [("trace_id", 1), ("created_at", -1)], name="runtime_logs_trace_idx"
        )
        ttl_days = int(os.getenv("MONGODB_LOG_TTL_DAYS", "30"))
        ttl_seconds = int(os.getenv("MONGODB_LOG_TTL_SECONDS", str(ttl_days * 86400)))
        collection.create_index(
            [("created_at", 1)],
            name="runtime_logs_ttl_idx",
            expireAfterSeconds=ttl_seconds,
        )
        replica_set = bool(client.admin.command("hello").get("setName"))
        RUNTIME_LOG_HEALTH.set(1)
        return {"status": "HEALTHY", "replica_set": replica_set}
    except Exception:
        RUNTIME_LOG_HEALTH.set(0)
        return {"status": "UNAVAILABLE", "replica_set": False}
    finally:
        if client is not None:
            client.close()


def operations_summary(*, trace_id: str = "") -> dict[str, Any]:
    inventory = runtime_inventory_snapshot(trace_id=trace_id)
    return {
        "outbox": {
            status: OutboxDelivery.objects.filter(status=status).count()
            for status, _ in OutboxDelivery.Status.choices
        },
        "compensations": {
            status: CompensationTask.objects.filter(status=status).count()
            for status, _ in CompensationTask.Status.choices
        },
        "instances": {
            status: ProvisioningInstance.objects.filter(status=status).count()
            for status, _ in ProvisioningInstance.Status.choices
        },
        "reservations": {
            status: QuotaReservation.objects.filter(status=status).count()
            for status, _ in QuotaReservation.Status.choices
        },
        "runtime_adapters": {
            status: RuntimeAdapter.objects.filter(status=status).count()
            for status, _ in RuntimeAdapter.Status.choices
        },
        "runtime": inventory,
        "logs": runtime_logs_health(),
        "alerts": _alerts(inventory),
    }


def _alerts(inventory: dict[str, Any] | None = None) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    if OutboxDelivery.objects.filter(status=OutboxDelivery.Status.DEAD).exists():
        alerts.append({"severity": "P2", "code": "OUTBOX_DEAD", "message": "存在 DEAD Outbox 投递"})
    if CompensationTask.objects.filter(status=CompensationTask.Status.DEAD).exists():
        alerts.append({
            "severity": "P2",
            "code": "COMPENSATION_DEAD",
            "message": "存在 DEAD 补偿任务",
        })
    if ProvisioningInstance.objects.filter(status=ProvisioningInstance.Status.ORPHANED).exists():
        alerts.append({"severity": "P1", "code": "ORPHAN_INSTANCE", "message": "发现孤儿运行实例"})
    runtime = inventory or {}
    if runtime.get("status") == "UNAVAILABLE":
        alerts.append(
            {
                "severity": "P1",
                "code": "RUNTIME_ENGINE_UNAVAILABLE",
                "message": "运行时引擎不可用，请按 trace 查询失败任务",
            }
        )
    orphans = runtime.get("orphans", {})
    if any(
        int(orphans.get(kind, 0) or 0) > 0
        for kind in ("runtime", "judge", "volume")
    ):
        alerts.append(
            {
                "severity": "P2",
                "code": "RUNTIME_ORPHAN_RESOURCE",
                "message": "发现未对账的运行时资源",
            }
        )
    return alerts


def query_runtime_logs(
    *, limit: int = 50, trace_id: str = "", level: str = ""
) -> list[dict[str, Any]]:
    uri = os.getenv("MONGODB_URI", "")
    if not uri:
        RUNTIME_LOG_QUERIES.labels(result="DISABLED").inc()
        return []
    try:
        client: MongoClient[dict[str, Any]] = MongoClient(
            uri, serverSelectionTimeoutMS=500
        )
        collection = client[os.getenv("MONGODB_LOG_DATABASE", "observability")][
            os.getenv("MONGODB_LOG_COLLECTION", "runtime_logs")
        ]
        query: dict[str, str] = {}
        if trace_id:
            query["trace_id"] = trace_id
        if level:
            query["level"] = level
        rows = list(
            collection.find(query, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 100)))
        )
        client.close()
        RUNTIME_LOG_QUERIES.labels(result="SUCCEEDED").inc()
        return rows
    except Exception:
        RUNTIME_LOG_QUERIES.labels(result="DEGRADED").inc()
        return []
