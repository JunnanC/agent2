"""Per-experiment grade publication and a stable contract for course analytics."""

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.audit import append_audit
from apps.core.concurrency import compare_and_swap
from apps.core.errors import StateConflict
from apps.courses.models import Enrollment
from apps.reports.models import ReportSubmission

from .assessment_parts import part_scores
from .models import (
    AssessmentRun,
    ExperimentTask,
    PartRedo,
    PublishedExperimentGrade,
    TaskPublication,
)


def _snapshot(task: ExperimentTask) -> dict[str, Any]:
    parts = part_scores(task)
    rows = []
    for part in parts:
        status = part["status"]
        rows.append({
            "kind": part["kind"],
            "score": str(Decimal(part["score"] or "0").quantize(Decimal("0.01"))),
            "max_score": part["max_score"],
            "status": "NOT_SUBMITTED" if status == "RETURNED" else status,
        })
    return {
        "parts": rows,
        "should_do": task.enrollment.activated_at is None
        or task.enrollment.activated_at < task.publication.window_end,
        "status": "NOT_SUBMITTED"
        if all(row["status"] == "NOT_SUBMITTED" for row in rows)
        else "SUBMITTED"
        if all(row["status"] in {"SUBMITTED", "GRADED"} for row in rows)
        else "PARTIAL",
        "score": str(sum((Decimal(row["score"]) for row in rows), Decimal("0.00"))),
        "max_score": str(sum((Decimal(row["max_score"]) for row in rows), Decimal("0.00"))),
    }


def release_status(publication: TaskPublication) -> dict[str, Any]:
    tasks = ExperimentTask.objects.filter(publication=publication)
    return {
        "publication_id": publication.public_id,
        "deadline": publication.window_end,
        "grades_published_at": publication.grades_published_at,
        "pending_reports": ReportSubmission.objects.filter(
            task__in=tasks,
            status="SUBMITTED",
        )
        .exclude(review_status="READY")
        .count(),
        "pending_runs": AssessmentRun.objects.filter(
            task__in=tasks,
            mode=AssessmentRun.Mode.FINAL,
        )
        .exclude(status="COMPLETED")
        .count(),
        "open_redos": PartRedo.objects.filter(
            task__in=tasks, redo_until__gt=timezone.now()
        ).count(),
    }


@transaction.atomic
def release_grades(
    publication: TaskPublication, *, actor: User, trace_id: str = "",
) -> dict[str, Any]:
    publication = TaskPublication.objects.select_for_update().get(pk=publication.pk)
    if not publication.direct_assessment:
        raise StateConflict(detail={"publication": "unsupported"})
    if publication.grades_published_at:
        return release_status(publication)
    now = timezone.now()
    if publication.status not in {"PUBLISHED", "CLOSED"} or now < publication.window_end:
        raise StateConflict(detail={"publication": "deadline_not_reached_or_unpublished"})
    status = release_status(publication)
    blockers = {name: status[name] for name in ("pending_reports", "pending_runs", "open_redos")}
    if any(blockers.values()):
        raise StateConflict(detail=blockers)

    tasks = list(
        ExperimentTask.objects.filter(publication=publication)
        .select_related("publication", "enrollment")
        .order_by("pk"),
    )
    task_ids = [task.pk for task in tasks]
    signer = publication.course.owner
    for report in ReportSubmission.objects.filter(task_id__in=task_ids, status="SUBMITTED"):
        suggestion = report.ai_review
        compare_and_swap(
            ReportSubmission,
            pk=report.pk,
            expected_version=report.row_version,
            changes={
                "status": ReportSubmission.Status.GRADED,
                "score": Decimal(suggestion["score"]),
                "feedback": suggestion["feedback"],
                "comments": suggestion["comments"],
                "graded_by": actor,
            },
        )
    PublishedExperimentGrade.objects.bulk_create([
        PublishedExperimentGrade(task=task, result=_snapshot(task)) for task in tasks
    ])
    updated = compare_and_swap(
        TaskPublication,
        pk=publication.pk,
        expected_version=publication.row_version,
        changes={
            "grades_published_at": now,
            "grade_signer": signer.display_name,
            "status": TaskPublication.Status.CLOSED,
            "closed_by": actor,
            "closed_at": publication.closed_at or now,
        },
    )
    append_audit(
        actor_ref=actor.public_id, actor_portal="TEACHING", actor_context={},
        action="experiment.grades.publish", target_type="task_publication",
        target_ref=publication.public_id, course_ref=publication.course.public_id,
        after={"released_at": now.isoformat(), "result_count": len(tasks)},
        trace_id=trace_id, result="SUCCEEDED",
    )
    return release_status(updated)


def published_results(publication: TaskPublication) -> list[dict[str, Any]]:
    if not publication.grades_published_at:
        return []
    source = (
        PublishedExperimentGrade.objects.filter(task__publication=publication)
        .select_related(
            "task__student",
            "task__enrollment",
        )
        .order_by("task_id")
    )
    prefix = {
        "course_id": publication.course.public_id,
        "publication_id": publication.public_id,
        "deadline": publication.window_end,
        "grades_published_at": publication.grades_published_at,
    }
    rows: dict[int, dict[str, Any]] = {}
    for grade in source:
        task = grade.task
        rows[task.student_id] = {
            **prefix,
            "task_id": task.public_id,
            "student_id": task.student.public_id,
            "enrollment_id": task.enrollment.public_id,
            **grade.result,
        }
    for enrollment in Enrollment.objects.filter(
        course=publication.course,
        status="ACTIVE",
    ).select_related("student"):
        if enrollment.student_id not in rows:
            eligible = bool(
                enrollment.activated_at and enrollment.activated_at < publication.window_end,
            )
            empty_parts = (
                [
                    {"kind": kind, "score": "0.00", "max_score": maximum, "status": "NOT_SUBMITTED"}
                    for kind, maximum in publication.experiment_spec["part_maxima"].items()
                    if Decimal(maximum) > 0
                ]
                if eligible
                else []
            )
            rows[enrollment.student_id] = {
                **prefix,
                "task_id": None,
                "student_id": enrollment.student.public_id,
                "enrollment_id": enrollment.public_id,
                "should_do": eligible,
                "status": "NOT_SUBMITTED" if eligible else "NOT_ASSIGNED",
                "score": "0.00" if eligible else None,
                "parts": empty_parts,
                "max_score": str(
                    sum(
                        (Decimal(part["max_score"]) for part in empty_parts),
                        Decimal("0.00"),
                    )
                )
                if eligible
                else None,
            }
    return list(rows.values())
