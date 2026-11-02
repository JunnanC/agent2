"""Demo Agent configuration, sessions, messages, tool approvals, and feedback."""

from __future__ import annotations

import contextlib
from collections import Counter
from typing import Final

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import ActorContext
from apps.agents.models import (
    AgentDefinition,
    AgentSession,
    AgentSource,
    AgentSourceVersion,
    AgentToolCallState,
    CourseAgentProfile,
    KnowledgeBase,
    ModelRoute,
    SessionFeedbackTriage,
    ToolPolicy,
)
from apps.agents.services import (
    create_agent_session,
    decide_tool_call,
    enqueue_agent_message,
    process_agent_message,
    request_tool,
    submit_agent_feedback,
)
from apps.courses.models import Course

from .banks import AGENT_QUESTIONS, AI_PROMPTS_HINT
from .config import BuildContext, stable_digest

DEMO_MODEL_ROUTE_KEY: Final[str] = "demo-local-rule"
DEMO_TOOL_POLICY_KEY: Final[str] = "demo-workspace-draft"
DEMO_DEFINITION_KEY: Final[str] = "demo-course-agent"
DEMO_KB_NAME: Final[str] = "演示课程知识库"
DEMO_SOURCE_TITLE: Final[str] = "演示课程讲义"
DEMO_TOOL_NAME: Final[str] = "workspace_draft"


def build_assistant_stack(
    ctx: BuildContext,
    courses: list[Course],
    students: list[User],
    counts: Counter[str],
) -> None:
    """Create demo agent profiles and conversations for the first two published courses."""

    agent_courses = [course for course in courses if course.status == Course.Status.PUBLISHED][:2]
    known = set(students)
    for course in agent_courses:
        route = _ensure_model_route(counts)
        definition = _ensure_definition(route, counts)
        policy = _ensure_tool_policy(counts)
        knowledge = _ensure_knowledge_base(ctx, course, counts)
        profile = _ensure_course_profile(
            ctx, course, definition, policy, route, knowledge, counts
        )
        if profile is None:
            continue
        learners = [
            enrollment.student
            for enrollment in course.enrollments.filter(status="ACTIVE")
            if enrollment.student in known
        ]
        teacher = course.owner
        if len(learners) < 2:
            continue
        for offset, student in enumerate(learners[:2]):
            _converse(ctx, course, student, offset, counts)
        _tool_calls(ctx, course, learners[0], counts)
        _feedback_with_triage(ctx, course, learners[1], teacher, counts)


def _user_view(ctx: BuildContext, student: User) -> ActorContext:
    return ActorContext(student.public_id, "USER", ctx.trace_id)


def _converse(
    ctx: BuildContext,
    course: Course,
    student: User,
    offset: int,
    counts: Counter[str],
) -> None:
    view = _user_view(ctx, student)
    with contextlib.suppress(Exception):
        session = create_agent_session(
            actor=student,
            course_id=course.public_id,
            mode=AgentSession.Mode.KNOWLEDGE_QA,
            context=view,
        )
        counts["agents.AgentSession"] += 1
        message = enqueue_agent_message(
            actor=student,
            session_id=session.public_id,
            body=AGENT_QUESTIONS[offset % len(AGENT_QUESTIONS)],
            context=view,
        )
        counts["agents.AgentMessage"] += 1
        reply = process_agent_message(message_id=message.public_id, trace_id=ctx.trace_id)
        counts["agents.AgentMessageReply"] += 1
        if offset == 1:
            with contextlib.suppress(Exception):
                submit_agent_feedback(
                    actor=student,
                    session_id=session.public_id,
                    message_id=reply.public_id,
                    rating="USEFUL",
                    issue_type="",
                    note="演示反馈：回答清晰。",
                    context=view,
                )
                counts["agents.SessionFeedback"] += 1


def _tool_calls(
    ctx: BuildContext,
    course: Course,
    student: User,
    counts: Counter[str],
) -> None:
    view = _user_view(ctx, student)
    session = None
    with contextlib.suppress(Exception):
        session = create_agent_session(
            actor=student,
            course_id=course.public_id,
            mode=AgentSession.Mode.KNOWLEDGE_QA,
            context=view,
        )
        counts["agents.AgentSession"] += 1
    if session is None:
        return
    with contextlib.suppress(Exception):
        call = request_tool(
            actor=student,
            session_id=session.public_id,
            tool_name=DEMO_TOOL_NAME,
            arguments={"path": "draft.md", "content": AI_PROMPTS_HINT},
            context=view,
        )
        counts["agents.AgentToolCall"] += 1
        decide_tool_call(
            actor=student,
            call_id=call.public_id,
            decision="APPROVED",
            reason="演示数据集：学生本人确认。",
            expected_version=call.state.row_version,
            context=view,
        )
        counts["agents.AgentToolCallState"] += 1
    with contextlib.suppress(Exception):
        second = request_tool(
            actor=student,
            session_id=session.public_id,
            tool_name=DEMO_TOOL_NAME,
            arguments={"path": "gradebook.csv", "content": "演示"},
            context=view,
        )
        counts["agents.AgentToolCall"] += 1
        if second.state.status == AgentToolCallState.Status.PENDING_APPROVAL:
            decide_tool_call(
                actor=student,
                call_id=second.public_id,
                decision="REJECTED",
                reason="演示数据集：学生取消该操作。",
                expected_version=second.state.row_version,
                context=view,
            )
            counts["agents.AgentToolCallState"] += 1


def _feedback_with_triage(
    ctx: BuildContext,
    course: Course,
    student: User,
    teacher: User,
    counts: Counter[str],
) -> None:
    view = _user_view(ctx, student)
    with contextlib.suppress(Exception):
        session = create_agent_session(
            actor=student,
            course_id=course.public_id,
            mode=AgentSession.Mode.KNOWLEDGE_QA,
            context=view,
        )
        counts["agents.AgentSession"] += 1
        message = enqueue_agent_message(
            actor=student,
            session_id=session.public_id,
            body=AGENT_QUESTIONS[2 % len(AGENT_QUESTIONS)],
            context=view,
        )
        counts["agents.AgentMessage"] += 1
        reply = process_agent_message(message_id=message.public_id, trace_id=ctx.trace_id)
        feedback = submit_agent_feedback(
            actor=student,
            session_id=session.public_id,
            message_id=reply.public_id,
            rating="NOT_USEFUL",
            issue_type="WRONG_ANSWER",
            note="演示反馈：答复未覆盖问题。",
            context=view,
        )
        counts["agents.SessionFeedback"] += 1
        SessionFeedbackTriage.objects.create(
            feedback=feedback,
            actor=teacher,
            status=SessionFeedbackTriage.Status.OPEN,
        )
        counts["agents.SessionFeedbackTriage"] += 1


def _ensure_model_route(counts: Counter[str]) -> ModelRoute:
    route, created = ModelRoute.objects.get_or_create(
        key=DEMO_MODEL_ROUTE_KEY,
        version_no=1,
        defaults={
            "provider": "LOCAL",
            "model_name": "rule-based",
            "regions": ["LOCAL"],
            "timeout_seconds": 5,
            "max_tokens": 4096,
        },
    )
    if created:
        counts["agents.ModelRoute"] += 1
    return route


def _ensure_definition(route: ModelRoute, counts: Counter[str]) -> AgentDefinition:
    definition, created = AgentDefinition.objects.get_or_create(
        key=DEMO_DEFINITION_KEY,
        version_no=1,
        defaults={
            "mode": "COURSE_AGENT",
            "model_route": route.public_id,
            "safety_config": {"platform_baseline": True},
        },
    )
    if created:
        counts["agents.AgentDefinition"] += 1
    return definition


def _ensure_tool_policy(counts: Counter[str]) -> ToolPolicy:
    policy, created = ToolPolicy.objects.get_or_create(
        key=DEMO_TOOL_POLICY_KEY,
        version_no=1,
        defaults={
            "tool_name": DEMO_TOOL_NAME,
            "risk": ToolPolicy.Risk.HIGH,
            "allowlist": [DEMO_TOOL_NAME],
            "schema": {"type": "object", "additionalProperties": True},
            "status": ToolPolicy.Status.ACTIVE,
        },
    )
    if created:
        counts["agents.ToolPolicy"] += 1
    return policy


def _ensure_knowledge_base(
    ctx: BuildContext,
    course: Course,
    counts: Counter[str],
) -> KnowledgeBase:
    knowledge, created = KnowledgeBase.objects.get_or_create(
        course=course,
        name=DEMO_KB_NAME,
        defaults={
            "description": "演示数据集课程知识库。",
            "status": KnowledgeBase.Status.ACTIVE,
        },
    )
    if created:
        counts["agents.KnowledgeBase"] += 1

    published_version = (
        course.materials.filter(current_version__isnull=False)
        .order_by("course", "-created_at")
        .first()
    )
    if published_version is not None:
        material_version = published_version.current_version
        source, _ = AgentSource.objects.get_or_create(
            knowledge_base=knowledge,
            title=DEMO_SOURCE_TITLE,
            defaults={
                "course": course,
                "source_type": AgentSource.SourceType.COURSE_MATERIAL,
                "material_version": material_version,
                "audience": {"course_id": course.public_id},
                "status": AgentSource.Status.ACTIVE,
            },
        )
        counts["agents.AgentSource"] += 1
        digest = getattr(material_version, "digest_sha256", "") or stable_digest(
            "demo-kb", str(material_version.public_id)
        )
        _, version_created = AgentSourceVersion.objects.get_or_create(
            source=source,
            version_no=1,
            defaults={
                "digest_sha256": digest,
                "material_version": material_version,
                "audience": {"course_id": course.public_id},
                "status": AgentSourceVersion.Status.INDEXED,
                "indexed_at": timezone.now(),
            },
        )
        if version_created:
            counts["agents.AgentSourceVersion"] += 1
    return knowledge


def _ensure_course_profile(
    ctx: BuildContext,
    course: Course,
    definition: AgentDefinition,
    policy: ToolPolicy,
    route: ModelRoute,
    knowledge: KnowledgeBase,
    counts: Counter[str],
) -> CourseAgentProfile | None:
    del ctx
    profile = CourseAgentProfile.objects.filter(course=course, version_no=1).first()
    if profile is None:
        profile = CourseAgentProfile.objects.create(
            course=course,
            definition=definition,
            version_no=1,
            status=CourseAgentProfile.Status.ACTIVE,
            modes=list(AgentSession.Mode.values),
            knowledge_base=knowledge,
            tool_policy=policy,
            model_route=route.public_id,
            budget={
                "max_tokens": 2048,
                "daily_tokens": 100000,
                "requests_per_minute": 30,
                "daily_tool_calls": 50,
                "daily_cost_minor": 50000,
            },
        )
        counts["agents.CourseAgentProfile"] += 1
    return profile
