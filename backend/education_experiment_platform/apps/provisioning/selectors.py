from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.experiments.models import ExperimentTask

from .models import ProvisioningInstance, ProvisioningJob


def job_for_user(*, actor: User, task_id: str) -> ProvisioningJob:
    job = (
        ProvisioningJob.objects.select_related(
            "task", "course", "reservation", "failure_record", "compensation_task"
        )
        .prefetch_related("stage_events")
        .filter(task__public_id=task_id, task__student=actor)
        .order_by("-attempt_no", "-created_at")
        .first()
    )
    if job is None:
        raise ResourceNotFound()
    return job


def jobs_for_task(task: ExperimentTask) -> QuerySet[ProvisioningJob]:
    return (
        ProvisioningJob.objects.select_related("reservation", "failure_record", "compensation_task")
        .prefetch_related("stage_events")
        .filter(task=task)
        .order_by("-attempt_no", "-created_at")
    )


def instance_for_task(task: ExperimentTask) -> ProvisioningInstance | None:
    return (
        ProvisioningInstance.objects.select_related("runtime_adapter", "image", "resource_profile")
        .filter(task=task)
        .first()
    )


def active_job_for_task(task: ExperimentTask) -> ProvisioningJob | None:
    return (
        ProvisioningJob.objects.select_for_update()
        .filter(
            task=task,
            status__in=(
                ProvisioningJob.Status.QUEUED,
                ProvisioningJob.Status.RUNNING,
                ProvisioningJob.Status.RETRY,
            ),
        )
        .order_by("-attempt_no")
        .first()
    )
