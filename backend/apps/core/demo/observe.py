"""Demo notifications derived from demo outbox events, plus analytics projections."""

from __future__ import annotations

import contextlib
from collections import Counter
from typing import Final

from apps.accounts.models import User
from apps.accounts.services import ActorContext
from apps.analytics.models import StudentRiskSignal
from apps.analytics.services import rebuild_course_analytics, resolve_risk_signal
from apps.core.models import OutboxEvent
from apps.courses.models import Course
from apps.experiments.models import ExperimentTask
from apps.notifications.models import Notification
from apps.notifications.services import create_notifications_for_event, mark_read

from .config import DEMO_USERNAME_PREFIX, BuildContext

NOTIFICATION_EVENT_LIMIT: Final[int] = 400
MARKED_ROWS_LIMIT: Final[int] = 3


def populate_notifications(ctx: BuildContext, counts: Counter[str]) -> int:
    """Turn demo outbox events into in-app notifications (idempotent by source event)."""

    events = OutboxEvent.objects.filter(trace_id__startswith="demo").order_by("created_at")[
        :NOTIFICATION_EVENT_LIMIT
    ]
    created_total = 0
    for event in events:
        with contextlib.suppress(Exception):
            made = create_notifications_for_event(event)
            created_total += made
    counts["notifications.OutboxDerived"] += created_total
    created_total += _synthesize_task_notifications(counts)
    counts["notifications.Notification"] += created_total
    _mark_some_read(ctx, counts)
    return created_total


_NOTIFICATION_TEMPLATES: Final[dict[str, tuple[str, str, str]]] = {
    "assigned": ("demo-task-assigned", "新实验任务已分配", "请进入任务列表完成演示实验。"),
    "submitted": ("demo-report-submitted", "收到实验提交", "学生已提交实验报告，评阅流程已开启。"),
    "under_review": (
        "demo-submitted-received",
        "实验提交已确认",
        "报告版本已提交，正在等待教师完成评阅。",
    ),
    "archived": ("demo-archived", "实验已归档", "评阅结论已生效，实验资源按归档策略回收完成。"),
}


def _synthesize_task_notifications(counts: Counter[str]) -> int:
    """Most demo events omit actor keys, so derive inbox rows straight from facts."""

    tasks = ExperimentTask.objects.filter(publication__course__code__startswith="DEMO-")[:300]
    created = 0
    for task in tasks:
        task.refresh_from_db()
        teacher = task.course.owner
        rows: list[tuple[User, str, str]] = []
        if task.student is not None:
            rows.append((task.student, "USER", "assigned"))
        if task.status == ExperimentTask.Status.UNDER_REVIEW and teacher is not None:
            rows.append((teacher, "TEACHING", "submitted"))
            rows.append((task.student, "USER", "under_review"))
        if task.status in {
            ExperimentTask.Status.APPROVED,
            ExperimentTask.Status.ARCHIVING,
            ExperimentTask.Status.COMPLETED,
        } and task.student is not None:
            rows.append((task.student, "USER", "archived"))
        for account, portal, template in rows:
            kind, title, body = _NOTIFICATION_TEMPLATES[template]
            if _create_demo_notification(account, portal, kind, title, body, task):
                created += 1
    return created


def _create_demo_notification(
    account: User,
    portal: str,
    kind: str,
    title: str,
    body: str,
    task: ExperimentTask,
) -> bool:
    source_event_id = f"demo-note:{kind}:{task.public_id}"
    _, made = Notification.objects.get_or_create(
        account=account,
        portal=portal,
        kind=kind,
        source_event_id=source_event_id,
        defaults={
            "title": title,
            "body_masked": body,
            "link_url": "",
            "course_ref": task.course.public_id,
            "task_ref": task.public_id,
            "scope": {},
        },
    )
    return made


def _mark_some_read(ctx: BuildContext, counts: Counter[str]) -> None:
    student = User.objects.filter(
        username__startswith=f"{DEMO_USERNAME_PREFIX}student-"
    ).order_by("username").first()
    if student is None:
        return
    unread = Notification.objects.filter(
        account=student,
        portal="USER",
        read_at__isnull=True,
    ).order_by("-created_at")[:MARKED_ROWS_LIMIT]
    view = ActorContext(student.public_id, "USER", ctx.trace_id)
    for item in unread:
        with contextlib.suppress(Exception):
            mark_read(
                item=item,
                expected_version=item.row_version,
                context=view,  # type: ignore[arg-type]
            )
            counts["notifications.Read"] += 1


def rebuild_analytics(
    ctx: BuildContext,
    courses: list[Course],
    counts: Counter[str],
) -> int:
    """Recompute projections from the seeded business facts, per course."""

    rebuilt = 0
    for course in courses:
        course.refresh_from_db()
        if course.status == Course.Status.DRAFT:
            continue
        with contextlib.suppress(Exception):
            rebuilt += int(rebuild_course_analytics(course_id=course.public_id))
    counts["analytics.Projections"] += rebuilt
    _resolve_one_signal(ctx, courses, counts)
    return rebuilt


def _resolve_one_signal(
    ctx: BuildContext,
    courses: list[Course],
    counts: Counter[str],
) -> None:
    for course in courses:
        teacher = course.owner
        signal = (
            StudentRiskSignal.objects.filter(course=course, status=StudentRiskSignal.Status.OPEN)
            .order_by("-calculated_at", "public_id")
            .first()
        )
        if signal is None:
            continue
        with contextlib.suppress(Exception):
            resolve_risk_signal(
                signal_id=signal.public_id,
                actor=teacher,
                status=StudentRiskSignal.Status.ACKNOWLEDGED,
                expected_version=signal.row_version,
                context=ActorContext(teacher.public_id, "TEACHING", ctx.trace_id),  # type: ignore[arg-type]
                reason="演示数据集：教师已确认风险信号",
            )
            counts["analytics.RiskSignalAck"] += 1
        return
