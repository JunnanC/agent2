from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.courses.models import Course
from apps.experiments.assessment_parts import part_scores
from apps.experiments.models import ExperimentTask, TaskPublication

PARTS = {"CHOICE": "选择题", "PROGRAMMING": "编程题", "REPORT": "实验报告"}
SUGGESTIONS = {
    "CHOICE": "复习得分较低的知识点，增加低风险随堂测验。",
    "PROGRAMMING": "拆分关键编程步骤，增加基础练习和示例讲评。",
    "REPORT": "给出报告范例和提交前自查清单。",
}
ZERO = Decimal("0")


@dataclass(frozen=True)
class ReleasedExperiment:
    publication_id: str
    title: str
    deadline: datetime
    released_at: datetime


@dataclass(frozen=True)
class ReleasedResult:
    publication_id: str
    student_id: str
    student_name: str
    task_id: str | None
    joined_at: datetime | None
    expected: bool
    submission_status: str
    # Each entry is (actual score, possible score) in the original scoring scale.
    parts: dict[str, tuple[Decimal, Decimal]]


def current_released_results(
    course: Course,
) -> tuple[list[ReleasedExperiment], list[ReleasedResult], list[dict[str, str]]]:
    """Read explicit releases through the current task relations until B's snapshot lands."""
    now = timezone.now()
    publications = list(
        TaskPublication.objects.filter(
            course=course,
            retake_of__isnull=True,
            score_release_at__lte=now,
            window_end__lte=now,
            status__in=(TaskPublication.Status.PUBLISHED, TaskPublication.Status.CLOSED),
        ).order_by("window_end", "pk")
    )
    experiments = [
        ReleasedExperiment(p.public_id, p.title, p.window_end, p.score_release_at)
        for p in publications
        if p.score_release_at is not None
    ]
    tasks = (
        ExperimentTask.objects.filter(publication__in=publications)
        .exclude(status=ExperimentTask.Status.CANCELLED)
        .select_related(
            "publication",
            "enrollment",
            "student",
        )
        .order_by("pk")
    )
    awaiting: list[dict[str, str]] = []
    results: list[ReleasedResult] = []
    for task in tasks:
        if (
            task.course_id != course.pk
            or task.enrollment.course_id != course.pk
            or task.enrollment.student_id != task.student_id
            or not task.enrollment.activated_at
        ):
            awaiting.append({
                "publication_id": task.publication.public_id,
                "task_id": task.public_id,
                "reason": "ENROLLMENT_UNCONFIRMED",
            })
            continue
        parts = part_scores(task)
        if not parts or any(
            part["score"] is None and part["status"] != "NOT_SUBMITTED" for part in parts
        ):
            awaiting.append({
                "publication_id": task.publication.public_id,
                "task_id": task.public_id,
                "reason": "RELEASED_PARTS_UNCONFIRMED",
            })
            continue
        submitted_states = {"SUBMITTED", "APPROVED", "COMPLETED", "GRADED", "SCORED"}
        if all(part["status"] == "NOT_SUBMITTED" for part in parts):
            status = "NOT_SUBMITTED"
        elif all(part["status"] in submitted_states for part in parts):
            status = "SUBMITTED"
        else:
            status = "PARTIAL"
        results.append(
            ReleasedResult(
                task.publication.public_id,
                task.student.public_id,
                task.student.display_name,
                task.public_id,
                task.enrollment.activated_at,
                True,
                status,
                {
                    part["kind"]: (Decimal(part["score"] or "0"), Decimal(part["max_score"]))
                    for part in parts
                },
            )
        )
    return experiments, results, awaiting


def _percent(numerator: Decimal | int, denominator: Decimal | int) -> float | None:
    return round(float(100 * Decimal(numerator) / Decimal(denominator)), 2) if denominator else None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = len(rows)
    completed = sum(row["status"] == "SUBMITTED" for row in rows)
    points = sum((row["score"] for row in rows), ZERO)
    maximum = sum((row["max_score"] for row in rows), ZERO)
    return {
        "expected": expected,
        "completed": completed,
        "completion_rate": _percent(completed, expected),
        "score": float(points),
        "max_score": float(maximum),
        "percent": _percent(points, maximum),
    }


def analyze_released_grades(
    experiments: list[ReleasedExperiment],
    results: list[ReleasedResult],
    publication_ids: set[str],
    awaiting: list[dict[str, str]],
) -> dict[str, Any]:
    selected = {
        item.publication_id: item
        for item in experiments
        if not publication_ids or item.publication_id in publication_ids
    }
    by_experiment: dict[str, list[dict[str, Any]]] = {key: [] for key in selected}
    by_student: dict[str, list[dict[str, Any]]] = {}
    by_part = {kind: [ZERO, ZERO] for kind in PARTS}
    awaiting = [
        item for item in awaiting if not publication_ids or item.get("publication_id") in selected
    ]
    counts: dict[tuple[str, str], int] = {}
    for item in results:
        experiment = selected.get(item.publication_id)
        if (
            item.expected
            and experiment
            and item.joined_at
            and item.joined_at <= experiment.deadline
        ):
            key = (item.publication_id, item.student_id)
            counts[key] = counts.get(key, 0) + 1
    for item in results:
        experiment = selected.get(item.publication_id)
        if experiment is None or not item.expected:
            continue
        if item.joined_at is None or counts.get((item.publication_id, item.student_id), 0) > 1:
            awaiting.append({"task_id": item.task_id or "", "reason": "ENROLLMENT_UNCONFIRMED"})
            continue
        if experiment.deadline < item.joined_at:
            continue
        score = maximum = ZERO
        for kind, (actual, possible) in item.parts.items():
            actual = ZERO if item.submission_status == "NOT_SUBMITTED" else actual
            score += actual
            maximum += possible
            by_part[kind][0] += actual
            by_part[kind][1] += possible
        row = {
            "publication_id": item.publication_id,
            "task_id": item.task_id,
            "student_id": item.student_id,
            "student_name": item.student_name,
            "status": item.submission_status,
            "score": score,
            "max_score": maximum,
        }
        by_experiment[item.publication_id].append(row)
        by_student.setdefault(item.student_id, []).append(row)
    students = []
    for student_id, rows in by_student.items():
        summary = _summary(rows)
        exact = (
            sum((row["score"] for row in rows), ZERO)
            / sum((row["max_score"] for row in rows), ZERO)
            if summary["max_score"]
            else None
        )
        students.append({
            "student_id": student_id,
            "student_name": rows[0]["student_name"],
            "rank": None,
            "exact": exact,
            **summary,
        })
    students.sort(
        key=lambda item: (-(item["exact"] if item["exact"] is not None else -1), item["student_id"])
    )
    previous = None
    rank = 0
    for index, student in enumerate(students, 1):
        score = student.pop("exact")
        if score is not None:
            if score != previous:
                rank = index
            student["rank"] = rank
            student["failed"] = score < Decimal("0.60")
            previous = score
        else:
            student["failed"] = None
    all_rows = [row for rows in by_experiment.values() for row in rows]
    parts = [
        {
            "kind": kind,
            "label": PARTS[kind],
            "percent": _percent(score, maximum),
            "suggestion": SUGGESTIONS[kind]
            if maximum and score < maximum * Decimal("0.60")
            else "",
        }
        for kind, (score, maximum) in by_part.items()
        if maximum
    ]
    return {
        "summary": {
            **_summary(all_rows),
            "failure_rate": _percent(
                sum(s["failed"] is True for s in students),
                sum(s["failed"] is not None for s in students),
            ),
        },
        "experiments": [
            {
                "publication_id": key,
                "title": experiment.title,
                "deadline": experiment.deadline,
                "released_at": experiment.released_at,
                **_summary(by_experiment[key]),
            }
            for key, experiment in selected.items()
        ],
        "students": students,
        "parts": parts,
        "awaiting_confirmation": awaiting,
        "results": [
            {**row, "score": float(row["score"]), "max_score": float(row["max_score"])}
            for row in all_rows
        ],
    }
