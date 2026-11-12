import hashlib
import json
import tempfile
import zipfile
from contextlib import suppress
from datetime import timedelta
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.assets import record_purge_result, register_asset, set_scan_result
from apps.core.audit import append_audit, append_failure
from apps.core.compensation import create_compensation
from apps.core.concurrency import compare_and_swap
from apps.core.downloads import create_download_grant
from apps.core.errors import DownloadScopeDenied, ResourceNotFound, RowVersionConflict
from apps.core.models import CompensationTask, FileDownloadGrant, ObjectAsset, ObjectPurgeLog
from apps.core.object_storage import iter_chunks, object_storage
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.ports import Blocker
from apps.courses.selectors import require_course_capability
from apps.experiments.models import ExperimentTask
from apps.experiments.services import transition_task

from . import events
from .errors import ArchiveStateConflict, ArchiveVerificationFailed
from .metrics import (
    ARCHIVE_DURATION_SECONDS,
    ARCHIVE_EXPORTS_TOTAL,
    ARCHIVE_JOBS_TOTAL,
    ARCHIVE_RETENTION_TOTAL,
)
from .models import ArchiveExportGrant, ArchiveJob, ArchiveManifest, ArchiveVerification

TERMINAL_STATUSES = {
    ExperimentTask.Status.COMPLETED,
    ExperimentTask.Status.CANCELLED,
    ExperimentTask.Status.EXPIRED,
}


def _trace(context: Any) -> str:
    return str(getattr(context, "trace_id", ""))


def worker_context(*, trace_id: str, actor_ref: str = "archive-worker") -> Any:
    return SimpleNamespace(
        actor_ref=actor_ref,
        portal="WORKER",
        trace_id=trace_id,
        client_ip="",
        user_agent="",
    )


def _audit(
    *,
    context: Any,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    actor: User | None = None,
    before: Any = None,
    after: Any = None,
    result: str = "SUCCEEDED",
    error_code: str = "",
) -> None:
    append_audit(
        actor_ref=actor.public_id if actor else str(getattr(context, "actor_ref", "worker")),
        actor_portal=str(getattr(context, "portal", "WORKER")),
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
        before=before,
        after=after,
        result=result,
        error_code=error_code,
        trace_id=_trace(context),
    )


def _emit(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
    context: Any,
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=payload,
        trace_id=_trace(context),
    )
    enqueue_relay_after_commit(trace_id=_trace(context))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        cls=DjangoJSONEncoder,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archive_retention_until() -> Any:
    days = max(1, int(getattr(settings, "ARCHIVE_RETENTION_DAYS", 365)))
    return timezone.now() + timedelta(days=days)


def _max_attempts() -> int:
    return max(1, int(getattr(settings, "ARCHIVE_MAX_ATTEMPTS", 5)))


def _set_terminal_target(task: ExperimentTask, target: str) -> ExperimentTask:
    if target not in ExperimentTask.TerminalTarget.values:
        raise ArchiveStateConflict(detail={"terminal_target": target})
    if task.terminal_target and task.terminal_target != target:
        raise ArchiveStateConflict(
            detail={"terminal_target": task.terminal_target, "requested_target": target}
        )
    if task.terminal_target == target:
        return task
    return compare_and_swap(
        ExperimentTask,
        pk=task.pk,
        expected_version=task.row_version,
        changes={"terminal_target": target},
    )


@transaction.atomic
def request_task_archive(
    *, task_id: str, terminal_target: str, trigger: str, context: Any, actor: User | None = None
) -> ArchiveJob | None:
    task = (
        ExperimentTask.objects.select_for_update()
        .select_related(
            "course",
            "student",
            "publication",
            "enrollment",
        )
        .get(public_id=task_id)
    )
    if task.status in TERMINAL_STATUSES:
        return ArchiveJob.objects.filter(task=task).first()
    task = _set_terminal_target(task, terminal_target)
    if task.status != "ARCHIVING":
        task = compare_and_swap(
            ExperimentTask,
            pk=task.pk,
            expected_version=task.row_version,
            changes={"status": "ARCHIVING"},
        )
    job, _ = ArchiveJob.objects.get_or_create(
        task=task,
        defaults={
            "course": task.course,
            "terminal_target": terminal_target,
            "max_attempts": _max_attempts(),
            "trace_id": _trace(context),
        },
    )
    _audit(
        context=context,
        actor=actor,
        action="archive.request",
        target_type="archive_job",
        target_ref=job.public_id,
        course_ref=task.course.public_id,
        after={"trigger": trigger, "terminal_target": terminal_target},
    )
    from .tasks import run_archive_job

    transaction.on_commit(
        lambda: run_archive_job.apply_async(
            kwargs={"job_id": job.public_id, "trace_id": _trace(context)},
            queue="q_archive",
        )
    )
    return job


def _zip_entry(archive: zipfile.ZipFile, path: str, data: bytes) -> None:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, data)


def _copy_verified_asset(
    *, archive: zipfile.ZipFile, asset: ObjectAsset, path: str
) -> dict[str, Any]:
    if (
        asset.status != ObjectAsset.Status.ACTIVE
        or asset.scan_status != ObjectAsset.ScanStatus.CLEAN
    ):
        raise ArchiveVerificationFailed(
            detail={"asset_id": asset.public_id, "scan_status": asset.scan_status}
        )
    stored = object_storage().open_object(
        bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with archive.open(path, "w") as target:
            for chunk in iter_chunks(stored.body):
                size += len(chunk)
                digest.update(chunk)
                target.write(chunk)
    finally:
        stored.body.close()
    actual = digest.hexdigest()
    if size != asset.size_bytes or actual != asset.digest_sha256:
        raise ArchiveVerificationFailed(
            detail={
                "asset_id": asset.public_id,
                "expected_size": asset.size_bytes,
                "actual_size": size,
                "expected_digest": asset.digest_sha256,
                "actual_digest": actual,
            }
        )
    return {
        "kind": "OBJECT_ASSET",
        "path": path,
        "asset_id": asset.public_id,
        "object_version": asset.object_version,
        "digest": actual,
        "size_bytes": size,
        "scan_status": asset.scan_status,
    }


def _build_package(task: ExperimentTask) -> tuple[Any, list[dict[str, Any]], str, int]:
    from .assessment import assessment_archive

    snapshot, assets = assessment_archive(task)
    generated = {
        "task.json": _canonical_bytes({"task": snapshot["task"]}),
        "report.json": _canonical_bytes(snapshot["report"]),
        "review.json": _canonical_bytes(snapshot["review"]),
        "workspace.json": _canonical_bytes(snapshot["workspace"]),
        "system-artifacts.json": _canonical_bytes(snapshot["system_artifacts"]),
    }
    # The caller owns this handle and closes it after upload or failure.
    package = tempfile.SpooledTemporaryFile(  # noqa: SIM115
        max_size=8 * 1024 * 1024,
        mode="w+b",
    )
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(package, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in generated.items():
            _zip_entry(archive, path, data)
            entries.append({
                "kind": "GENERATED",
                "path": path,
                "digest": _digest(data),
                "size_bytes": len(data),
            })
        for asset in sorted(assets, key=lambda item: item.public_id):
            suffix = PurePosixPath(asset.original_name).suffix[:16] if asset.original_name else ""
            path = f"assets/{asset.public_id}{suffix}"
            entries.append(_copy_verified_asset(archive=archive, asset=asset, path=path))
        manifest_bytes = _canonical_bytes({"schema": "edu.archive.manifest.v1", "entries": entries})
        _zip_entry(archive, "manifest.json", manifest_bytes)
    package.seek(0)
    digest = hashlib.sha256()
    size = 0
    for chunk in iter_chunks(package):
        size += len(chunk)
        digest.update(chunk)
    package.seek(0)
    return package, entries, digest.hexdigest(), size


def _verify_stored_package(asset: ObjectAsset) -> str:
    stored = object_storage().open_object(
        bucket=asset.bucket, object_key=asset.object_key, version_id=asset.object_version
    )
    digest = hashlib.sha256()
    size = 0
    try:
        for chunk in iter_chunks(stored.body):
            size += len(chunk)
            digest.update(chunk)
    finally:
        stored.body.close()
    actual = digest.hexdigest()
    if size != asset.size_bytes or actual != asset.digest_sha256:
        raise ArchiveVerificationFailed(
            detail={"asset_id": asset.public_id, "actual_size": size, "actual_digest": actual}
        )
    return actual


def _mark_job_running(job: ArchiveJob) -> ArchiveJob:
    if job.attempt_count >= job.max_attempts:
        raise ArchiveStateConflict(detail={"attempts_exhausted": True})
    return compare_and_swap(
        ArchiveJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={
            "status": ArchiveJob.Status.RUNNING,
            "attempt_count": job.attempt_count + 1,
            "started_at": job.started_at or timezone.now(),
            "failure_record": None,
        },
    )


def _ensure_archiving(task: ExperimentTask, context: Any) -> ExperimentTask:
    if task.status == ExperimentTask.Status.FAILED:
        failure = task.current_failure or {}
        if failure.get("previous_status") != ExperimentTask.Status.ARCHIVING:
            raise ArchiveStateConflict(detail={"task_status": task.status})
        task = transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.ARCHIVING,
            actor=None,
            expected_version=task.row_version,
            trigger="ARCHIVE_RETRY",
            reason="archive compensation retry",
            context=context,
        )
    if task.status != ExperimentTask.Status.ARCHIVING:
        raise ArchiveStateConflict(detail={"task_status": task.status})
    return task


def _record_archive_failure(job: ArchiveJob, exc: Exception, context: Any) -> ArchiveJob:
    error_code = getattr(exc, "code", "ARCHIVE_JOB_FAILED")
    detail = getattr(exc, "detail", {})
    failure = append_failure(
        failure_type="ARCHIVE",
        subject_type="ARCHIVE_JOB",
        subject_ref=job.public_id,
        error_code=error_code,
        message=error_code,
        detail=detail,
        retryable=True,
        trace_id=_trace(context),
    )
    ArchiveVerification.objects.create(
        job=job,
        attempt_no=job.attempt_count,
        result=ArchiveVerification.Result.FAILED,
        checks=[{"result": "FAILED", "error_code": error_code, "detail": detail}],
        error_code=error_code,
        verified_at=timezone.now(),
        trace_id=_trace(context),
    )
    compensation = job.compensation_task
    if compensation is None or compensation.status == CompensationTask.Status.COMPLETED:
        compensation = create_compensation(
            task_type="RETRY_ARCHIVE_JOB",
            subject_type="ARCHIVE_JOB",
            subject_ref=job.public_id,
            payload={"job_id": job.public_id},
            trace_id=_trace(context),
            max_attempts=job.max_attempts,
        )
    changed = compare_and_swap(
        ArchiveJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={
            "status": ArchiveJob.Status.FAILED,
            "failure_record": failure,
            "compensation_task": compensation,
        },
    )
    task = ExperimentTask.objects.get(pk=job.task_id)
    if task.status == ExperimentTask.Status.ARCHIVING:
        transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.FAILED,
            actor=None,
            expected_version=task.row_version,
            trigger="ARCHIVE_FAILED",
            reason="archive verification failed",
            context=context,
            detail={"retryable": True, "error_code": error_code},
        )
    _audit(
        context=context,
        action="archive.verify",
        target_type="archive_job",
        target_ref=job.public_id,
        course_ref=job.course.public_id,
        after={"status": "FAILED"},
        result="FAILED",
        error_code=error_code,
    )
    _emit(
        event_type=events.ARCHIVE_FAILED,
        aggregate_type="archive_job",
        aggregate_ref=job.public_id,
        payload={"job_id": job.public_id, "task_id": task.public_id, "error_code": error_code},
        context=context,
    )
    ARCHIVE_JOBS_TOTAL.labels(result="failed", terminal_target=job.terminal_target).inc()
    return changed


@transaction.atomic
def _finish_task_cleanup(job: ArchiveJob, context: Any, *, archive_verified: bool) -> None:
    task = ExperimentTask.objects.select_for_update().get(pk=job.task_id)
    if task.status == job.terminal_target:
        return
    if not archive_verified or not ArchiveManifest.objects.filter(job=job).exists():
        raise ArchiveStateConflict(detail={"archive": "verified_manifest_required"})
    compare_and_swap(
        ExperimentTask,
        pk=task.pk,
        expected_version=task.row_version,
        changes={
            "status": job.terminal_target,
            "completed_at": timezone.now()
            if job.terminal_target == "COMPLETED"
            else task.completed_at,
        },
    )
    _audit(
        context=context,
        action="archive.finalize",
        target_type="experiment_task",
        target_ref=task.public_id,
        course_ref=task.course.public_id,
        after={"status": job.terminal_target},
    )


@transaction.atomic
def _record_cleanup_failure(job: ArchiveJob, exc: Exception, context: Any) -> None:
    error_code = getattr(exc, "code", "ARCHIVE_FINALIZE_FAILED")
    failure = append_failure(
        failure_type="ARCHIVE_FINALIZE",
        subject_type="ARCHIVE_JOB",
        subject_ref=job.public_id,
        error_code=error_code,
        message=error_code,
        detail={"task_id": job.task.public_id},
        retryable=True,
        trace_id=_trace(context),
    )
    compensation = create_compensation(
        task_type="RETRY_ARCHIVE_JOB",
        subject_type="ARCHIVE_JOB",
        subject_ref=job.public_id,
        payload={"job_id": job.public_id},
        trace_id=_trace(context),
        max_attempts=_max_attempts(),
    )
    current = ArchiveJob.objects.select_for_update().get(pk=job.pk)
    compare_and_swap(
        ArchiveJob,
        pk=current.pk,
        expected_version=current.row_version,
        changes={"failure_record": failure, "compensation_task": compensation},
    )
    task = ExperimentTask.objects.select_for_update().get(pk=job.task_id)
    if task.status == ExperimentTask.Status.ARCHIVING:
        transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.FAILED,
            actor=None,
            expected_version=task.row_version,
            trigger="TERMINAL_CLEANUP_FAILED",
            reason="verified archive cleanup failed",
            context=context,
            detail={"retryable": True, "error_code": error_code},
        )
    _audit(
        context=context,
        action="archive.cleanup",
        target_type="archive_job",
        target_ref=job.public_id,
        course_ref=job.course.public_id,
        result="FAILED",
        error_code=error_code,
    )


@ARCHIVE_DURATION_SECONDS.time()
def execute_archive_job(
    *, job_id: str, trace_id: str = "", raise_on_failure: bool = False
) -> ArchiveJob:
    context = worker_context(trace_id=trace_id)
    job = ArchiveJob.objects.select_related(
        "task__course", "task__student", "task__publication"
    ).get(public_id=job_id)
    existing_manifest = ArchiveManifest.objects.filter(job=job).first()
    if existing_manifest is not None:
        if job.status != ArchiveJob.Status.PASSED:
            job = compare_and_swap(
                ArchiveJob,
                pk=job.pk,
                expected_version=job.row_version,
                changes={"status": ArchiveJob.Status.PASSED, "completed_at": timezone.now()},
            )
        try:
            _finish_task_cleanup(job, context, archive_verified=True)
        except Exception as exc:
            _record_cleanup_failure(job, exc, context)
            if raise_on_failure:
                raise
        return ArchiveJob.objects.get(pk=job.pk)
    with transaction.atomic():
        job = ArchiveJob.objects.select_for_update().select_related("task__course").get(pk=job.pk)
        job = _mark_job_running(job)
        task = (
            ExperimentTask.objects.select_for_update()
            .select_related("course", "student", "publication")
            .get(pk=job.task_id)
        )
        task = _ensure_archiving(task, context)
    package = None
    try:
        package, entries, package_digest, package_size = _build_package(task)
        manifest_digest = _digest(_canonical_bytes(entries))
        retention_until = _archive_retention_until()
        stored = object_storage().put_stream(
            bucket=settings.MINIO_BUCKET,
            object_key=f"archives/{task.course.public_id}/{task.public_id}/{manifest_digest}.zip",
            stream=package,
            media_type="application/zip",
        )
        asset = register_asset(
            bucket=settings.MINIO_BUCKET,
            object_key=f"archives/{task.course.public_id}/{task.public_id}/{manifest_digest}.zip",
            object_version=stored.version_id,
            digest_sha256=package_digest,
            size_bytes=package_size,
            owner_type="ARCHIVE_PACKAGE",
            owner_ref=task.public_id,
            purpose="TASK_ARCHIVE",
            media_type="application/zip",
            original_name=f"{task.public_id}-archive.zip",
            retention_until=retention_until,
        )
        asset = set_scan_result(
            asset_id=asset.pk,
            expected_version=asset.row_version,
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        actual_digest = _verify_stored_package(asset)
        with transaction.atomic():
            job = (
                ArchiveJob.objects.select_for_update()
                .select_related("task", "course")
                .get(pk=job.pk)
            )
            job = compare_and_swap(
                ArchiveJob,
                pk=job.pk,
                expected_version=job.row_version,
                changes={"status": ArchiveJob.Status.VERIFYING},
            )
            manifest = ArchiveManifest.objects.create(
                job=job,
                task=job.task,
                package_asset=asset,
                entries=entries,
                manifest_digest=manifest_digest,
                package_digest=package_digest,
                object_count=len(entries),
                total_size_bytes=sum(int(item["size_bytes"]) for item in entries),
                retention_until=retention_until,
                trace_id=_trace(context),
            )
            ArchiveVerification.objects.create(
                job=job,
                manifest=manifest,
                package_asset=asset,
                attempt_no=job.attempt_count,
                result=ArchiveVerification.Result.PASSED,
                checks=[{"result": "PASSED", "objects": len(entries)}],
                expected_digest=package_digest,
                actual_digest=actual_digest,
                verified_at=timezone.now(),
                trace_id=_trace(context),
            )
            job = compare_and_swap(
                ArchiveJob,
                pk=job.pk,
                expected_version=job.row_version,
                changes={"status": ArchiveJob.Status.PASSED, "completed_at": timezone.now()},
            )
            _audit(
                context=context,
                action="archive.verify",
                target_type="archive_manifest",
                target_ref=manifest.public_id,
                course_ref=job.course.public_id,
                after={
                    "manifest_digest": manifest_digest,
                    "package_digest": package_digest,
                    "object_count": len(entries),
                },
            )
            _emit(
                event_type=events.ARCHIVE_VERIFIED,
                aggregate_type="archive_job",
                aggregate_ref=job.public_id,
                payload={
                    "job_id": job.public_id,
                    "task_id": job.task.public_id,
                    "course_id": job.course.public_id,
                    "manifest_id": manifest.public_id,
                },
                context=context,
            )
        try:
            _finish_task_cleanup(job, context, archive_verified=True)
        except Exception as exc:
            _record_cleanup_failure(job, exc, context)
            if raise_on_failure:
                raise
        ARCHIVE_JOBS_TOTAL.labels(result="passed", terminal_target=job.terminal_target).inc()
        return ArchiveJob.objects.get(pk=job.pk)
    except Exception as exc:
        with transaction.atomic():
            current = (
                ArchiveJob.objects.select_for_update()
                .select_related("course", "task")
                .get(pk=job.pk)
            )
            failed = _record_archive_failure(current, exc, context)
        if raise_on_failure:
            raise
        return failed
    finally:
        if package is not None:
            package.close()


def retry_archive_compensation(task: CompensationTask) -> None:
    execute_archive_job(job_id=task.subject_ref, trace_id=task.trace_id, raise_on_failure=True)


@transaction.atomic
def retry_compensation_as_admin(
    *,
    compensation_id: str,
    actor: User,
    expected_version: int,
    reason: str,
    context: Any,
) -> CompensationTask:
    try:
        item = CompensationTask.objects.select_for_update().get(public_id=compensation_id)
    except CompensationTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if item.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": item.row_version,
            }
        )
    if item.status not in {CompensationTask.Status.RETRY, CompensationTask.Status.DEAD}:
        raise ArchiveStateConflict(detail={"compensation_status": item.status})
    if not reason.strip():
        raise ArchiveStateConflict(detail={"reason": "required"})
    changed = compare_and_swap(
        CompensationTask,
        pk=item.pk,
        expected_version=item.row_version,
        changes={
            "status": CompensationTask.Status.RETRY,
            "max_attempts": max(item.max_attempts, item.attempt_count + 1),
            "next_attempt_at": timezone.now(),
            "lease_token": None,
            "lease_until": None,
        },
    )
    _audit(
        context=context,
        actor=actor,
        action="platform.compensation.retry",
        target_type="compensation_task",
        target_ref=changed.public_id,
        course_ref="",
        before={"status": item.status},
        after={"status": changed.status, "reason": reason.strip()},
    )
    from apps.core.tasks import run_compensations

    transaction.on_commit(
        lambda: run_compensations.apply_async(
            kwargs={"trace_id": _trace(context)},
            queue="q_compensate",
            task_id=f"manual-compensation:{changed.public_id}:{changed.row_version}",
        )
    )
    return changed  # type: ignore[return-value]


def archive_course_blockers(course: Course) -> list[Blocker]:
    active_tasks = ExperimentTask.objects.filter(course=course).exclude(
        status__in=TERMINAL_STATUSES
    )
    active_jobs = ArchiveJob.objects.filter(course=course).exclude(status=ArchiveJob.Status.PASSED)
    blockers = []
    for name, queryset, message in (
        ("UNFINISHED_TASK", active_tasks, "仍有未终止个人任务"),
        ("ARCHIVING_IN_PROGRESS", active_jobs, "仍有未完成归档作业"),
    ):
        refs = tuple(queryset.values_list("public_id", flat=True)[:20])
        count = queryset.count()
        if count:
            blockers.append(Blocker(type=name, count=count, refs=refs, message=message))
    return blockers


def authorize_archive_download(asset: ObjectAsset, actor: User, portal: str) -> str:
    try:
        manifest = ArchiveManifest.objects.select_related("task__student", "task__course").get(
            package_asset=asset
        )
    except ArchiveManifest.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if manifest.retention_until <= timezone.now():
        raise DownloadScopeDenied()
    if portal == "USER" and manifest.task.student_id == actor.pk:
        return manifest.task.course.public_id
    if portal == "TEACHING":
        require_course_capability(
            course=manifest.task.course,
            actor=actor,
            capability=CourseStaffGrant.Capability.EXPORT_RESULT,
        )
        return manifest.task.course.public_id
    raise DownloadScopeDenied()


def record_archive_export(
    grant: FileDownloadGrant, actor: User, portal: str, trace_id: str
) -> None:
    if grant.asset.owner_type != "ARCHIVE_PACKAGE":
        return
    manifest = ArchiveManifest.objects.select_related("task__course").get(package_asset=grant.asset)
    scope = {
        "course_id": manifest.task.course.public_id,
        "task_id": manifest.task.public_id,
        "archive_id": manifest.job.public_id,
        "manifest_id": manifest.public_id,
    }
    export = ArchiveExportGrant.objects.create(
        manifest=manifest,
        download_grant=grant,
        course=manifest.task.course,
        requested_by=actor,
        approved_by=actor,
        portal=portal,
        scope=scope,
        scope_digest=_digest(_canonical_bytes(scope)),
        retention_until=min(manifest.retention_until, grant.expires_at),
        trace_id=trace_id,
    )
    context = SimpleNamespace(actor_ref=actor.public_id, portal=portal, trace_id=trace_id)
    _audit(
        context=context,
        actor=actor,
        action="archive.export.grant",
        target_type="archive_export_grant",
        target_ref=export.public_id,
        course_ref=manifest.task.course.public_id,
        after={
            "scope": scope,
            "expires_at": grant.expires_at.isoformat(),
            "max_downloads": grant.max_downloads,
        },
    )
    _emit(
        event_type=events.EXPORT_GRANTED,
        aggregate_type="archive_export_grant",
        aggregate_ref=export.public_id,
        payload={"export_id": export.public_id, **scope},
        context=context,
    )
    ARCHIVE_EXPORTS_TOTAL.labels(portal=portal, result="granted").inc()


@transaction.atomic
def create_archive_export(
    *,
    course_id: str,
    archive_id: str,
    actor: User,
    expected_version: int,
    token: str,
    context: Any,
) -> tuple[FileDownloadGrant, str]:
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        # Immutable manifests must stay outside the app role's locking query.
        job = ArchiveJob.objects.select_for_update().get(public_id=archive_id, course=course)
    except (Course.DoesNotExist, ArchiveJob.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.EXPORT_RESULT
    )
    if job.row_version != expected_version:
        raise RowVersionConflict(
            detail={"expected_row_version": expected_version, "actual_row_version": job.row_version}
        )
    if job.status != ArchiveJob.Status.PASSED or not hasattr(job, "manifest"):
        raise ArchiveStateConflict(detail={"status": job.status})
    remaining = int((job.manifest.retention_until - timezone.now()).total_seconds())
    if remaining <= 0:
        raise ArchiveStateConflict(detail={"retention": "expired"})
    ttl = min(int(getattr(settings, "ARCHIVE_EXPORT_TTL_SECONDS", 300)), remaining)
    return create_download_grant(
        asset_id=job.manifest.package_asset.public_id,
        actor=actor,
        portal="TEACHING",
        trace_id=_trace(context),
        token=token,
        ttl_seconds=ttl,
        max_downloads=1,
        client_ip=str(getattr(context, "client_ip", "")),
        user_agent=str(getattr(context, "user_agent", "")),
    )


def schedule_course_reconciliation(course: Course, context: Any) -> None:
    from .tasks import reconcile_course_archives

    reconcile_course_archives.apply_async(
        kwargs={"course_id": course.public_id, "trace_id": _trace(context)},
        task_id=f"archive-course-reconcile:{course.public_id}:{course.row_version}",
    )


def reconcile_archives(*, trace_id: str = "") -> dict[str, int]:
    from .tasks import run_archive_job

    count = 0
    for job in ArchiveJob.objects.filter(
        status__in=("QUEUED", "FAILED"),
        attempt_count__lt=models.F("max_attempts"),
    ):
        run_archive_job.apply_async(kwargs={"job_id": job.public_id, "trace_id": trace_id})
        count += 1
    return {"redispatched": count}


def purge_expired_archive_objects(*, trace_id: str = "") -> dict[str, int]:
    now = timezone.now()
    purged = 0
    skipped = 0
    failed = 0
    manifests = ArchiveManifest.objects.select_related("package_asset").filter(
        retention_until__lte=now,
        package_asset__status__in=(ObjectAsset.Status.ACTIVE, ObjectAsset.Status.PURGE_PENDING),
    )
    for manifest in manifests.iterator():
        active_grant = ArchiveExportGrant.objects.filter(
            manifest=manifest,
            retention_until__gt=now,
            download_grant__expires_at__gt=now,
            download_grant__revoked_at__isnull=True,
        ).exists()
        if active_grant:
            skipped += 1
            ARCHIVE_RETENTION_TOTAL.labels(result="skipped").inc()
            continue
        with transaction.atomic():
            asset = ObjectAsset.objects.select_for_update().get(pk=manifest.package_asset_id)
            if asset.status == ObjectAsset.Status.PURGED:
                continue
            if asset.status == ObjectAsset.Status.ACTIVE:
                asset = compare_and_swap(
                    ObjectAsset,
                    pk=asset.pk,
                    expected_version=asset.row_version,
                    changes={"status": ObjectAsset.Status.PURGE_PENDING},
                )
        try:
            actual_digest = _verify_stored_package(asset)
            if actual_digest != manifest.package_digest:
                raise ArchiveVerificationFailed(detail={"reason": "digest_mismatch"})
            object_storage().delete_object(
                bucket=asset.bucket,
                object_key=asset.object_key,
                version_id=asset.object_version,
            )
            record_purge_result(
                asset_id=asset.pk,
                expected_version=asset.row_version,
                result=ObjectPurgeLog.Result.PURGED,
                trace_id=trace_id,
                reason="archive retention expired",
            )
            purged += 1
            ARCHIVE_RETENTION_TOTAL.labels(result="purged").inc()
        except Exception as exc:  # noqa: BLE001 - keep processing independent objects
            failed += 1
            append_failure(
                failure_type="ARCHIVE_RETENTION",
                subject_type="ARCHIVE_MANIFEST",
                subject_ref=manifest.public_id,
                error_code=getattr(exc, "code", "ARCHIVE_RETENTION_PURGE_FAILED"),
                message=getattr(exc, "code", "ARCHIVE_RETENTION_PURGE_FAILED"),
                detail={"asset_id": asset.public_id},
                retryable=True,
                trace_id=trace_id,
            )
            with suppress(Exception):
                record_purge_result(
                    asset_id=asset.pk,
                    expected_version=asset.row_version,
                    result=ObjectPurgeLog.Result.FAILED,
                    trace_id=trace_id,
                    reason="archive retention cleanup failed",
                    error_code=getattr(exc, "code", "ARCHIVE_RETENTION_PURGE_FAILED"),
                )
            ARCHIVE_RETENTION_TOTAL.labels(result="failed").inc()
    return {"purged": purged, "skipped": skipped, "failed": failed}
