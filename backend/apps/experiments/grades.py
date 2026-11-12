from decimal import Decimal

from django.db.models import Q

from .models import ExperimentRetakeLink, ExperimentTask


def task_grades(
    tasks: list[ExperimentTask], *, student: bool = False,
) -> dict[int, dict[str, object]]:
    """Project one effective grade per original task, retaining attempt metadata."""
    links = list(
        ExperimentRetakeLink.objects.filter(
            Q(source_task__in=tasks) | Q(retake_task__in=tasks)
        ).select_related("source_task", "retake_task")
    )
    result: dict[int, dict[str, object]] = {
        task.pk: {"score": None, "retake_of_task_id": None, "has_retake": False,
                  "retake_task_id": None} for task in tasks
    }
    for link in links:
        if link.source_task_id in result:
            result[link.source_task_id].update({"has_retake": True,
                "retake_task_id": link.retake_task.public_id if link.retake_task else None})
        if link.retake_task_id in result:
            result[link.retake_task_id]["retake_of_task_id"] = link.source_task.public_id
    from .assessment import assessment_results
    from .models import PublicationTask

    assessment_tasks = {task.pk: task for task in tasks}
    for link in links:
        assessment_tasks[link.source_task_id] = link.source_task
        if link.retake_task_id:
            assessment_tasks[link.retake_task_id] = link.retake_task
    assessment_scores: dict[int, dict[str, object]] = {}
    for task in assessment_tasks.values():
        questions = PublicationTask.objects.filter(
            publication_chapter__publication_id=task.publication_id,
            task_type__in=("SINGLE_CHOICE", "MULTIPLE_CHOICE", "PROGRAMMING"),
        )
        if not questions.exists():
            continue
        values = assessment_results(task, student=student)
        kinds = {"CHOICE" if q.task_type != "PROGRAMMING" else "PROGRAMMING" for q in questions}
        completed = len(values) == len(kinds) and all(v["score"] is not None for v in values)
        maximum = sum((q.max_score for q in questions), Decimal("0"))
        if task.publication.report_required and task.publication.rubric_version_id:
            maximum += task.publication.rubric_version.total_score
        grade: dict[str, object] = {
            "score": str(sum((Decimal(v["score"]) for v in values), Decimal("0")))
            if completed else None,
            "max_score": str(maximum),
        }
        assessment_scores[task.pk] = grade
        if task.pk in result:
            result[task.pk].update(grade)
    for link in links:
        retake = assessment_scores.get(link.retake_task_id)
        source = assessment_scores.get(link.source_task_id)
        if not retake or not source or retake["score"] is None:
            continue
        cap = Decimal(str(retake["max_score"])) * Decimal("0.60")
        score = min(Decimal(str(retake["score"])), cap).quantize(Decimal("0.01"))
        if link.retake_task_id in result:
            result[link.retake_task_id]["score"] = str(score)
        if link.source_task_id in result:
            adjusted = score / Decimal(str(retake["max_score"])) * Decimal(str(source["max_score"]))
            result[link.source_task_id]["score"] = str(max(
                Decimal(str(source["score"] or "0")), adjusted,
            ).quantize(Decimal("0.01")))
    return result
