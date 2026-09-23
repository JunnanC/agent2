from typing import Any

from celery import shared_task

from .services import compensate_provisioning, execute_provisioning_job


@shared_task(bind=True, max_retries=2, queue="q_provision", acks_late=True)
def run_provisioning_job(self: Any, job_id: str, trace_id: str = "") -> str:
    execute_provisioning_job(job_id=job_id, trace_id=trace_id)
    return job_id


@shared_task(bind=True, max_retries=5, queue="q_compensate", acks_late=True)
def run_provisioning_compensation(self: Any, compensation_id: int) -> int:
    from apps.core.models import CompensationTask

    task = CompensationTask.objects.get(pk=compensation_id)
    compensate_provisioning(task)
    return int(task.pk)
