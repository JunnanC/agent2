"""Independent assessment deadlines and scores for the workspace workflow."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, StateConflict
from apps.labtemplates.questions import CHOICE_TYPES, QUESTION_TYPES

from .models import (
    AssessmentSection,
    AssessmentSession,
    ExperimentTask,
    PartRedo,
    ProgrammingSubmission,
    PublicationTask,
    TaskPublication,
)

INACTIVE_TASKS = {"CANCELLED", "EXPIRED", "FAILED", "ARCHIVING"}


def questions_for(task: ExperimentTask) -> Any:
    return PublicationTask.objects.filter(
        publication_chapter__publication_id=task.publication_id,
        task_type__in=QUESTION_TYPES,
    ).order_by("publication_chapter__sort_order", "sort_order", "pk")


def part_deadline(task: ExperimentTask, part: str, redo: PartRedo | None = None) -> datetime:
    redo = redo or PartRedo.objects.filter(task=task, part=part).first()
    return redo.redo_until if redo else task.publication.window_end


def part_open(task: ExperimentTask, deadline: datetime) -> bool:
    publication = task.publication
    return (
        task.status not in INACTIVE_TASKS
        and not publication.grades_published_at
        and task.enrollment.status == "ACTIVE"
        and publication.window_start <= timezone.now() < deadline
        and (
            publication.status == "PUBLISHED"
            or publication.status == "CLOSED"
            and deadline > publication.window_end
        )
    )


def require_part_open(task: ExperimentTask, part: str) -> datetime:
    deadline = part_deadline(task, part)
    if not part_open(task, deadline):
        raise StateConflict(detail={"window": "closed"})
    return deadline


def session_for(task: ExperimentTask) -> AssessmentSession | None:
    return AssessmentSession.objects.filter(task=task).first()


def can_start_session(task: ExperimentTask) -> bool:
    return (
        (questions_for(task).exists() or task.publication.direct_assessment
         and task.publication.report_required)
        and not AssessmentSection.objects.filter(
            task=task,
            kind="PROGRAMMING",
            current_submission__isnull=False,
        ).exists()
    )


def percentage(passed: int, total: int) -> Decimal:
    return (Decimal(passed * 100) / total).quantize(Decimal("0.01"))


def part_scores(task: ExperimentTask, *, student: bool = False) -> list[dict[str, Any]]:
    from apps.reports.models import ReportSubmission

    kinds = list(questions_for(task).values_list("task_type", flat=True))
    choices = sum(kind in CHOICE_TYPES for kind in kinds)
    programs = kinds.count("PROGRAMMING")
    redos = {row.part: row for row in PartRedo.objects.filter(task=task)}
    parts: list[dict[str, Any]] = []
    maxima = task.publication.experiment_spec.get("part_maxima", {})

    def add(part: str, status: str, score: Decimal | None) -> None:
        redo = redos.get(part)
        full_score = Decimal(maxima.get(part, "100"))
        maximum = full_score
        if redo or task.publication.retake_of_id:
            maximum = (full_score * Decimal("0.60")).quantize(Decimal("0.01"))
        deadline = redo.redo_until if redo else task.publication.window_end
        if score is None and timezone.now() >= deadline and status == "NOT_SUBMITTED":
            score = Decimal("0")
        parts.append({
            "kind": part,
            "status": status,
            "score": str(min(score, Decimal(maximum)).quantize(Decimal("0.01")))
            if score is not None
            else None,
            "max_score": str(full_score),
            "score_cap": float(maximum),
            "deadline": deadline,
            "redo_until": redo.redo_until if redo else None,
            "editable": part_open(task, deadline) and (part == "REPORT" or status != "SUBMITTED"),
        })

    if choices:
        section = (
            AssessmentSection.objects.filter(task=task, kind="CHOICE")
            .select_related(
                "current_submission",
            )
            .first()
        )
        status = section.status if section else "NOT_SUBMITTED"
        score = None
        if section and section.current_submission_id and status == "SUBMITTED":
            correct = sum(
                set(answer.selected_option_ids)
                == set(answer.question.marking_spec["correct_option_ids"])
                for answer in section.current_submission.answers.select_related("question")
            )
            score = Decimal(correct) * Decimal(maxima.get("CHOICE", "100")) / choices
        add("CHOICE", status, score)
    if programs:
        passed = ProgrammingSubmission.objects.filter(task=task).count()
        status = (
            "SUBMITTED"
            if passed == programs
            else "RETURNED"
            if "PROGRAMMING" in redos
            else ("IN_PROGRESS" if passed else "NOT_SUBMITTED")
        )
        scaled = Decimal(passed) * Decimal(maxima.get("PROGRAMMING", "100")) / programs
        add("PROGRAMMING", status, scaled)
        parts[-1].update(passed_questions=passed, total_questions=programs)
    if task.publication.report_required or task.publication.report_template_asset_id:
        report = ReportSubmission.objects.filter(task=task).first()
        status = report.status if report else "RETURNED" if "REPORT" in redos else "NOT_SUBMITTED"
        add("REPORT", status, report.score if report else None)
    if student and task.publication.direct_assessment:
        if not task.publication.grades_published_at:
            return [
                {**part, "score": None,
                 "status": "SUBMITTED" if part["status"] == "GRADED" else part["status"]}
                for part in parts
            ]
        from .models import PublishedExperimentGrade

        released = PublishedExperimentGrade.objects.filter(task=task).first()
        if released is not None:
            scores = {part["kind"]: part for part in released.result["parts"]}
            return [{**part, **scores.get(part["kind"], {}), "editable": False} for part in parts]
    return parts


def sync_workspace_progress(task: ExperimentTask) -> None:
    if task.status in INACTIVE_TASKS:
        return
    parts = {part["kind"]: part for part in part_scores(task)}
    progress_part = parts.get("PROGRAMMING") or parts.get("CHOICE")
    if progress_part is None:
        return
    complete = progress_part["status"] == "SUBMITTED"
    progress = 100 if complete else 0
    if progress_part["kind"] == "PROGRAMMING":
        progress = round(
            percentage(
                progress_part["passed_questions"],
                progress_part["total_questions"],
            )
        )
    now = timezone.now()
    compare_and_swap(
        ExperimentTask,
        pk=task.pk,
        expected_version=task.row_version,
        changes={
            "status": "COMPLETED" if complete else "IN_PROGRESS",
            "progress": progress,
            "started_at": task.started_at or now,
            "completed_at": (task.completed_at or now) if complete else None,
            "submitted_at": (task.submitted_at or now) if complete else None,
        },
    )


@transaction.atomic
def grant_redo(
    *,
    task: ExperimentTask,
    actor: User,
    part: str,
    redo_until: datetime,
    reason: str,
) -> PartRedo:
    from apps.reports.models import ReportSubmission

    publication = TaskPublication.objects.select_for_update().get(pk=task.publication_id)
    task = ExperimentTask.objects.select_for_update().get(pk=task.pk)
    task.publication = publication
    if not session_for(task):
        if not can_start_session(task):
            raise ResourceNotFound()
        AssessmentSession.objects.create(task=task)
    now = timezone.now()
    if (
        publication.grades_published_at
        or publication.status not in {"PUBLISHED", "CLOSED"}
        or task.status in INACTIVE_TASKS
    ):
        raise StateConflict(detail={"task": "not_open"})
    if now < task.publication.window_end or redo_until <= now:
        raise StateConflict(detail={"redo_until": "after_experiment_and_future_required"})
    state = next((row for row in part_scores(task) if row["kind"] == part), None)
    if state is None:
        raise ResourceNotFound()
    if part == "PROGRAMMING" and state["status"] == "SUBMITTED":
        raise StateConflict(detail={"programming": "all_questions_already_submitted"})
    fields = {"redo_until": redo_until, "granted_by": actor, "reason": reason}
    grant = PartRedo.objects.filter(task=task, part=part).first()
    if grant:
        grant = compare_and_swap(
            PartRedo, pk=grant.pk, expected_version=grant.row_version, changes=fields
        )
    else:
        grant = PartRedo.objects.create(task=task, part=part, **fields)
    if part == "CHOICE":
        section, created = AssessmentSection.objects.get_or_create(
            task=task,
            kind=part,
            defaults={"status": "RETURNED", "resubmit_until": redo_until},
        )
        if not created:
            compare_and_swap(
                AssessmentSection,
                pk=section.pk,
                expected_version=section.row_version,
                changes={"status": "RETURNED", "resubmit_until": redo_until},
            )
    elif part == "REPORT":
        report = ReportSubmission.objects.filter(task=task).first()
        if report:
            compare_and_swap(
                ReportSubmission,
                pk=report.pk,
                expected_version=report.row_version,
                changes={"status": "RETURNED", "score": None, "graded_by": None, "feedback": ""},
            )
    sync_workspace_progress(task)
    return grant
