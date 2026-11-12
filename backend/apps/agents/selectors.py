from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.courses.models import Course, CourseStaffGrant, Enrollment
from apps.courses.selectors import require_course_capability, visible_course

from .models import (
    AgentMessage,
    AgentSession,
    AgentSourceVersion,
    CourseAgentProfile,
    EvalRun,
    EvalSuite,
    IngestionRun,
    KnowledgeBase,
    PromptTemplate,
    PromptVersion,
    SessionFeedback,
)


def teaching_course(*, actor: User, course_id: str) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.MANAGE_AGENT
    )
    return course


def user_course(*, actor: User, course_id: str) -> tuple[Course, Enrollment]:
    try:
        enrollment = Enrollment.objects.select_related("course").get(
            course__public_id=course_id,
            student=actor,
            status=Enrollment.Status.ACTIVE,
        )
    except Enrollment.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    return enrollment.course, enrollment


def active_profile_for_course(*, course: Course) -> CourseAgentProfile:
    try:
        return CourseAgentProfile.objects.select_related(
            "course",
            "definition",
            "knowledge_base",
            "prompt_version",
            "tool_policy",
            "last_eval_run",
        ).get(course=course, status=CourseAgentProfile.Status.ACTIVE)
    except CourseAgentProfile.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def profile_for_course(*, actor: User, course_id: str, profile_id: str) -> CourseAgentProfile:
    course = teaching_course(actor=actor, course_id=course_id)
    try:
        return CourseAgentProfile.objects.select_related(
            "course",
            "definition",
            "knowledge_base",
            "prompt_version",
            "tool_policy",
            "last_eval_run",
        ).get(course=course, public_id=profile_id)
    except CourseAgentProfile.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def profiles_for_course(*, actor: User, course_id: str) -> QuerySet[CourseAgentProfile]:
    course = teaching_course(actor=actor, course_id=course_id)
    return (
        CourseAgentProfile.objects.filter(course=course)
        .select_related(
            "definition", "knowledge_base", "prompt_version", "tool_policy", "last_eval_run"
        )
        .order_by("-version_no")
    )


def session_for_user(*, actor: User, session_id: str) -> AgentSession:
    try:
        return AgentSession.objects.select_related(
            "course",
            "enrollment",
            "task",
            "profile",
            "definition",
            "prompt_version",
            "knowledge_base",
            "tool_policy",
        ).get(public_id=session_id, student=actor)
    except AgentSession.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def messages_for_user(*, actor: User, session_id: str) -> QuerySet[AgentMessage]:
    session = session_for_user(actor=actor, session_id=session_id)
    return AgentMessage.objects.filter(session=session).order_by("created_at", "id")


def teaching_knowledge_bases(*, actor: User, course_id: str) -> QuerySet[KnowledgeBase]:
    course = teaching_course(actor=actor, course_id=course_id)
    return KnowledgeBase.objects.filter(course=course).order_by("name", "id")


def teaching_source_versions(
    *, actor: User, course_id: str, source_id: str
) -> QuerySet[AgentSourceVersion]:
    course = teaching_course(actor=actor, course_id=course_id)
    return AgentSourceVersion.objects.filter(
        source__course=course, source__public_id=source_id
    ).order_by("-version_no")


def ingestion_for_course(*, actor: User, course_id: str, run_id: str) -> IngestionRun:
    course = teaching_course(actor=actor, course_id=course_id)
    try:
        return IngestionRun.objects.select_related("source_version__source").get(
            public_id=run_id, source_version__source__course=course
        )
    except IngestionRun.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def prompt_templates_for_course(*, actor: User, course_id: str) -> QuerySet[PromptTemplate]:
    course = teaching_course(actor=actor, course_id=course_id)
    return PromptTemplate.objects.filter(course=course).order_by("name", "id")


def prompt_versions_for_course(
    *, actor: User, course_id: str, template_id: str
) -> QuerySet[PromptVersion]:
    course = teaching_course(actor=actor, course_id=course_id)
    return PromptVersion.objects.filter(
        template__course=course, template__public_id=template_id
    ).order_by("-version_no")


def eval_suites_for_course(*, actor: User, course_id: str) -> QuerySet[EvalSuite]:
    course = teaching_course(actor=actor, course_id=course_id)
    return EvalSuite.objects.filter(course=course).order_by("name", "id")


def eval_run_for_course(*, actor: User, course_id: str, run_id: str) -> EvalRun:
    course = teaching_course(actor=actor, course_id=course_id)
    try:
        return EvalRun.objects.select_related("suite", "profile").get(
            public_id=run_id, suite__course=course
        )
    except EvalRun.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def feedback_for_course(*, actor: User, course_id: str) -> QuerySet[SessionFeedback]:
    course = teaching_course(actor=actor, course_id=course_id)
    return (
        SessionFeedback.objects.filter(session__course=course)
        .select_related("message", "student", "triage")
        .order_by("-created_at")
    )


def platform_eval_run(*, run_id: str) -> EvalRun:
    try:
        return EvalRun.objects.select_related("suite", "profile").get(public_id=run_id)
    except EvalRun.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def can_start_session(*, session: AgentSession) -> bool:
    if session.status != AgentSession.Status.ACTIVE:
        return False
    if session.student.account_status != User.AccountStatus.ACTIVE:
        return False
    if session.enrollment.status != Enrollment.Status.ACTIVE:
        return False
    if session.course.status != Course.Status.PUBLISHED:
        return False
    return session.task is None or session.task.status not in {
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
        "ARCHIVING",
    }
