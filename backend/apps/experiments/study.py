"""Study time from actual completed custom executions, excluding queue wait."""

from typing import Any

from django.utils import timezone

from .models import AssessmentRun


def weekly_study_minutes_for_student(*, student: Any) -> dict[str, object]:
    now = timezone.localtime()
    monday = (now - timezone.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    previous = monday - timezone.timedelta(days=7)
    minutes = [0] * 7
    last_week = 0
    for run in AssessmentRun.objects.filter(
        task__student=student,
        status="COMPLETED",
        started_at__gte=previous,
        started_at__lt=monday + timezone.timedelta(days=7),
    ):
        started = timezone.localtime(run.started_at)
        value = round((run.duration_ms or 0) / 60000)
        if started < monday:
            last_week += value
        else:
            minutes[(started - monday).days] += value
    return {
        "minutes_by_day": minutes,
        "total_minutes": sum(minutes),
        "last_week_minutes": last_week,
        "has_records": bool(sum(minutes) or last_week),
    }
