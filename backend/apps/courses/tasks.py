from typing import Any

from celery import shared_task

from apps.accounts.models import User

from .content_services import execute_copy_job, execute_import, precheck_import_job
from .models import EnrollmentImportJob, TimetableImportJob
from .services import ActorContext
from .timetable_services import execute_timetable_import


@shared_task(bind=True, max_retries=3, queue="q_content")
def run_copy_job(self: Any, job_id: str, actor_id: int, trace_id: str = "") -> str:
    try:
        actor = User.objects.get(pk=actor_id)
        job = execute_copy_job(
            job_id=job_id,
            actor=actor,
            context=ActorContext(actor.public_id, "TEACHING", trace_id),
        )
        return job.public_id
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@shared_task(bind=True, max_retries=3, queue="q_content")
def run_enrollment_import_precheck(
    self: Any, job_id: str, actor_id: int, trace_id: str = ""
) -> str:
    try:
        actor = User.objects.get(pk=actor_id)
        job = precheck_import_job(
            job_id=job_id,
            actor=actor,
            context=ActorContext(actor.public_id, "TEACHING", trace_id),
        )
        return job.public_id
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            EnrollmentImportJob.objects.filter(public_id=job_id).update(
                status=EnrollmentImportJob.Status.FAILED,
                summary={"error": "PRECHECK_FAILED"},
            )
            raise
        raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@shared_task(bind=True, max_retries=3, queue="q_content")
def run_enrollment_import(self: Any, job_id: str, actor_id: int, trace_id: str = "") -> str:
    try:
        actor = User.objects.get(pk=actor_id)
        job = execute_import(
            job_id=job_id,
            actor=actor,
            context=ActorContext(actor.public_id, "TEACHING", trace_id),
        )
        return job.public_id
    except Exception as exc:
        raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@shared_task(bind=True, max_retries=2, acks_late=True, queue="q_content")
def run_timetable_import(
    self: Any, job_id: str, actor_id: int, kind: str, trace_id: str = ""
) -> str:
    try:
        actor = User.objects.get(pk=actor_id)
        job = execute_timetable_import(
            job_id=job_id,
            actor=actor,
            kind=kind,
            context=ActorContext(
                actor.public_id,
                "TEACHING" if kind == TimetableImportJob.Kind.TEACHER else "USER",
                trace_id,
            ),
        )
        return job.public_id
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            TimetableImportJob.objects.filter(public_id=job_id).update(
                status=TimetableImportJob.Status.FAILED,
                summary={"error": "IMPORT_FAILED"},
            )
            raise
        raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
