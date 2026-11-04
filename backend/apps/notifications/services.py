import logging
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.core.models import OutboxEvent
from apps.core.outbox import consume_once
from apps.courses.events import ENROLLMENT_STUDENT_DROPPED
from apps.courses.models import Course, Enrollment
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask, TaskPublication

from .metrics import NOTIFICATIONS_TOTAL
from .models import Notification, Preference

logger = logging.getLogger(__name__)

ASSIGNMENT_KINDS = {"experiment.task_assigned", "tasks.task.assigned", "demo-task-assigned"}
DEADLINE_REMINDER_KIND = "experiment.deadline_reminder"
GENERIC_BODIES = {"", "有新的平台动态", "请进入任务列表完成演示实验。"}


def _deadline_text(deadline: datetime) -> str:
    return timezone.localtime(deadline).strftime("%Y-%m-%d %H:%M")


def _notification_content(kind: str, payload: dict[str, Any]) -> dict[str, str]:
    """Use event snapshots; resolve older events that predate descriptive payloads."""
    if kind == ENROLLMENT_STUDENT_DROPPED:
        ended_at = parse_datetime(payload["ended_at"])
        return {
            "title": "学生退课通知",
            "body_masked": (
                f"学生：{payload['student_name']}（{payload['student_username']}）。\n"
                f"已退出课程：《{payload['course_name']}》。\n"
                f"退课原因：{payload['reason']}。\n"
                f"退课时间：{_deadline_text(ended_at) if ended_at else payload['ended_at']}。\n"
                "退课已生效，无需教师审批。"
            ),
            "link_url": f"/courses/{payload['course_id']}/enrollments",
        }
    system_messages = {
        "account.created": (
            "账号创建成功",
            "你的平台账号已创建，可以完善个人资料并加入课程开始学习。",
        ),
        "teacher.qualification.changed": (
            "教师资格信息已更新",
            "你的教师资格信息已更新，请在个人资料中查看当前认证状态。",
        ),
        "governance.quota.reserved": (
            "实验资源配额已预留",
            "平台已为实验预留所需资源配额，资源将随实验任务的使用和回收进行管理。",
        ),
    }
    if kind in system_messages:
        title, body = system_messages[kind]
        return {"title": title, "body_masked": body}
    if kind in ASSIGNMENT_KINDS:
        task_id = payload.get("task_id")
        title, course_name = payload.get("experiment_title"), payload.get("course_name")
        course_id = payload.get("course_id")
        deadline = parse_datetime(payload["deadline"]) if payload.get("deadline") else None
        if task_id and not (title and course_name and course_id and deadline):
            task = (
                ExperimentTask.objects.select_related("publication", "course")
                .filter(public_id=task_id)
                .first()
            )
            if task:
                title = title or task.publication.title
                course_name = course_name or task.course.title
                course_id = course_id or task.course.public_id
                deadline = deadline or task.effective_deadline or task.publication.window_end
        if title and course_name:
            body = f"教师发布了新实验：{title}。\n所属课程：{course_name}。"
            if deadline:
                body += f"\n截止时间：{_deadline_text(deadline)}。"
            body += "\n请在截止前完成实验并提交报告。"
            return {
                "title": "新实验已发布",
                "body_masked": body,
                "course_ref": str(course_id or ""),
                "task_ref": str(task_id or ""),
                "link_url": f"/experiments/{task_id}" if task_id else "",
            }
    enrollment_messages = {
        "enrollment.applied": ("课程申请已提交", "你已申请加入课程《{course}》，请等待教师审核。"),
        "enrollment.activated": (
            "已加入课程",
            "你已成功加入课程《{course}》，可以开始学习和实验。",
        ),
        "enrollment.rejected": ("课程申请未通过", "你加入课程《{course}》的申请未通过教师审核。"),
        "enrollment.ended": ("选课已结束", "你在课程《{course}》的选课已结束。"),
    }
    if kind in enrollment_messages and payload.get("course_id"):
        course = Course.objects.filter(public_id=payload["course_id"]).first()
        if course:
            title, body = enrollment_messages[kind]
            return {"title": title, "body_masked": body.format(course=course.title)}
    return {}


def _accepts_notification(account: User, portal: str, kind: str) -> bool:
    preference = Preference.objects.filter(account=account, portal=portal).first()
    return not preference or (
        kind not in preference.muted_kinds and preference.channels.get("in_app", True)
    )


def _targets(event: OutboxEvent) -> list[tuple[User, str]]:
    payload = event.payload or {}
    if event.event_type == ENROLLMENT_STUDENT_DROPPED:
        return [
            (user, "TEACHING")
            for user in User.objects.filter(public_id__in=payload.get("teacher_ids", []))
        ]
    portal = str(payload.get("portal", "USER"))
    values = [payload.get("user_id"), payload.get("student_id"), payload.get("actor_id")]
    result: list[tuple[User, str]] = []
    for value in dict.fromkeys(str(item) for item in values if item):
        user = User.objects.filter(public_id=value).first()
        if user:
            result.append((user, portal))
    return result


@transaction.atomic
def create_notifications_for_event(event: OutboxEvent) -> int:
    payload = event.payload or {}
    kind = event.event_type
    content = _notification_content(kind, payload)
    created = 0
    for account, portal in _targets(event):
        if not _accepts_notification(account, portal, kind):
            continue
        _, made = Notification.objects.get_or_create(
            account=account,
            portal=portal,
            source_event_id=str(event.id),
            kind=kind,
            defaults={
                "title": str(payload.get("title", "平台通知")),
                "body_masked": str(payload.get("message", payload.get("body", "有新的平台动态"))),
                "link_url": str(payload.get("link_url", "")),
                "course_ref": str(payload.get("course_id", "")),
                "task_ref": str(payload.get("task_id", "")),
                "scope": {"actor_ref": account.public_id, "portal": portal},
                **content,
            },
        )
        if made:
            created += 1
            NOTIFICATIONS_TOTAL.labels(kind=kind, result="CREATED").inc()
    return created


def backfill_notification_content() -> int:
    """Repair generic historical messages without changing read status or identity."""
    count = 0
    candidates = Notification.objects.filter(body_masked__in=GENERIC_BODIES)
    for pk in candidates.values_list("pk", flat=True).iterator():
        with transaction.atomic():
            item = Notification.objects.select_for_update().get(pk=pk)
            if item.body_masked not in GENERIC_BODIES:
                continue
            content = _notification_content(
                item.kind,
                {
                    "task_id": item.task_ref,
                    "course_id": item.course_ref,
                },
            )
            if not content:
                continue
            compare_and_swap(
                Notification, pk=item.pk, expected_version=item.row_version, changes=content
            )
            count += 1
    return count


def remind_unfinished_experiments(*, now: datetime | None = None) -> int:
    now = now or timezone.now()
    until = now + timedelta(hours=settings.NOTIFICATION_DEADLINE_REMINDER_HOURS)
    unfinished = Q(
        status__in=[
            ExperimentTask.Status.ASSIGNED,
            ExperimentTask.Status.PROVISIONING,
            ExperimentTask.Status.READY,
            ExperimentTask.Status.IN_PROGRESS,
            ExperimentTask.Status.REPORT_DRAFT,
            ExperimentTask.Status.REJECTED,
        ]
    ) | Q(status=ExperimentTask.Status.FAILED, current_failure__retryable=True)

    def eligible() -> QuerySet[ExperimentTask]:
        return ExperimentTask.objects.annotate(
            reminder_deadline=Coalesce("effective_deadline", "publication__window_end")
        ).filter(
            unfinished,
            enrollment__status=Enrollment.Status.ACTIVE,
            course__status=Course.Status.PUBLISHED,
            publication__status=TaskPublication.Status.PUBLISHED,
            student__account_status=User.AccountStatus.ACTIVE,
            reminder_deadline__gt=now,
            reminder_deadline__lte=until,
            completed_at__isnull=True,
            terminal_target__isnull=True,
        )

    count = 0
    for pk in eligible().values_list("pk", flat=True).iterator():
        with transaction.atomic():
            # Recheck under lock in case the student submitted after the initial scan.
            task = (
                eligible()
                .select_for_update()
                .select_related("publication", "course", "student", "enrollment")
                .filter(pk=pk)
                .first()
            )
            if not task or not _accepts_notification(task.student, "USER", DEADLINE_REMINDER_KIND):
                continue
            deadline = task.reminder_deadline
            source = sha256(
                f"deadline:{task.public_id}:{deadline.isoformat()}".encode()
            ).hexdigest()
            _, made = Notification.objects.get_or_create(
                account=task.student,
                portal="USER",
                kind=DEADLINE_REMINDER_KIND,
                source_event_id=source,
                defaults={
                    "title": "实验未完成提醒",
                    "body_masked": (
                        f"实验未完成：{task.publication.title}。\n所属课程：{task.course.title}。\n"
                        f"截止时间：{_deadline_text(deadline)}。\n"
                        "实验即将截止，你尚未完成提交，请及时完成实验并提交报告。"
                    ),
                    "course_ref": task.course.public_id,
                    "task_ref": task.public_id,
                    "link_url": f"/experiments/{task.public_id}",
                    "scope": {"actor_ref": task.student.public_id, "portal": "USER"},
                },
            )
            if made:
                count += 1
                NOTIFICATIONS_TOTAL.labels(kind=DEADLINE_REMINDER_KIND, result="CREATED").inc()
    return count


def consume_notification_event(*, event_id: object) -> bool:
    event = OutboxEvent.objects.get(pk=event_id)
    return consume_once(
        event_id=event.id, consumer="notifications", handler=create_notifications_for_event
    )


@transaction.atomic
def mark_read(*, item: Notification, expected_version: int, context: ActorContext) -> Notification:
    if item.read_at is None:
        item = compare_and_swap(
            Notification,
            pk=item.pk,
            expected_version=expected_version,
            changes={"read_at": timezone.now()},
        )
        NOTIFICATIONS_TOTAL.labels(kind=item.kind, result="READ").inc()
    return item


@transaction.atomic
def update_preference(
    *, actor: User, portal: str, data: dict[str, Any], expected_version: int | None = None
) -> Preference:
    item, created = Preference.objects.get_or_create(account=actor, portal=portal, defaults=data)
    if created:
        return item
    if expected_version is None:
        from apps.core.errors import PreconditionRequired

        raise PreconditionRequired()
    return compare_and_swap(Preference, pk=item.pk, expected_version=expected_version, changes=data)
