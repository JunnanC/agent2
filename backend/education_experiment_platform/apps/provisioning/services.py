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
from apps.governance.models import QuotaReservation
from apps.governance.services import release_reservation, reserve_quota

from . import events
from .adapters import FakeRuntimeFailure, runtime_for_driver
from .errors import ProvisioningConfigurationError, ProvisioningStateConflict
from .metrics import PROVISIONING_JOBS_TOTAL, PROVISIONING_STAGE_TOTAL
from .models import ProvisioningInstance, ProvisioningJob, ProvisioningStageEvent, public_id_field
from .ports import RuntimeInventoryItem, RuntimeSpec
from .selectors import active_job_for_task, jobs_for_task

STAGES: tuple[str, ...] = tuple(ProvisioningJob.Stage.values)
ACTIVE_JOB_STATUSES = (
    ProvisioningJob.Status.QUEUED,
    ProvisioningJob.Status.RUNNING,
    ProvisioningJob.Status.RETRY,
)


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


def _runtime_spec(task: ExperimentTask) -> RuntimeSpec:
    template = task.template_version
    profile = template.resource_profile
    image = template.image
    return RuntimeSpec(
        task_id=task.public_id,
        course_id=task.course.public_id,
        student_id=task.student.public_id,
        runtime_type=task.runtime_type,
        image_digest=image.digest,
        resource_profile_id=profile.public_id,
        cpu_millicores=profile.cpu_millicores,
        memory_mb=profile.memory_mb,
        disk_gb=profile.disk_gb,
        network_policy=template.network_policy,
        workspace_capabilities=template.workspace_capabilities,
    )


def _reservation_values(task: ExperimentTask) -> dict[str, int]:
    profile = task.template_version.resource_profile
    return {
        "instance_count": 1,
        "start_count": 1,
        "cpu_millicores": profile.cpu_millicores,
        "memory_mb": profile.memory_mb,
        "disk_gb": profile.disk_gb,
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
        resource_profile_id=task.template_version.resource_profile.public_id,
        values=_reservation_values(task),
        expires_at=None,
        context=context,
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
            "runtime_adapter": task.template_version.runtime_adapter,
            "image": task.template_version.image,
            "resource_profile": task.template_version.resource_profile,
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
    adapter_row = task.template_version.runtime_adapter
    if adapter_row.status != "ENABLED" or adapter_row.health_status in ("DEGRADED", "UNAVAILABLE"):
        raise ProvisioningStateConflict(detail={"runtime_adapter": adapter_row.public_id})
    if (
        task.template_version.image.scan_status != "CLEAN"
        or task.template_version.image.approval_status != "APPROVED"
    ):
        raise ProvisioningConfigurationError(detail={"image": "not_approved_or_clean"})
    if task.template_version.resource_profile.status != "ACTIVE":
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
    release_reservation(
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


def _stage_finished(
    event: ProvisioningStageEvent, *, status: str, detail: dict[str, Any], error_code: str = ""
) -> None:
    ProvisioningStageEvent.objects.create(
        job=event.job,
        stage=event.stage,
        status=status,
        attempt_no=event.attempt_no,
        detail_masked=detail,
        error_code=error_code,
        trace_id=event.trace_id,
        started_at=event.started_at,
        completed_at=timezone.now(),
    )
    PROVISIONING_STAGE_TOTAL.labels(stage=event.stage, status=status).inc()


def _job_context(job: ProvisioningJob) -> ActorContext:
    return ActorContext(actor_ref="worker", portal="WORKER", trace_id=job.trace_id)


def _error_code(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, FakeRuntimeFailure):
        return exc.code, True
    if isinstance(exc, TimeoutError):
        return str(exc) or "RUNTIME_TIMEOUT", True
    if isinstance(exc, ProvisioningConfigurationError):
        return exc.code, False
    return "PROVISIONING_STAGE_FAILED", True


def _failure_detail(exc: Exception, error_code: str) -> dict[str, Any]:
    return {"error_code": error_code, "retryable": True, "detail": str(exc)[:255]}


def _mark_failed(job: ProvisioningJob, exc: Exception, context: ActorContext) -> None:
    error_code, retryable = _error_code(exc)
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
        release_reservation(
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


@transaction.atomic
def execute_provisioning_job(*, job_id: str, trace_id: str = "") -> ProvisioningJob:
    job = (
        ProvisioningJob.objects.select_for_update()
        .select_related(
            "task__course",
            "task__student",
            "task__template_version__runtime_adapter",
            "task__template_version__image",
            "task__template_version__resource_profile",
            "reservation",
        )
        .get(public_id=job_id)
    )
    if job.status not in (ProvisioningJob.Status.QUEUED, ProvisioningJob.Status.RETRY):
        return job
    context = _job_context(job)
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
    spec = _runtime_spec(job.task)
    try:
        adapter = runtime_for_driver(job.task.template_version.runtime_adapter.driver)
        result = None
        for stage in STAGES:
            event = _stage_started(job, stage, context)
            try:
                if stage == ProvisioningJob.Stage.QUOTA_CHECK:
                    result = adapter.preflight(spec)
                elif stage == ProvisioningJob.Stage.IMAGE_PREPARE:
                    if (
                        job.task.template_version.image.approval_status != "APPROVED"
                        or job.task.template_version.image.scan_status != "CLEAN"
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
                    event, status=ProvisioningStageEvent.Status.PASSED, detail={"stage": stage}
                )
                _emit(
                    event_type=events.STAGE_CHANGED,
                    aggregate_type="provisioning_job",
                    aggregate_ref=job.public_id,
                    payload={
                        "job_id": job.public_id,
                        "task_id": job.task.public_id,
                        "stage": stage,
                        "status": "PASSED",
                    },
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
                    error_code=error_code,
                )
                raise
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
            expected_version=ProvisioningJob.objects.get(pk=job.pk).row_version,
            changes={
                "status": ProvisioningJob.Status.PASSED,
                "current_stage": ProvisioningJob.Stage.WORKSPACE_READY,
                "completed_at": timezone.now(),
            },
        )
        PROVISIONING_JOBS_TOTAL.labels(
            status=changed.status, runtime_type=job.task.runtime_type
        ).inc()
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


@transaction.atomic
def compensate_provisioning(task: CompensationTask) -> None:
    job = (
        ProvisioningJob.objects.select_for_update()
        .select_related("reservation", "task")
        .get(public_id=task.subject_ref)
    )
    instance = ProvisioningInstance.objects.select_for_update().filter(task=job.task).first()
    context = ActorContext(actor_ref="compensation", portal="WORKER", trace_id=task.trace_id)
    if instance is not None and instance.external_id:
        adapter = runtime_for_driver(instance.runtime_adapter.driver)
        adapter.destroy(instance.external_id, f"destroy:{job.public_id}")
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
    release_reservation(
        reservation_id=job.reservation.public_id,
        reason="provisioning compensation",
        context=context,
    )


def runtime_inventory(*, driver: str = "FAKE") -> list[RuntimeInventoryItem]:
    return runtime_for_driver(driver).inventory()


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
            release_reservation(
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

    adapter = runtime_for_driver(driver)
    if external_id:
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
