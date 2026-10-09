import logging
from contextlib import suppress
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.audit import append_audit, hash_client_ip
from apps.core.compensation import create_compensation
from apps.core.concurrency import compare_and_swap
from apps.core.models import CompensationTask, FailureRecord
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.models import Enrollment
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import (
    prerequisite_blockers_for_publication,
    transition_task,
)
from apps.governance.errors import QuotaExceeded
from apps.governance.models import QuotaReservation
from apps.governance.models import RuntimeAdapter as RuntimeAdapterConfig
from apps.governance.services import effective_resource_profile, release_reservation, reserve_quota

from . import events
from .adapters import RuntimeAdapterFailure, runtime_adapter_for, runtime_for_driver
from .errors import ProvisioningConfigurationError, ProvisioningStateConflict
from .metrics import (
    PROVISIONING_DURATION,
    PROVISIONING_JOBS_TOTAL,
    PROVISIONING_STAGE_TOTAL,
    RUNTIME_CONTAINER_CREATE_DURATION,
    RUNTIME_ENGINE_UNAVAILABLE_TOTAL,
    RUNTIME_WORKSPACE_START_DURATION,
    is_engine_unavailable,
)
from .models import (
    ProvisioningInstance,
    ProvisioningJob,
    ProvisioningStageEvent,
    RuntimeCapacityReservation,
    public_id_field,
)
from .ports import RuntimeAdapter, RuntimeInventoryItem, RuntimeSpec
from .selectors import active_job_for_task, jobs_for_task

STAGES: tuple[str, ...] = tuple(ProvisioningJob.Stage.values)
ACTIVE_JOB_STATUSES = (
    ProvisioningJob.Status.QUEUED,
    ProvisioningJob.Status.RUNNING,
    ProvisioningJob.Status.RETRY,
)


@transaction.atomic
def reserve_runtime_capacity(
    *,
    reservation_id: str | QuotaReservation,
    runtime_adapter_id: str,
    cpu_millicores: int,
    memory_mb: int,
) -> RuntimeCapacityReservation | None:
    """Atomically admit a quota reservation against adapter capacity."""
    if cpu_millicores <= 0 or memory_mb <= 0:
        raise ProvisioningConfigurationError(
            detail={"capacity": "cpu_and_memory_must_be_positive"}
        )
    reservation = reservation_id
    if isinstance(reservation_id, str):
        reservation = QuotaReservation.objects.select_for_update().get(public_id=reservation_id)
    else:
        reservation = QuotaReservation.objects.select_for_update().get(pk=reservation.pk)
    runtime = RuntimeAdapterConfig.objects.select_for_update().get(public_id=runtime_adapter_id)
    if reservation.status != QuotaReservation.Status.ACTIVE:
        raise ProvisioningStateConflict(detail={"reservation": reservation.status})
    existing = RuntimeCapacityReservation.objects.select_for_update().filter(
        reservation=reservation
    ).first()
    if existing is not None:
        if existing.status != RuntimeCapacityReservation.Status.ACTIVE:
            raise ProvisioningStateConflict(detail={"reservation": "capacity_already_released"})
        if (existing.cpu_millicores, existing.memory_mb) != (cpu_millicores, memory_mb):
            raise ProvisioningStateConflict(detail={"reservation": "capacity_binding_mismatch"})
        if existing.runtime_adapter_id != runtime.pk:
            raise ProvisioningStateConflict(detail={"reservation": "runtime_binding_mismatch"})
        return existing
    # Zero-valued capacity is the historical "not reported" marker.
    if (
        runtime.capacity_cpu_millicores
        and runtime.available_cpu_millicores < cpu_millicores
    ) or (
        runtime.capacity_memory_mb
        and runtime.available_memory_mb < memory_mb
    ):
        raise QuotaExceeded(
            detail={
                "dimension": "runtime_capacity",
                "available_cpu_millicores": runtime.available_cpu_millicores,
                "available_memory_mb": runtime.available_memory_mb,
                "requested_cpu_millicores": cpu_millicores,
                "requested_memory_mb": memory_mb,
            }
        )
    if runtime.capacity_cpu_millicores or runtime.capacity_memory_mb:
        changed = compare_and_swap(
            RuntimeAdapterConfig,
            pk=runtime.pk,
            expected_version=runtime.row_version,
            changes={
                "available_cpu_millicores": (
                    runtime.available_cpu_millicores - cpu_millicores
                    if runtime.capacity_cpu_millicores
                    else runtime.available_cpu_millicores
                ),
                "available_memory_mb": (
                    runtime.available_memory_mb - memory_mb
                    if runtime.capacity_memory_mb
                    else runtime.available_memory_mb
                ),
            },
        )
        del changed
    return RuntimeCapacityReservation.objects.create(
        reservation=reservation,
        runtime_adapter=runtime,
        cpu_millicores=cpu_millicores,
        memory_mb=memory_mb,
    )


@transaction.atomic
def release_runtime_capacity(
    *, reservation_id: str | QuotaReservation
) -> RuntimeCapacityReservation | None:
    """Release a runtime binding once; repeated calls are no-ops."""
    reservation = reservation_id
    if isinstance(reservation_id, str):
        reservation = QuotaReservation.objects.select_for_update().get(public_id=reservation_id)
    else:
        reservation = QuotaReservation.objects.select_for_update().get(pk=reservation.pk)
    binding = RuntimeCapacityReservation.objects.select_for_update().filter(
        reservation=reservation
    ).first()
    if binding is None or binding.status != RuntimeCapacityReservation.Status.ACTIVE:
        return binding
    runtime = RuntimeAdapterConfig.objects.select_for_update().get(pk=binding.runtime_adapter_id)
    changes: dict[str, int] = {}
    if runtime.capacity_cpu_millicores:
        changes["available_cpu_millicores"] = min(
            runtime.capacity_cpu_millicores,
            runtime.available_cpu_millicores + binding.cpu_millicores,
        )
    if runtime.capacity_memory_mb:
        changes["available_memory_mb"] = min(
            runtime.capacity_memory_mb,
            runtime.available_memory_mb + binding.memory_mb,
        )
    if changes:
        compare_and_swap(
            RuntimeAdapterConfig,
            pk=runtime.pk,
            expected_version=runtime.row_version,
            changes=changes,
        )
    return compare_and_swap(
        RuntimeCapacityReservation,
        pk=binding.pk,
        expected_version=binding.row_version,
        changes={
            "status": RuntimeCapacityReservation.Status.RELEASED,
            "released_at": timezone.now(),
        },
    )


def _release_reservation(*, reservation_id: str, reason: str, context: Any) -> None:
    try:
        release_runtime_capacity(reservation_id=reservation_id)
    except Exception as exc:  # noqa: BLE001 - quota release must proceed independently
        logger.error(
            "runtime capacity release failed",
            extra={
                "trace_id": _trace(context),
                "resource_ref": reservation_id,
                "error_code": str(getattr(exc, "code", "RUNTIME_CAPACITY_RELEASE_FAILED")),
                "result": "FAILED",
            },
        )
    release_reservation(reservation_id=reservation_id, reason=reason, context=context)


logger = logging.getLogger("runtime.provisioning")


def _trace(context: Any) -> str:
    return str(getattr(context, "trace_id", ""))


def _actor_ref(actor: User | None, context: Any) -> str:
    return actor.public_id if actor is not None else str(getattr(context, "actor_ref", "worker"))


def _audit(
    *,
    context: Any,
    actor: User | None,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    before: Any = None,
    after: Any = None,
    result: str = "SUCCEEDED",
    error_code: str = "",
) -> None:
    append_audit(
        actor_ref=_actor_ref(actor, context),
        actor_portal=str(getattr(context, "portal", "")),
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
        before=before,
        after=after,
        result=result,
        error_code=error_code,
        client_ip_hash=hash_client_ip(
            str(getattr(context, "client_ip", "")), salt=settings.AUDIT_IP_HASH_SALT
        ),
        user_agent_summary=str(getattr(context, "user_agent", "")),
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


def _task_runtime_snapshot(task: ExperimentTask) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Return task-frozen runtime rows, with a legacy-template fallback."""

    template = task.template_version
    adapter = task.runtime_adapter or template.runtime_adapter
    image = task.image or template.image
    profile = task.resource_profile or template.resource_profile
    profile_snapshot = effective_resource_profile(task)
    return adapter, image, profile, profile_snapshot


def _runtime_spec(
    task: ExperimentTask, *, trace_id: str = "", instance_public_id: str = ""
) -> RuntimeSpec:
    template = task.template_version
    _, image, _, profile_snapshot = _task_runtime_snapshot(task)
    deadline = task.effective_deadline or task.publication.window_end
    ttl_seconds = max(
        60,
        min(
            int((deadline - timezone.now()).total_seconds()),
            int(getattr(settings, "RUNTIME_DEFAULT_TTL_SECONDS", 14400)),
        ),
    )

    network_policy = dict(template.network_policy or {})
    execution_spec = dict(task.execution_spec or {})
    network_policy["mode"] = str(
        execution_spec.get("network_mode")
        or profile_snapshot["network_mode"]
    )
    return RuntimeSpec(
        task_id=task.public_id,
        course_id=task.course.public_id,
        student_id=task.student.public_id,
        runtime_type=task.runtime_type,
        image_registry=task.image_registry or image.registry,
        image_repository=task.image_repository or image.repository,
        image_digest=task.image_digest or image.digest,
        resource_profile_id=str(profile_snapshot["public_id"]),
        cpu_millicores=int(profile_snapshot["cpu_request_millicores"]),
        memory_mb=int(profile_snapshot["memory_request_mb"]),
        disk_gb=int(profile_snapshot["disk_gb"]),
        network_policy={
            "mode": profile_snapshot["network_mode"],
            **network_policy,
        },
        workspace_capabilities=template.workspace_capabilities,
        ttl_seconds=ttl_seconds,
        workspace_port=int(getattr(settings, "RUNTIME_WORKSPACE_PORT", 8080)),
        healthcheck_path=str(getattr(settings, "RUNTIME_HEALTHCHECK_PATH", "/healthz")),
        trace_id=trace_id,
        instance_public_id=instance_public_id,
    )


def _runtime_adapter_for_row(
    *, driver: str, config_ref: str = "", code: str = ""
) -> RuntimeAdapter:
    """Use the explicit deployment mode for its selected governance row.

    Historical rows may still name a different driver/configuration, so those
    continue through the compatibility resolver until they are migrated.
    """

    configured_code = str(getattr(settings, "RUNTIME_ADAPTER_CODE", "")).strip()
    if configured_code and code.strip().casefold() == configured_code.casefold():
        return runtime_adapter_for(configured_code)
    return runtime_for_driver(driver, config_ref=config_ref)


def _reservation_values(task: ExperimentTask) -> dict[str, int]:
    _, _, _, profile_snapshot = _task_runtime_snapshot(task)
    return {
        "instance_count": 1,
        "start_count": 1,
        "cpu_millicores": int(profile_snapshot["cpu_request_millicores"]),
        "memory_mb": int(profile_snapshot["memory_request_mb"]),
        "disk_gb": int(profile_snapshot["disk_gb"]),
        "object_storage_bytes": 0,
        "agent_tokens": 0,
        "agent_requests": 0,
    }


def _load_task(task_id: str, *, actor: User | None = None) -> ExperimentTask:
    queryset = ExperimentTask.objects.select_for_update().select_related(
        "course",
        "publication",
        "enrollment",
        "student",
        "runtime_adapter",
        "image",
        "resource_profile",
        "template_version__runtime_adapter",
        "template_version__image",
        "template_version__resource_profile",
    )
    if actor is not None:
        queryset = queryset.filter(student=actor)
    try:
        return queryset.get(public_id=task_id)
    except ExperimentTask.DoesNotExist as exc:
        from apps.core.errors import ResourceNotFound

        raise ResourceNotFound() from exc


def _next_attempt_no(task: ExperimentTask) -> int:
    latest = jobs_for_task(task).order_by("-attempt_no").first()
    return (latest.attempt_no + 1) if latest is not None else 1


def _create_job_and_reservation(
    *, task: ExperimentTask, context: Any, attempt_no: int
) -> ProvisioningJob:
    job_id = public_id_field().get_default()  # type: ignore[assignment]
    reservation = reserve_quota(
        reservation_key=f"provisioning:{job_id}",
        reservation_type=QuotaReservation.ReservationType.STANDARD,
        subject_type="EXPERIMENT_TASK",
        subject_ref=task.public_id,
        course_id=task.course.public_id,
        user_id=task.student.public_id,
        resource_profile_id=str(
            (task.resource_profile_snapshot or {}).get("public_id")
            or (task.resource_profile or task.template_version.resource_profile).public_id
        ),
        values=_reservation_values(task),
        expires_at=None,
        context=context,
    )
    adapter = _task_runtime_snapshot(task)[0]
    reserve_runtime_capacity(
        reservation_id=reservation,
        runtime_adapter_id=adapter.public_id,
        cpu_millicores=_reservation_values(task)["cpu_millicores"],
        memory_mb=_reservation_values(task)["memory_mb"],
    )
    job = ProvisioningJob.objects.create(
        public_id=job_id,
        task=task,
        course=task.course,
        reservation=reservation,
        attempt_no=attempt_no,
        status=ProvisioningJob.Status.QUEUED,
        current_stage=ProvisioningJob.Stage.QUOTA_CHECK,
        idempotency_key=f"provisioning:{job_id}",
        trace_id=_trace(context),
    )
    instance, created = ProvisioningInstance.objects.get_or_create(
        task=task,
        defaults={
            "course": task.course,
            "runtime_adapter": _task_runtime_snapshot(task)[0],
            "image": _task_runtime_snapshot(task)[1],
            "resource_profile": _task_runtime_snapshot(task)[2],
            "runtime_type": task.runtime_type,
            "status": ProvisioningInstance.Status.CREATING,
            "created_trace_id": _trace(context),
        },
    )
    if not created and instance.external_id:
        raise ProvisioningStateConflict(
            detail={
                "instance_external_id_present": True,
                "instance_status": instance.status,
            }
        )
    if not created and instance.status in (
        ProvisioningInstance.Status.FAILED,
        ProvisioningInstance.Status.DESTROYED,
    ):
        compare_and_swap(
            ProvisioningInstance,
            pk=instance.pk,
            expected_version=instance.row_version,
            changes={
                "status": ProvisioningInstance.Status.CREATING,
                "external_id": None,
                "endpoint": "",
                "failure_record": None,
                "created_trace_id": _trace(context),
            },
        )
    _emit(
        event_type=events.JOB_CREATED,
        aggregate_type="provisioning_job",
        aggregate_ref=job.public_id,
        payload={
            "job_id": job.public_id,
            "task_id": task.public_id,
            "course_id": task.course.public_id,
            "status": job.status,
            "events_channel": f"task:{task.public_id}",
        },
        context=context,
    )
    return job


def _enqueue(job: ProvisioningJob) -> None:
    from .tasks import run_provisioning_job

    transaction.on_commit(
        lambda: run_provisioning_job.apply_async(
            kwargs={"job_id": job.public_id, "trace_id": job.trace_id}
        )
    )


@transaction.atomic
def start_provisioning(
    *, task_id: str, actor: User, expected_version: int, context: ActorContext
) -> tuple[ExperimentTask, ProvisioningJob]:
    task = _load_task(task_id, actor=actor)
    if task.status != ExperimentTask.Status.ASSIGNED:
        raise ProvisioningStateConflict(detail={"status": task.status})
    if task.enrollment.status != Enrollment.Status.ACTIVE:
        raise ProvisioningStateConflict(detail={"enrollment_status": task.enrollment.status})
    now = timezone.now()
    if now < task.publication.window_start or now > (
        task.effective_deadline or task.publication.window_end
    ):
        raise ProvisioningStateConflict(
            detail={
                "window_start": task.publication.window_start,
                "effective_deadline": task.effective_deadline,
            }
        )
    blockers = prerequisite_blockers_for_publication(publication=task.publication, student=actor)
    if blockers:
        from apps.experiments.errors import PublicationPrerequisiteBlocked

        raise PublicationPrerequisiteBlocked(detail={"blockers": blockers})
    if active_job_for_task(task) is not None:
        raise ProvisioningStateConflict(detail={"active_job": True})
    adapter_row, image, profile, _ = _task_runtime_snapshot(task)
    if adapter_row.status != "ENABLED" or adapter_row.health_status in ("DEGRADED", "UNAVAILABLE"):
        raise ProvisioningStateConflict(detail={"runtime_adapter": adapter_row.public_id})
    if (
        image.scan_status != "CLEAN"
        or image.approval_status != "APPROVED"
    ):
        raise ProvisioningConfigurationError(detail={"image": "not_approved_or_clean"})
    if profile.status != "ACTIVE":
        raise ProvisioningConfigurationError(detail={"resource_profile": "not_active"})
    job = _create_job_and_reservation(task=task, context=context, attempt_no=_next_attempt_no(task))
    changed = transition_task(
        task_id=task.public_id,
        to_status=ExperimentTask.Status.PROVISIONING,
        actor=actor,
        expected_version=expected_version,
        trigger="START",
        reason="student started provisioning",
        context=context,
        detail={"job_id": job.public_id},
    )
    _audit(
        context=context,
        actor=actor,
        action="provisioning.start",
        target_type="experiment_task",
        target_ref=task.public_id,
        course_ref=task.course.public_id,
        before={"status": task.status},
        after={"status": changed.status, "job_id": job.public_id},
    )
    _enqueue(job)
    return changed, job


@transaction.atomic
def retry_provisioning(
    *, task_id: str, actor: User, expected_version: int, context: ActorContext
) -> tuple[ExperimentTask, ProvisioningJob]:
    task = _load_task(task_id, actor=actor)
    failure = task.current_failure or {}
    if task.status != ExperimentTask.Status.FAILED or not failure.get("retryable"):
        raise ProvisioningStateConflict(
            detail={"status": task.status, "retryable": failure.get("retryable", False)}
        )
    if failure.get("previous_status") != ExperimentTask.Status.PROVISIONING:
        raise ProvisioningStateConflict(detail={"previous_status": failure.get("previous_status")})
    if task.enrollment.status != Enrollment.Status.ACTIVE:
        raise ProvisioningStateConflict(detail={"enrollment_status": task.enrollment.status})
    instance = ProvisioningInstance.objects.select_for_update().filter(task=task).first()
    if instance is not None and instance.external_id:
        previous_job = (
            jobs_for_task(task)
            .filter(status=ProvisioningJob.Status.FAILED)
            .order_by("-attempt_no")
            .first()
        )
        compensation = previous_job.compensation_task if previous_job is not None else None
        if compensation is None or compensation.status != CompensationTask.Status.COMPLETED:
            raise ProvisioningStateConflict(
                detail={
                    "compensation_pending": True,
                    "compensation_status": compensation.status if compensation else None,
                }
            )
    attempt_no = _next_attempt_no(task)
    previous_job = jobs_for_task(task).first()
    if previous_job is not None and attempt_no > previous_job.max_attempts:
        raise ProvisioningStateConflict(
            detail={"max_attempts": previous_job.max_attempts, "attempt_no": attempt_no}
        )
    job = _create_job_and_reservation(task=task, context=context, attempt_no=attempt_no)
    changed = transition_task(
        task_id=task.public_id,
        to_status=ExperimentTask.Status.PROVISIONING,
        actor=actor,
        expected_version=expected_version,
        trigger="RETRY",
        reason="student retried provisioning",
        context=context,
        detail={"job_id": job.public_id},
    )
    _enqueue(job)
    return changed, job


@transaction.atomic
def cancel_queued_provisioning(
    *, task_id: str, actor: User, expected_version: int, context: ActorContext
) -> tuple[ExperimentTask, ProvisioningJob]:
    task = _load_task(task_id, actor=actor)
    job = active_job_for_task(task)
    if job is None:
        raise ProvisioningStateConflict(detail={"active_job": False})
    if job.status != ProvisioningJob.Status.QUEUED:
        raise ProvisioningStateConflict(detail={"job_status": job.status})
    changed_job = compare_and_swap(
        ProvisioningJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={
            "status": ProvisioningJob.Status.CANCELLED,
            "retryable": True,
            "completed_at": timezone.now(),
        },
    )
    instance = ProvisioningInstance.objects.select_for_update().filter(task=task).first()
    if instance is not None and not instance.external_id:
        compare_and_swap(
            ProvisioningInstance,
            pk=instance.pk,
            expected_version=instance.row_version,
            changes={
                "status": ProvisioningInstance.Status.DESTROYED,
                "destroyed_at": timezone.now(),
            },
        )
    _release_reservation(
        reservation_id=job.reservation.public_id,
        reason="queued provisioning cancelled",
        context=context,
    )
    changed_task = transition_task(
        task_id=task.public_id,
        to_status=ExperimentTask.Status.FAILED,
        actor=actor,
        expected_version=expected_version,
        trigger="CANCEL_PROVISIONING",
        reason="queued provisioning cancelled",
        context=context,
        detail={"retryable": True, "error_code": "PROVISIONING_CANCELLED", "job_id": job.public_id},
    )
    _emit(
        event_type=events.JOB_CANCELLED,
        aggregate_type="provisioning_job",
        aggregate_ref=changed_job.public_id,
        payload={
            "job_id": changed_job.public_id,
            "task_id": task.public_id,
            "status": changed_job.status,
        },
        context=context,
    )
    return changed_task, changed_job


@transaction.atomic
def _stage_started(job: ProvisioningJob, stage: str, context: Any) -> ProvisioningStageEvent:
    now = timezone.now()
    job = compare_and_swap(
        ProvisioningJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={"current_stage": stage},
    )  # type: ignore[assignment]
    event = ProvisioningStageEvent.objects.create(
        job=job,
        stage=stage,
        status=ProvisioningStageEvent.Status.STARTED,
        attempt_no=job.attempt_count,
        trace_id=_trace(context),
        started_at=now,
    )
    PROVISIONING_STAGE_TOTAL.labels(stage=stage, status="STARTED").inc()
    return event


@transaction.atomic
def _stage_finished(
    event: ProvisioningStageEvent,
    *,
    status: str,
    detail: dict[str, Any],
    context: Any,
    error_code: str = "",
) -> None:
    completed_at = timezone.now()
    ProvisioningStageEvent.objects.create(
        job=event.job,
        stage=event.stage,
        status=status,
        attempt_no=event.attempt_no,
        detail_masked=detail,
        error_code=error_code,
        trace_id=event.trace_id,
        started_at=event.started_at,
        completed_at=completed_at,
    )
    PROVISIONING_STAGE_TOTAL.labels(stage=event.stage, status=status).inc()
    job = ProvisioningJob.objects.select_related("task").get(pk=event.job_id)
    duration = max(0.0, (completed_at - (event.started_at or completed_at)).total_seconds())
    driver = str(job.task.runtime_adapter_driver or job.task.runtime_type or "UNKNOWN")
    if event.stage == ProvisioningJob.Stage.CREATE:
        RUNTIME_CONTAINER_CREATE_DURATION.labels(driver=driver, result=status).observe(duration)
    elif event.stage == ProvisioningJob.Stage.WORKSPACE_READY:
        RUNTIME_WORKSPACE_START_DURATION.labels(driver=driver, result=status).observe(duration)
    _emit(
        event_type=events.STAGE_CHANGED,
        aggregate_type="provisioning_job",
        aggregate_ref=job.public_id,
        payload={
            "job_id": job.public_id,
            "task_id": job.task.public_id,
            "stage": event.stage,
            "status": status,
            "error_code": error_code,
        },
        context=context,
    )


def _job_context(job: ProvisioningJob) -> ActorContext:
    return ActorContext(actor_ref="worker", portal="WORKER", trace_id=job.trace_id)


def _error_code(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, RuntimeAdapterFailure):
        return exc.code, exc.retryable
    if isinstance(exc, TimeoutError):
        return str(exc) or "RUNTIME_TIMEOUT", True
    if isinstance(exc, ProvisioningConfigurationError):
        return exc.code, False
    return "PROVISIONING_STAGE_FAILED", True


def _failure_detail(exc: Exception, error_code: str) -> dict[str, Any]:
    return {"error_code": error_code, "retryable": True, "detail": str(exc)[:255]}


@transaction.atomic
def _mark_failed(job: ProvisioningJob, exc: Exception, context: ActorContext) -> None:
    job = (
        ProvisioningJob.objects.select_for_update()
        .select_related("task", "reservation")
        .get(pk=job.pk)
    )
    error_code, retryable = _error_code(exc)
    driver = str(job.task.runtime_adapter_driver or job.task.runtime_type or "UNKNOWN")
    if is_engine_unavailable(error_code):
        RUNTIME_ENGINE_UNAVAILABLE_TOTAL.labels(driver=driver).inc()
    failure = FailureRecord.objects.create(
        failure_type="PROVISIONING",
        subject_type="PROVISIONING_JOB",
        subject_ref=job.public_id,
        error_code=error_code,
        message_masked=error_code,
        detail_masked={"stage": job.current_stage},
        retryable=retryable,
        trace_id=job.trace_id,
    )
    instance = ProvisioningInstance.objects.select_for_update().filter(task=job.task).first()
    compensation: CompensationTask | None = None
    if instance is not None and instance.external_id:
        compensation = create_compensation(
            task_type="COMPENSATE_PROVISIONING",
            subject_type="PROVISIONING_JOB",
            subject_ref=job.public_id,
            payload={"job_id": job.public_id, "external_id": instance.external_id},
            trace_id=job.trace_id,
        )
        from apps.core.tasks import run_compensations

        transaction.on_commit(
            lambda: run_compensations.apply_async(
                kwargs={"trace_id": job.trace_id},
                queue="q_compensate",
                task_id=f"p07-compensation-{compensation.public_id}",
            )
        )
    changed = compare_and_swap(
        ProvisioningJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={
            "status": ProvisioningJob.Status.FAILED,
            "retryable": retryable,
            "failure_record": failure,
            "compensation_task": compensation,
            "completed_at": timezone.now(),
        },
    )
    if instance is not None:
        compare_and_swap(
            ProvisioningInstance,
            pk=instance.pk,
            expected_version=instance.row_version,
            changes={"status": ProvisioningInstance.Status.FAILED, "failure_record": failure},
        )
    with suppress(Exception):
        _release_reservation(
            reservation_id=job.reservation.public_id, reason=error_code, context=context
        )
    task = ExperimentTask.objects.select_for_update().get(pk=job.task_id)
    if task.status == ExperimentTask.Status.PROVISIONING:
        transition_task(
            task_id=task.public_id,
            to_status=ExperimentTask.Status.FAILED,
            actor=None,
            expected_version=task.row_version,
            trigger="PROVISION",
            reason="provisioning stage failed",
            context=context,
            detail={"retryable": retryable, "error_code": error_code, "stage": job.current_stage},
        )
    PROVISIONING_JOBS_TOTAL.labels(status=changed.status, runtime_type=job.task.runtime_type).inc()
    if job.started_at and changed.completed_at:
        PROVISIONING_DURATION.labels(runtime_type=job.task.runtime_type).observe(
            max(0.0, (changed.completed_at - job.started_at).total_seconds())
        )
    logger.warning(
        "runtime provisioning failed",
        extra={
            "trace_id": job.trace_id,
            "task_ref": job.task.public_id,
            "instance_ref": instance.public_id if instance else "",
            "container_ref": instance.external_id if instance else "",
            "resource_ref": job.public_id,
            "error_code": error_code,
            "result": changed.status,
        },
    )
    _emit(
        event_type=events.JOB_FAILED,
        aggregate_type="provisioning_job",
        aggregate_ref=job.public_id,
        payload={
            "job_id": job.public_id,
            "task_id": job.task.public_id,
            "status": changed.status,
            "error_code": error_code,
        },
        context=context,
    )


def execute_provisioning_job(*, job_id: str, trace_id: str = "") -> ProvisioningJob:
    del trace_id
    with transaction.atomic():
        job = (
            ProvisioningJob.objects.select_for_update()
            .select_related(
                "task__course",
                "task__student",
                "task__runtime_adapter",
                "task__image",
                "task__resource_profile",
                "task__template_version__runtime_adapter",
                "task__template_version__image",
                "task__template_version__resource_profile",
                "reservation",
            )
            .get(public_id=job_id)
        )
        if job.status not in (ProvisioningJob.Status.QUEUED, ProvisioningJob.Status.RETRY):
            return job
        job = compare_and_swap(
            ProvisioningJob,
            pk=job.pk,
            expected_version=job.row_version,
            changes={
                "status": ProvisioningJob.Status.RUNNING,
                "attempt_count": job.attempt_count + 1,
                "started_at": timezone.now(),
            },
        )  # type: ignore[assignment]
        instance = ProvisioningInstance.objects.select_for_update().get(task=job.task)

    context = _job_context(job)
    spec = _runtime_spec(
        job.task, trace_id=job.trace_id, instance_public_id=instance.public_id
    )
    try:
        adapter_row, image, _, _ = _task_runtime_snapshot(job.task)
        adapter_driver = job.task.runtime_adapter_driver or adapter_row.driver
        adapter_config_ref = job.task.runtime_adapter_config_ref or adapter_row.config_ref
        adapter = _runtime_adapter_for_row(
            driver=adapter_driver,
            config_ref=adapter_config_ref,
            code=adapter_row.code,
        )
        result = None
        for stage in STAGES:
            event = _stage_started(job, stage, context)
            try:
                if stage == ProvisioningJob.Stage.QUOTA_CHECK:
                    result = adapter.preflight(spec)
                elif stage == ProvisioningJob.Stage.IMAGE_PREPARE:
                    if (
                        image.approval_status != "APPROVED"
                        or image.scan_status != "CLEAN"
                    ):
                        raise ProvisioningConfigurationError(
                            detail={"image": "not_approved_or_clean"}
                        )
                    adapter.prepare_image(spec)
                elif stage == ProvisioningJob.Stage.CREATE:
                    result = adapter.create(spec, job.idempotency_key)
                    compare_and_swap(
                        ProvisioningInstance,
                        pk=instance.pk,
                        expected_version=instance.row_version,
                        changes={
                            "external_id": result.external_id,
                            "external_metadata": dict(result.metadata),
                        },
                    )
                    instance = ProvisioningInstance.objects.get(pk=instance.pk)
                elif stage == ProvisioningJob.Stage.NETWORK_ATTACH:
                    adapter.attach_network(spec)
                elif stage == ProvisioningJob.Stage.BOOT_PROBE:
                    if not result:
                        result = adapter.create(spec, job.idempotency_key)
                    if adapter.status(result.external_id) != "READY":
                        raise RuntimeError("RUNTIME_NOT_READY")
                elif stage == ProvisioningJob.Stage.WORKSPACE_READY:
                    if not result:
                        raise RuntimeError("RUNTIME_INSTANCE_MISSING")
                    endpoint = adapter.endpoint(result.external_id)
                    compare_and_swap(
                        ProvisioningInstance,
                        pk=instance.pk,
                        expected_version=instance.row_version,
                        changes={
                            "status": ProvisioningInstance.Status.READY,
                            "endpoint": endpoint,
                            "ready_at": timezone.now(),
                        },
                    )
                    instance = ProvisioningInstance.objects.get(pk=instance.pk)
                _stage_finished(
                    event,
                    status=ProvisioningStageEvent.Status.PASSED,
                    detail={"stage": stage},
                    context=context,
                )
                job = ProvisioningJob.objects.get(pk=job.pk)
            except Exception as exc:
                partial_result = getattr(exc, "result", None)
                if partial_result is not None and instance.external_id is None:
                    compare_and_swap(
                        ProvisioningInstance,
                        pk=instance.pk,
                        expected_version=instance.row_version,
                        changes={
                            "external_id": partial_result.external_id,
                            "external_metadata": dict(partial_result.metadata),
                        },
                    )
                    instance = ProvisioningInstance.objects.get(pk=instance.pk)
                error_code, _ = _error_code(exc)
                _stage_finished(
                    event,
                    status=ProvisioningStageEvent.Status.FAILED,
                    detail={"stage": stage},
                    context=context,
                    error_code=error_code,
                )
                raise
        with transaction.atomic():
            job = (
                ProvisioningJob.objects.select_for_update()
                .select_related("task")
                .get(pk=job.pk)
            )
            task = ExperimentTask.objects.select_for_update().get(pk=job.task_id)
            if task.status == ExperimentTask.Status.PROVISIONING:
                transition_task(
                    task_id=task.public_id,
                    to_status=ExperimentTask.Status.READY,
                    actor=None,
                    expected_version=task.row_version,
                    trigger="PROVISION",
                    reason="provisioning completed",
                    context=context,
                    detail={"job_id": job.public_id},
                )
            changed = compare_and_swap(
                ProvisioningJob,
                pk=job.pk,
                expected_version=job.row_version,
                changes={
                    "status": ProvisioningJob.Status.PASSED,
                    "current_stage": ProvisioningJob.Stage.WORKSPACE_READY,
                    "completed_at": timezone.now(),
                },
            )
            PROVISIONING_JOBS_TOTAL.labels(
                status=changed.status, runtime_type=job.task.runtime_type
            ).inc()
            if job.started_at and changed.completed_at:
                PROVISIONING_DURATION.labels(runtime_type=job.task.runtime_type).observe(
                    max(0.0, (changed.completed_at - job.started_at).total_seconds())
                )
            logger.info(
                "runtime workspace ready",
                extra={
                    "trace_id": job.trace_id,
                    "task_ref": job.task.public_id,
                    "instance_ref": instance.public_id,
                    "container_ref": instance.external_id or "",
                    "resource_ref": job.public_id,
                    "result": changed.status,
                },
            )
            _emit(
                event_type=events.JOB_PASSED,
                aggregate_type="provisioning_job",
                aggregate_ref=job.public_id,
                payload={
                    "job_id": job.public_id,
                    "task_id": job.task.public_id,
                    "status": changed.status,
                },
                context=context,
            )
            return changed  # type: ignore[return-value]
    except Exception as exc:
        _mark_failed(
            ProvisioningJob.objects.select_related("task", "reservation").get(pk=job.pk),
            exc,
            context,
        )
        return ProvisioningJob.objects.get(pk=job.pk)


def compensate_provisioning(task: CompensationTask) -> None:
    context = ActorContext(actor_ref="compensation", portal="WORKER", trace_id=task.trace_id)
    with transaction.atomic():
        job = (
            ProvisioningJob.objects.select_for_update()
            .select_related("reservation", "task")
            .get(public_id=task.subject_ref)
        )
        instance = (
            ProvisioningInstance.objects.select_for_update()
            .select_related("runtime_adapter")
            .filter(task=job.task)
            .first()
        )
        external_id = instance.external_id if instance is not None else None
        driver = instance.runtime_adapter.driver if instance is not None else ""
        config_ref = instance.runtime_adapter.config_ref if instance is not None else ""

    if instance is not None and external_id:
        adapter = _runtime_adapter_for_row(
            driver=driver,
            config_ref=config_ref,
            code=instance.runtime_adapter.code if instance is not None else "",
        )
        adapter.destroy(external_id, f"destroy:{job.public_id}")

    with transaction.atomic():
        job = (
            ProvisioningJob.objects.select_for_update()
            .select_related("reservation", "task")
            .get(pk=job.pk)
        )
        instance = (
            ProvisioningInstance.objects.select_for_update().filter(task=job.task).first()
        )
        if instance is not None and instance.external_id:
            compare_and_swap(
                ProvisioningInstance,
                pk=instance.pk,
                expected_version=instance.row_version,
                changes={
                    "status": ProvisioningInstance.Status.DESTROYED,
                    "external_id": None,
                    "endpoint": "",
                    "destroyed_at": timezone.now(),
                },
            )
        _release_reservation(
            reservation_id=job.reservation.public_id,
            reason="provisioning compensation",
            context=context,
        )


def runtime_inventory(
    *, driver: str = "FAKE", config_ref: str = "", code: str = ""
) -> list[RuntimeInventoryItem]:
    return _runtime_adapter_for_row(
        driver=driver, config_ref=config_ref, code=code
    ).inventory()


def enabled_runtime_inventory(
    *, include_unavailable: bool = False, trace_id: str = ""
) -> list[RuntimeInventoryItem]:
    """Return inventory for enabled adapters, optionally preserving outage facts.

    Reconciliation callers historically treated an unavailable adapter as an empty
    inventory.  The platform list needs to distinguish that condition from a
    confirmed missing runtime, so it can opt into a synthetic marker item with no
    external id.
    """
    result: list[RuntimeInventoryItem] = []
    adapters = RuntimeAdapterConfig.objects.filter(status=RuntimeAdapterConfig.Status.ENABLED)
    for adapter_config in adapters.order_by("driver", "code"):
        try:
            items = runtime_inventory(
                driver=adapter_config.driver,
                config_ref=adapter_config.config_ref,
                code=adapter_config.code,
            )
        except Exception as exc:  # noqa: BLE001 - inventory must not break the platform list
            error_code = str(getattr(exc, "code", "RUNTIME_UNAVAILABLE"))[:64]
            if is_engine_unavailable(error_code):
                RUNTIME_ENGINE_UNAVAILABLE_TOTAL.labels(driver=adapter_config.driver).inc()
            logger.error(
                "runtime inventory unavailable",
                extra={
                    "trace_id": trace_id,
                    "resource_ref": adapter_config.public_id,
                    "error_code": error_code,
                    "result": "UNAVAILABLE",
                },
            )
            if include_unavailable:
                result.append(
                    RuntimeInventoryItem(
                        external_id="",
                        status="UNAVAILABLE",
                        metadata={
                            "adapter_id": adapter_config.public_id,
                            "adapter_code": adapter_config.code,
                            "driver": adapter_config.driver,
                            "error_code": error_code,
                            "inventory_unavailable": True,
                        },
                    )
                )
            continue
        for item in items:
            result.append(
                RuntimeInventoryItem(
                    external_id=item.external_id,
                    status=item.status,
                    metadata={
                        **dict(item.metadata),
                        "adapter_id": adapter_config.public_id,
                        "adapter_code": adapter_config.code,
                        "driver": adapter_config.driver,
                    },
                )
            )
    return result


def enabled_runtime_resources() -> list[RuntimeInventoryItem]:
    """Return managed transient (judge/volume) resources for P11 reconciliation."""

    result: list[RuntimeInventoryItem] = []
    adapters = RuntimeAdapterConfig.objects.filter(status=RuntimeAdapterConfig.Status.ENABLED)
    for adapter_config in adapters.order_by("driver", "code"):
        try:
            adapter = _runtime_adapter_for_row(
                driver=adapter_config.driver,
                config_ref=adapter_config.config_ref,
                code=adapter_config.code,
            )
            inventory_resources = getattr(adapter, "inventory_resources", None)
            if not callable(inventory_resources):
                continue
            items = inventory_resources()
        except RuntimeAdapterFailure:
            continue
        for item in items:
            result.append(
                RuntimeInventoryItem(
                    external_id=item.external_id,
                    status=item.status,
                    metadata={
                        **dict(item.metadata),
                        "adapter_id": adapter_config.public_id,
                        "adapter_code": adapter_config.code,
                        "driver": adapter_config.driver,
                    },
                )
            )
    return result


def runtime_inventory_snapshot(*, trace_id: str = "") -> dict[str, Any]:
    """Build a bounded operations snapshot from DB and managed runtime facts."""

    from apps.reviews.models import AutoCheckRun

    from .metrics import RUNTIME_ENGINE_HEALTH, RUNTIME_INVENTORY, RUNTIME_ORPHAN_RESOURCES

    configs = list(
        RuntimeAdapterConfig.objects.filter(status=RuntimeAdapterConfig.Status.ENABLED)
        .order_by("driver", "code")
    )
    runtime_items: list[RuntimeInventoryItem] = []
    transient_items: list[RuntimeInventoryItem] = []
    drivers: list[dict[str, str]] = []
    for config in configs:
        driver = str(config.driver)
        try:
            adapter = _runtime_adapter_for_row(
                driver=driver,
                config_ref=config.config_ref,
                code=config.code,
            )
            health = dict(adapter.health())
            health_status = str(health.get("status", "UNKNOWN"))
            drivers.append({"driver": driver, "code": config.code, "status": health_status})
            RUNTIME_ENGINE_HEALTH.labels(driver=driver).set(1 if health_status == "HEALTHY" else 0)
            if health_status == "UNAVAILABLE":
                RUNTIME_ENGINE_UNAVAILABLE_TOTAL.labels(driver=driver).inc()
                logger.error(
                    "runtime engine unavailable",
                    extra={
                        "trace_id": trace_id,
                        "resource_ref": config.public_id,
                        "error_code": str(health.get("error_code", "RUNTIME_UNAVAILABLE")),
                        "result": health_status,
                    },
                )
                continue
            for item in adapter.inventory():
                runtime_items.append(
                    RuntimeInventoryItem(
                        external_id=item.external_id,
                        status=item.status,
                        metadata={
                            **dict(item.metadata),
                            "adapter_id": config.public_id,
                            "adapter_code": config.code,
                            "driver": driver,
                        },
                    )
                )
            inventory_resources = getattr(adapter, "inventory_resources", None)
            if callable(inventory_resources):
                for item in inventory_resources():
                    transient_items.append(
                        RuntimeInventoryItem(
                            external_id=item.external_id,
                            status=item.status,
                            metadata={
                                **dict(item.metadata),
                                "adapter_id": config.public_id,
                                "adapter_code": config.code,
                                "driver": driver,
                            },
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - inventory must degrade safely
            drivers.append(
                {
                    "driver": driver,
                    "code": config.code,
                    "status": "UNAVAILABLE",
                    "error_code": str(getattr(exc, "code", "RUNTIME_UNAVAILABLE"))[:64],
                }
            )
            RUNTIME_ENGINE_HEALTH.labels(driver=driver).set(0)
            error_code = str(getattr(exc, "code", "RUNTIME_UNAVAILABLE"))[:64]
            if is_engine_unavailable(error_code):
                RUNTIME_ENGINE_UNAVAILABLE_TOTAL.labels(driver=driver).inc()
            logger.error(
                "runtime inventory unavailable",
                extra={
                    "trace_id": trace_id,
                    "resource_ref": config.public_id,
                    "error_code": error_code,
                    "result": "UNAVAILABLE",
                },
            )

    db_external_ids = set(
        ProvisioningInstance.objects.exclude(external_id__isnull=True).values_list(
            "runtime_adapter__public_id", "external_id"
        )
    )
    inventory_external_ids = {
        (str(item.metadata.get("adapter_id", "")), item.external_id) for item in runtime_items
    }
    runtime_orphans = sum(
        1
        for item in runtime_items
        if (str(item.metadata.get("adapter_id", "")), item.external_id) not in db_external_ids
    )
    missing_runtime = sum(
        1
        for instance in ProvisioningInstance.objects.exclude(
            status=ProvisioningInstance.Status.DESTROYED
        ).exclude(external_id__isnull=True)
        if (instance.runtime_adapter.public_id, instance.external_id) not in inventory_external_ids
    )
    orphan_judges = 0
    orphan_volumes = 0
    for item in transient_items:
        kind = str(item.metadata.get("kind", "")).casefold()
        if kind == "judge":
            judge_id = str(item.metadata.get("judge_id") or item.external_id)
            if not AutoCheckRun.objects.filter(
                public_id=judge_id,
                status__in=(AutoCheckRun.Status.QUEUED, AutoCheckRun.Status.RUNNING),
            ).exists():
                orphan_judges += 1
        elif kind == "volume":
            task_id = str(item.metadata.get("task_id", ""))
            if not ProvisioningInstance.objects.filter(task__public_id=task_id).exclude(
                status=ProvisioningInstance.Status.DESTROYED
            ).exists():
                orphan_volumes += 1

    counts: dict[tuple[str, str, str], int] = {}
    for item in [*runtime_items, *transient_items]:
        key = (
            str(item.metadata.get("driver", "UNKNOWN")),
            str(item.metadata.get("kind", "runtime")),
            str(item.status),
        )
        counts[key] = counts.get(key, 0) + 1
    RUNTIME_INVENTORY.clear()
    for (driver, kind, status), value in counts.items():
        RUNTIME_INVENTORY.labels(driver=driver, kind=kind, status=status).set(value)
    RUNTIME_ENGINE_HEALTH.clear()
    for driver_health in drivers:
        RUNTIME_ENGINE_HEALTH.labels(driver=driver_health["driver"]).set(
            1 if driver_health["status"] == "HEALTHY" else 0
        )
    RUNTIME_ORPHAN_RESOURCES.clear()
    for kind, value in (
        ("runtime", runtime_orphans),
        ("judge", orphan_judges),
        ("volume", orphan_volumes),
    ):
        RUNTIME_ORPHAN_RESOURCES.labels(kind=kind).set(value)
    unavailable = any(item["status"] == "UNAVAILABLE" for item in drivers)
    logger.info(
        "runtime inventory reconciled",
        extra={
            "trace_id": trace_id,
            "result": "UNAVAILABLE" if unavailable else "SUCCEEDED",
            "runtime_count": len(runtime_items),
            "transient_count": len(transient_items),
            "orphan_runtime_count": runtime_orphans,
            "orphan_judge_count": orphan_judges,
            "orphan_volume_count": orphan_volumes,
        },
    )

    return {
        "status": (
            "UNAVAILABLE"
            if unavailable
            else (
                "HEALTHY"
                if drivers and all(item["status"] == "HEALTHY" for item in drivers)
                else "DEGRADED"
            )
        ),
        "drivers": drivers,
        "inventory": {"runtime": len(runtime_items), "transient": len(transient_items)},
        "orphans": {"runtime": runtime_orphans, "judge": orphan_judges, "volume": orphan_volumes},
        "missing_runtime": missing_runtime,
    }


def destroy_task_instance(
    *,
    task_id: str,
    idempotency_key: str,
    context: Any,
    expected_version: int | None = None,
) -> ProvisioningInstance | None:
    """Destroy through the runtime adapter, verify absence, then close DB/quota facts."""

    def release_latest_reservation() -> None:
        job = (
            ProvisioningJob.objects.select_related("reservation")
            .filter(task__public_id=task_id)
            .order_by("-attempt_no")
            .first()
        )
        if job is not None:
            _release_reservation(
                reservation_id=job.reservation.public_id,
                reason="runtime destroyed",
                context=ActorContext(
                    actor_ref=str(getattr(context, "actor_ref", "worker")),
                    portal=str(getattr(context, "portal", "WORKER")),
                    trace_id=_trace(context),
                ),
            )

    with transaction.atomic():
        instance = (
            ProvisioningInstance.objects.select_for_update()
            .select_related("task", "course", "runtime_adapter")
            .filter(task__public_id=task_id)
            .first()
        )
        if instance is None:
            release_latest_reservation()
            return None
        if expected_version is not None and instance.row_version != expected_version:
            from apps.core.errors import RowVersionConflict

            raise RowVersionConflict(
                detail={
                    "expected_row_version": expected_version,
                    "actual_row_version": instance.row_version,
                }
            )
        if instance.status == ProvisioningInstance.Status.DESTROYED:
            release_latest_reservation()
            return instance
        if instance.status != ProvisioningInstance.Status.DESTROYING:
            instance = compare_and_swap(
                ProvisioningInstance,
                pk=instance.pk,
                expected_version=instance.row_version,
                changes={"status": ProvisioningInstance.Status.DESTROYING, "endpoint": ""},
            )
        external_id = instance.external_id or ""
        driver = instance.runtime_adapter.driver

    adapter = _runtime_adapter_for_row(
        driver=driver,
        config_ref=instance.runtime_adapter.config_ref,
        code=instance.runtime_adapter.code,
    )
    if external_id:
        # Capture the task-owned Volume before the adapter removes the
        # container and its managed Volume.  FakeRuntime has no storage job.
        from apps.workspaces.storage import finalize_workspace_before_destroy

        finalize_workspace_before_destroy(task_id=task_id, context=context)
        adapter.destroy(external_id, idempotency_key)
        if adapter.status(external_id) != "ABSENT":
            raise RuntimeError("RUNTIME_DESTROY_NOT_CONFIRMED")

    with transaction.atomic():
        current = (
            ProvisioningInstance.objects.select_for_update()
            .select_related("task", "course")
            .get(pk=instance.pk)
        )
        if current.status != ProvisioningInstance.Status.DESTROYED:
            current = compare_and_swap(
                ProvisioningInstance,
                pk=current.pk,
                expected_version=current.row_version,
                changes={
                    "status": ProvisioningInstance.Status.DESTROYED,
                    "endpoint": "",
                    "destroyed_at": timezone.now(),
                },
            )
            _audit(
                context=context,
                actor=None,
                action="provisioning.instance.destroy",
                target_type="provisioning_instance",
                target_ref=current.public_id,
                course_ref=current.course.public_id,
                before={"status": instance.status},
                after={"status": current.status, "external_absent": True},
            )
            _emit(
                event_type=events.INSTANCE_DESTROYED,
                aggregate_type="provisioning_instance",
                aggregate_ref=current.public_id,
                payload={
                    "instance_id": current.public_id,
                    "task_id": current.task.public_id,
                    "status": current.status,
                },
                context=context,
            )
        release_latest_reservation()
        return current
