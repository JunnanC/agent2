import hashlib
import logging
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.core.audit import append_audit
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound
from apps.core.models import OutboxEvent
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.models import Course, Enrollment
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.governance.models import QuotaReservation

from .metrics import (
    ANALYTICS_DURATION,
    ANALYTICS_PROJECTION_LAG,
    ANALYTICS_PROJECTION_RUNS,
    RESOURCE_COST_AMOUNT,
    RISK_SIGNALS_TOTAL,
)
from .models import (
    CourseDaily,
    CourseQualitySnapshot,
    LearningRecommendation,
    ResourceCostDaily,
    StudentRiskSignal,
)

logger = logging.getLogger(__name__)
PROJECTION_VERSION = "p13-v1"


def _cursor() -> str:
    item = OutboxEvent.objects.order_by("-created_at", "-id").first()
    return f"{item.created_at.isoformat()}|{item.id}" if item else ""


def _digest(*values: object) -> str:
    return hashlib.sha256("|".join(str(value) for value in values).encode()).hexdigest()


def _upsert_projection(
    model: type[CourseDaily], *, lookup: dict[str, Any], defaults: dict[str, Any]
) -> Any:
    """Upsert a VersionedModel projection through the same CAS contract as APIs."""
    with transaction.atomic():
        current = model.objects.select_for_update().filter(**lookup).first()
        if current is None:
            try:
                return model.objects.create(**lookup, **defaults)
            except IntegrityError:
                current = model.objects.select_for_update().get(**lookup)
        return compare_and_swap(
            model,
            pk=current.pk,
            expected_version=current.row_version,
            changes=defaults,
        )


def rebuild_course_analytics(*, course_id: str | None = None, trace_id: str = "") -> int:
    started = timezone.now()
    courses = (
        Course.objects.all() if course_id is None else Course.objects.filter(public_id=course_id)
    )
    now = timezone.now()
    period = now.date()
    cursor = _cursor()
    total = 0
    for course in courses.iterator():
        tasks = ExperimentTask.objects.filter(course=course)
        task_counts = dict(
            tasks.values("status").annotate(count=Count("id")).values_list("status", "count")
        )
        enrollment_counts = dict(
            Enrollment.objects.filter(course=course)
            .values("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )
        metrics = {
            "enrollments": enrollment_counts,
            "tasks": task_counts,
            "active_students": enrollment_counts.get(Enrollment.Status.ACTIVE, 0),
            "task_total": tasks.count(),
        }
        _upsert_projection(
            CourseDaily,
            lookup={
                "course": course,
                "period_start": period,
                "projection_version": PROJECTION_VERSION,
            },
            defaults={"metrics": metrics, "source_cursor": cursor, "calculated_at": now},
        )
        completed = task_counts.get(ExperimentTask.Status.COMPLETED, 0) + task_counts.get(
            ExperimentTask.Status.APPROVED, 0
        )
        task_total = tasks.count()
        quality_metrics = {
            "task_total": task_total,
            "completed": completed,
            "completion_rate": (completed / task_total if task_total else 0),
        }
        _upsert_projection(
            CourseQualitySnapshot,
            lookup={
                "course": course,
                "period_start": period,
                "projection_version": PROJECTION_VERSION,
            },
            defaults={
                "quality_score": round(float(quality_metrics["completion_rate"]) * 100, 2),
                "metrics": quality_metrics,
                "source_cursor": cursor,
                "calculated_at": now,
            },
        )
        reservation_totals = QuotaReservation.objects.filter(course=course).aggregate(
            amount_minor=Sum("estimated_cost_minor"), units=Sum("instance_count")
        )
        _upsert_projection(
            ResourceCostDaily,
            lookup={
                "course": course,
                "period_start": period,
                "resource_type": "quota_estimate",
                "projection_version": PROJECTION_VERSION,
            },
            defaults={
                "amount_minor": int(reservation_totals["amount_minor"] or 0),
                "units": reservation_totals["units"] or 0,
                "metadata": {"source": "governance_quota_reservation"},
                "source_cursor": cursor,
                "calculated_at": now,
            },
        )
        RESOURCE_COST_AMOUNT.labels(resource_type="quota_estimate").inc(
            int(reservation_totals["amount_minor"] or 0)
        )
        overdue = tasks.filter(effective_deadline__lt=now, progress__lt=50).exclude(
            status__in=(
                ExperimentTask.Status.COMPLETED,
                ExperimentTask.Status.CANCELLED,
                ExperimentTask.Status.EXPIRED,
            )
        )
        for task in overdue.select_related("student"):
            digest = _digest(task.public_id, task.status, task.progress, task.effective_deadline)
            common = {
                "course": course,
                "task": task,
                "projection_version": PROJECTION_VERSION,
                "source_cursor": cursor,
                "calculated_at": now,
                "valid_until": now + timedelta(days=7),
            }
            _upsert_projection(
                StudentRiskSignal,
                lookup={
                    "student": task.student,
                    "kind": "OVERDUE_LOW_PROGRESS",
                    "source_digest": digest,
                },
                defaults={
                    **common,
                    "severity": "HIGH",
                    "explanation_masked": "任务已超过截止时间且进度较低，请教师结合实际情况判断。",
                    "evidence": {"progress": task.progress, "status": task.status},
                    "source_refs": [task.public_id],
                    "rule_version": "overdue-low-progress-v1",
                },
            )
            _upsert_projection(
                LearningRecommendation,
                lookup={
                    "student": task.student,
                    "kind": "REVIEW_OVERDUE_TASK",
                    "source_digest": digest,
                },
                defaults={
                    **common,
                    "title": "回顾待完成任务",
                    "explanation_masked": (
                        "该任务需要进一步关注，可查看任务要求和反馈后制定学习计划。"
                    ),
                    "evidence": {"progress": task.progress, "deadline": task.effective_deadline},
                    "source_refs": [task.public_id],
                    "rule_version": "overdue-low-progress-v1",
                },
            )
            RISK_SIGNALS_TOTAL.labels(kind="OVERDUE_LOW_PROGRESS", result="UPSERTED").inc()
        total += 1
    ANALYTICS_PROJECTION_RUNS.labels(kind="course", result="SUCCEEDED").inc()
    ANALYTICS_PROJECTION_LAG.labels(kind="course").set(0)
    ANALYTICS_DURATION.labels(kind="course").observe(
        max((timezone.now() - started).total_seconds(), 0)
    )
    logger.info(
        "analytics projection rebuilt",
        extra={
            "action": "analytics.rebuild",
            "result": "SUCCEEDED",
            "course_id": course_id,
            "count": total,
            "trace_id": trace_id,
        },
    )
    return total


@transaction.atomic
def resolve_risk_signal(
    *,
    signal_id: str,
    actor: User,
    status: str,
    expected_version: int,
    context: ActorContext,
    reason: str = "",
) -> StudentRiskSignal:
    signal = (
        StudentRiskSignal.objects.select_for_update()
        .select_related("course")
        .filter(public_id=signal_id)
        .first()
    )
    if signal is None:
        raise ResourceNotFound()
    if signal.status == StudentRiskSignal.Status.CLOSED and status != signal.status:
        raise ResourceNotFound()
    updated = compare_and_swap(
        StudentRiskSignal,
        pk=signal.pk,
        expected_version=expected_version,
        changes={"status": status, "resolved_by": actor, "resolved_at": timezone.now()},
    )
    append_audit(
        actor_ref=actor.public_id,
        actor_portal=context.portal,
        actor_context={},
        action="analytics.risk_signal.resolve",
        course_ref=signal.course.public_id,
        target_type="risk_signal",
        target_ref=signal.public_id,
        before={"status": signal.status},
        after={"status": status, "reason": reason},
        result="SUCCEEDED",
        trace_id=context.trace_id,
    )
    append_outbox_event(
        event_type="analytics.risk_signal.resolved",
        aggregate_type="risk_signal",
        aggregate_ref=signal.public_id,
        payload={
            "course_id": signal.course.public_id,
            "user_id": actor.public_id,
            "risk_signal_id": signal.public_id,
            "status": status,
        },
        trace_id=context.trace_id,
    )
    enqueue_relay_after_commit(trace_id=context.trace_id)
    RISK_SIGNALS_TOTAL.labels(kind=signal.kind, result=status).inc()
    return updated
