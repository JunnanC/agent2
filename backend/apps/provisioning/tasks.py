from typing import Any

from celery import shared_task

from .services import (
    compensate_provisioning,
    execute_provisioning_job,
    warmup_publication_image,
)


@shared_task(bind=True, max_retries=5, queue="q_provision", acks_late=True)
def destroy_student_runtime(self: Any, runtime_id: str, actor_ref: str, trace_id: str = "") -> str:
    from apps.courses.services import ActorContext

    from .models import ProvisioningInstance
    from .services import destroy_task_instance

    instance = ProvisioningInstance.objects.select_related("task").get(public_id=runtime_id)
    try:
        destroy_task_instance(
            task_id=instance.task.public_id, idempotency_key=f"student-stop:{runtime_id}",
            context=ActorContext(actor_ref, "USER", trace_id),
        )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(30 * (2 ** self.request.retries), 300)) from exc
    return runtime_id


@shared_task(bind=True, max_retries=2, queue="q_provision", acks_late=True)
def run_provisioning_job(self: Any, job_id: str, trace_id: str = "") -> str:
    execute_provisioning_job(job_id=job_id, trace_id=trace_id)
    return job_id


@shared_task(bind=True, max_retries=0, queue="q_provision", acks_late=True)
def warmup_publication_image_task(self: Any, publication_id: str, trace_id: str = "") -> str:
    return warmup_publication_image(publication_id=publication_id, trace_id=trace_id)


@shared_task(bind=True, max_retries=5, queue="q_compensate", acks_late=True)
def run_provisioning_compensation(self: Any, compensation_id: int) -> int:
    from apps.core.models import CompensationTask

    task = CompensationTask.objects.get(pk=compensation_id)
    compensate_provisioning(task)
    return int(task.pk)
