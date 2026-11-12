from decimal import Decimal

from django.db.models import Q

from apps.reviews.models import ReviewDecision

from .models import ExperimentRetakeLink, ExperimentTask


def capped_retake_score(score: Decimal) -> Decimal:
    return min(score, Decimal("60.00"))


def task_grades(
    tasks: list[ExperimentTask], *, student: bool = False,
) -> dict[int, dict[str, object]]:
    """Project one effective grade per original task, retaining attempt metadata."""
    links = list(
        ExperimentRetakeLink.objects.filter(
            Q(source_task__in=tasks) | Q(retake_task__in=tasks)
        ).select_related("source_task", "retake_task")
    )
    all_ids = {task.pk for task in tasks}
    all_ids.update(link.source_task_id for link in links)
    all_ids.update(link.retake_task_id for link in links if link.retake_task_id)
    decisions: dict[int, ReviewDecision] = {}
    for decision in ReviewDecision.objects.filter(review__task_id__in=all_ids).select_related(
        "review"
    ).order_by("review__task_id", "-review__round_no"):
        decisions.setdefault(decision.review.task_id, decision)
    result: dict[int, dict[str, object]] = {
        task.pk: {
            "score": str(decisions[task.pk].score) if task.pk in decisions else None,
            "retake_of_task_id": None,
            "has_retake": False,
            "retake_task_id": None,
        }
        for task in tasks
    }
    for link in links:
        retake_score = link.registered_score
        if retake_score is None and link.retake_task_id in decisions:
            retake_score = capped_retake_score(decisions[link.retake_task_id].score)
        if link.source_task_id in result:
            original = decisions.get(link.source_task_id)
            score = original.score if original else None
            if retake_score is not None:
                score = max(score or Decimal("0"), retake_score)
            result[link.source_task_id].update({
                "score": str(score) if score is not None else None,
                "has_retake": True,
                "retake_task_id": link.retake_task.public_id if link.retake_task else None,
            })
        if link.retake_task_id in result:
            result[link.retake_task_id].update({
                "score": str(retake_score) if retake_score is not None else None,
                "retake_of_task_id": link.source_task.public_id,
            })
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
