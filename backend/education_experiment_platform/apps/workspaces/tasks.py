from typing import Any

from celery import shared_task

from apps.core.assets import record_purge_result
from apps.core.audit import append_failure
from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage

from .models import WorkspaceSnapshot
from .services import execute_execution_run, expire_sessions
from .storage import execute_storage_job, reconcile_storage_jobs


@shared_task(
    bind=True,
    acks_late=True,
    queue="q_default",
    name="apps.workspaces.expire_workspace_sessions",
)
def expire_workspace_sessions(_task: Any, *, trace_id: str = "") -> int:
    """Expire ticket rows by id; the worker never receives a token or payload."""
    return expire_sessions(trace_id=trace_id)


@shared_task(
    bind=True,
    acks_late=True,
    queue="q_provision",
    name="apps.workspaces.execute_workspace_execution_run",
)
def execute_workspace_execution_run(
    _task: Any, *, execution_run_id: str, trace_id: str = ""
) -> str:
    """Execute a queued RUN_CHECK using only the persisted run identifier."""

    run = execute_execution_run(execution_run_id=execution_run_id, trace_id=trace_id)
    return run.public_id


@shared_task(
    bind=True,
    acks_late=True,
    queue="q_workspace_storage",
    name="apps.workspaces.execute_workspace_storage_job",
)
def execute_workspace_storage_job(
    _task: Any, *, storage_job_id: str, trace_id: str = ""
) -> str:
    """Process one persisted storage job without browser-provided runtime data."""

    return execute_storage_job(storage_job_id=storage_job_id, trace_id=trace_id)


@shared_task(
    bind=True,
    acks_late=True,
    queue="q_default",
    name="apps.workspaces.reconcile_workspace_storage_jobs",
)
def reconcile_workspace_storage_jobs(_task: Any) -> int:
    """Redispatch durable storage jobs that did not reach a worker or lost one."""

    return reconcile_storage_jobs()


@shared_task(
    bind=True,
    acks_late=True,
    queue="q_default",
    name="apps.workspaces.check_workspace_objects",
)
def check_workspace_objects(
    _task: Any, *, snapshot_ids: list[str] | None = None, trace_id: str = ""
) -> int:
    """Check that referenced immutable MinIO versions still exist."""
    queryset = WorkspaceSnapshot.objects.select_related("asset")
    if snapshot_ids:
        queryset = queryset.filter(public_id__in=snapshot_ids)
    checked = 0
    storage = object_storage()
    for snapshot in queryset.iterator():
        try:
            stored = storage.head_object(
                bucket=snapshot.asset.bucket,
                object_key=snapshot.asset.object_key,
                version_id=snapshot.asset.object_version,
            )
            if stored.content_length != snapshot.size_bytes:
                raise ValueError("WORKSPACE_OBJECT_SIZE_MISMATCH")
        except Exception as exc:  # noqa: BLE001 - consistency checks must continue per object
            append_failure(
                failure_type="WORKSPACE_OBJECT_CONSISTENCY",
                subject_type="WORKSPACE_SNAPSHOT",
                subject_ref=snapshot.public_id,
                error_code="WORKSPACE_OBJECT_MISSING",
                message=str(exc),
                detail={"asset_id": snapshot.asset.public_id},
                retryable=True,
                trace_id=trace_id,
            )
        checked += 1
    return checked


@shared_task(
    bind=True,
    acks_late=True,
    queue="q_default",
    name="apps.workspaces.process_workspace_orphans",
)
def process_workspace_orphans(
    _task: Any, *, asset_ids: list[str] | None = None, trace_id: str = ""
) -> int:
    """Delete unreferenced workspace objects and append a purge fact."""
    queryset = ObjectAsset.objects.filter(
        owner_type="WORKSPACE_TASK",
        purpose="WORKSPACE_SNAPSHOT",
        workspace_snapshots__isnull=True,
    )
    if asset_ids:
        queryset = queryset.filter(public_id__in=asset_ids)
    processed = 0
    storage = object_storage()
    for asset in queryset.iterator():
        try:
            storage.delete_object(
                bucket=asset.bucket,
                object_key=asset.object_key,
                version_id=asset.object_version,
            )
            record_purge_result(
                asset_id=asset.pk,
                expected_version=asset.row_version,
                result="PURGED",
                trace_id=trace_id,
                reason="workspace orphan asset",
            )
        except Exception as exc:  # noqa: BLE001 - one orphan must not block the sweep
            append_failure(
                failure_type="WORKSPACE_ORPHAN",
                subject_type="OBJECT_ASSET",
                subject_ref=asset.public_id,
                error_code="WORKSPACE_ORPHAN_PURGE_FAILED",
                message=str(exc),
                detail={},
                retryable=True,
                trace_id=trace_id,
            )
        processed += 1
    return processed
