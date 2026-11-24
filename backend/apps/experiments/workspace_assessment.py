"""Student workspace and single-question attempts."""

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict, StateConflict
from apps.workspaces.code_snapshots import create_code_snapshot
from apps.workspaces.models import StudentWorkspace

from .assessment import _draft, _question, _task
from .assessment_parts import (
    can_start_session,
    part_deadline,
    part_open,
    questions_for,
    require_part_open,
    sync_workspace_progress,
)
from .models import (
    AssessmentRun,
    AssessmentSession,
    ExperimentTask,
    ProgrammingSubmission,
    TaskPublication,
)


def _workspace(task: ExperimentTask) -> StudentWorkspace | None:
    return StudentWorkspace.objects.filter(task=task).first()


def workspace_data(task: ExperimentTask) -> dict[str, Any]:
    workspace = _workspace(task)
    has_programs = questions_for(task).filter(task_type="PROGRAMMING").exists()
    expires_at = part_deadline(task, "PROGRAMMING")
    active = part_open(task, expires_at)
    status = "NOT_REQUIRED"
    if has_programs:
        status = "PENDING" if active else "EXPIRED"
        if active and workspace and workspace.expires_at == expires_at:
            status = workspace.status
    return {"status": status, "expires_at": expires_at}


def ensure_student_workspace(task: ExperimentTask) -> StudentWorkspace | None:
    expires_at = part_deadline(task, "PROGRAMMING")
    if (
        not part_open(task, expires_at)
        or not questions_for(task)
        .filter(
            task_type="PROGRAMMING",
        )
        .exists()
    ):
        return None
    workspace, _ = StudentWorkspace.objects.get_or_create(
        task=task,
        defaults={"expires_at": expires_at},
    )
    if workspace.expires_at != expires_at:
        workspace = StudentWorkspace.objects.select_for_update().get(pk=workspace.pk)
        # A different deadline names a new generation; the old labels allow cleanup.
        return compare_and_swap(
            StudentWorkspace,
            pk=workspace.pk,
            expected_version=workspace.row_version,
            changes={
                "expires_at": expires_at,
                "status": StudentWorkspace.Status.PENDING,
                "synced_at": None,
            },
        )
    return workspace


@transaction.atomic
def enter_workspace(*, actor: User, task_id: str) -> dict[str, Any]:
    from apps.workspaces.tasks import sync_student_workspace

    task = _task(actor, task_id)
    publication = TaskPublication.objects.select_for_update().get(pk=task.publication_id)
    task = ExperimentTask.objects.select_for_update().get(pk=task.pk)
    task.publication = publication
    if publication.direct_assessment and not part_open(task, publication.window_end):
        return workspace_data(task)
    if not can_start_session(task):
        raise ResourceNotFound()
    _, created = AssessmentSession.objects.get_or_create(task=task)
    if created and part_open(task, task.publication.window_end):
        sync_workspace_progress(task)
    workspace = ensure_student_workspace(task)
    if workspace:
        transaction.on_commit(lambda: sync_student_workspace.delay(workspace.pk), robust=True)
    return workspace_data(task)


@transaction.atomic
def select_question(*, actor: User, task_id: str, question_id: str) -> None:
    task = _task(actor, task_id, write=True, part="PROGRAMMING")
    question = _question(task, question_id)
    if (
        question.task_type != "PROGRAMMING"
        or not AssessmentSession.objects.filter(
            task=task,
        ).exists()
    ):
        raise ResourceNotFound()
    AssessmentSession.objects.filter(task=task).update(current_question=question)


@transaction.atomic
def request_attempt(
    *,
    actor: User,
    task_id: str,
    question_id: str,
    language: str,
    expected_version: int,
    stdin: str,
    mode: str,
) -> AssessmentRun:
    from .assessment_workers import run_assessment_job

    task = _task(actor, task_id, write=True, part="PROGRAMMING")
    require_part_open(task, "PROGRAMMING")
    question = _question(task, question_id)
    if (
        question.task_type != "PROGRAMMING"
        or not AssessmentSession.objects.filter(
            task=task,
        ).exists()
    ):
        raise ResourceNotFound()
    if ProgrammingSubmission.objects.filter(task=task, question=question).exists():
        raise StateConflict(detail={"question": "already_submitted"})
    if len(stdin.encode()) > 1048576:
        raise StateConflict(detail={"stdin": "too_large"})
    draft = _draft(task, question, language)
    if draft.row_version != expected_version:
        raise RowVersionConflict()
    ensure_student_workspace(task)
    run = AssessmentRun.objects.create(
        task=task,
        question=question,
        mode=mode,
        stdin=stdin,
        draft_version=draft.row_version,
        snapshot=create_code_snapshot(task=task, question=question, draft=draft),
    )
    transaction.on_commit(lambda: run_assessment_job.delay(pk=run.pk, formal=False), robust=True)
    return run


def attempt_deadline(run: AssessmentRun, task: ExperimentTask) -> float | None:
    """An on-time final submission may finish while the teacher waits to release grades."""
    publication = task.publication
    deadline = part_deadline(task, "PROGRAMMING")
    if publication.direct_assessment and run.mode == AssessmentRun.Mode.FINAL:
        grace = deadline + timedelta(minutes=15)
        if (
            not publication.grades_published_at and task.enrollment.status == "ACTIVE"
            and task.status not in {"CANCELLED", "EXPIRED", "FAILED", "ARCHIVING"}
            and publication.status in {"PUBLISHED", "CLOSED"}
            and publication.window_start <= run.created_at < deadline
            and timezone.now() < grace
        ):
            return grace.timestamp()
        return None
    return deadline.timestamp() if part_open(task, deadline) else None


@transaction.atomic
def complete_attempt(run: AssessmentRun, *, result: dict[str, Any], all_passed: bool) -> None:
    from .assessment_workers import _finish

    publication = TaskPublication.objects.select_for_update().get(pk=run.task.publication_id)
    task = ExperimentTask.objects.select_for_update().get(pk=run.task_id)
    task.publication = publication
    current = AssessmentRun.objects.select_for_update().get(pk=run.pk)
    if current.lease_token != run.lease_token or current.status != "RUNNING":
        return
    if all_passed and attempt_deadline(current, task) is not None:
        existing = ProgrammingSubmission.objects.filter(task=task, question=run.question).first()
        if existing:
            result.update(result_status="ALREADY_SUBMITTED")
        elif _draft(task, run.question, run.snapshot.language).row_version != run.draft_version:
            result.update(result_status="DRAFT_CHANGED")
        else:
            ProgrammingSubmission.objects.create(
                task=task,
                question=run.question,
                run=run,
                code_snapshot=run.snapshot,
                case_results=result["case_results"],
            )
            ids = list(
                questions_for(task).filter(task_type="PROGRAMMING").values_list("pk", flat=True)
            )
            passed = set(
                ProgrammingSubmission.objects.filter(task=task).values_list(
                    "question_id",
                    flat=True,
                )
            )
            i = ids.index(run.question_id) + 1
            next_question = next((qid for qid in ids[i:] + ids[:i] if qid not in passed), None)
            AssessmentSession.objects.filter(task=task).update(current_question_id=next_question)
            result.update(submitted=True, next_question_id=next_question)
            sync_workspace_progress(task)
    elif all_passed:
        result.update(result_status="WINDOW_CLOSED")
    _finish(run, status="COMPLETED", **result)
