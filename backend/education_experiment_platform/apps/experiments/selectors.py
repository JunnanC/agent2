from django.db.models import Q, QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.core.pagination import PageSpec
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.selectors import require_course_capability, visible_course

from .models import ExperimentTask, TaskExtensionRequest, TaskPublication


def teaching_course(*, actor: User, course_id: str, capability: str) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(course=course, actor=actor, capability=capability)
    return course


def publication_for_course(*, actor: User, course_id: str, publication_id: str) -> TaskPublication:
    course = teaching_course(
        actor=actor,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT,
    )
    try:
        return (
            TaskPublication.objects.select_related(
                "course",
                "template_version__template",
                "rubric_version__rubric",
                "runtime_adapter",
                "image",
                "resource_profile",
            )
            .prefetch_related("prerequisites", "audience")
            .get(public_id=publication_id, course=course)
        )
    except TaskPublication.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def publications_for_course(*, actor: User, course_id: str) -> QuerySet[TaskPublication]:
    course = teaching_course(
        actor=actor,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT,
    )
    return (
        TaskPublication.objects.filter(course=course)
        .select_related(
            "template_version__template",
            "rubric_version__rubric",
            "runtime_adapter",
            "image",
            "resource_profile",
        )
        .order_by("-created_at", "-id")
    )


def task_for_user(*, actor: User, task_id: str) -> ExperimentTask:
    try:
        return ExperimentTask.objects.select_related(
            "course",
            "publication",
            "enrollment",
            "template_version__template",
            "runtime_adapter",
            "image",
            "resource_profile",
        ).get(public_id=task_id, student=actor)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def task_for_teaching(*, actor: User, course_id: str, task_id: str) -> ExperimentTask:
    course = teaching_course(
        actor=actor,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.VIEW_PROGRESS,
    )
    try:
        return ExperimentTask.objects.select_related(
            "course",
            "publication",
            "student",
            "enrollment",
            "template_version__template",
            "runtime_adapter",
            "image",
            "resource_profile",
        ).get(public_id=task_id, course=course)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def task_for_platform(*, task_id: str) -> ExperimentTask:
    try:
        return ExperimentTask.objects.select_related(
            "course",
            "publication",
            "student",
            "enrollment",
            "runtime_adapter",
            "image",
            "resource_profile",
        ).get(public_id=task_id)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def paged_user_tasks(
    *,
    actor: User,
    spec: PageSpec,
    course_id: str = "",
    status: str = "",
    runtime_type: str = "",
    query: str = "",
) -> tuple[QuerySet[ExperimentTask], int]:
    tasks = ExperimentTask.objects.select_related(
        "course",
        "publication",
        "template_version__template",
        "enrollment",
        "student",
        "runtime_adapter",
        "image",
        "resource_profile",
    ).filter(student=actor)
    if course_id:
        tasks = tasks.filter(course__public_id=course_id)
    if status:
        tasks = tasks.filter(status=status)
    if runtime_type:
        tasks = tasks.filter(runtime_type=runtime_type)
    if query:
        tasks = tasks.filter(Q(public_id__icontains=query) | Q(publication__title__icontains=query))
    total = tasks.count()
    return tasks.order_by("-created_at", "-id")[spec.offset : spec.offset + spec.page_size], total


def paged_teaching_tasks(
    *,
    actor: User,
    course_id: str,
    publication_id: str,
    spec: PageSpec,
    status: str = "",
    query: str = "",
) -> tuple[QuerySet[ExperimentTask], int]:
    course = teaching_course(
        actor=actor,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.VIEW_PROGRESS,
    )
    tasks = ExperimentTask.objects.select_related(
        "course",
        "student",
        "publication",
        "enrollment",
        "template_version__template",
        "runtime_adapter",
        "image",
        "resource_profile",
    ).filter(course=course, publication__public_id=publication_id)
    if status:
        tasks = tasks.filter(status=status)
    if query:
        tasks = tasks.filter(
            Q(public_id__icontains=query) | Q(student__display_name__icontains=query)
        )
    total = tasks.count()
    return tasks.order_by("-created_at", "-id")[spec.offset : spec.offset + spec.page_size], total


def extension_request_for_teaching(
    *, actor: User, course_id: str, request_id: str
) -> TaskExtensionRequest:
    course = teaching_course(
        actor=actor,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.MANAGE_EXTENSION,
    )
    try:
        return TaskExtensionRequest.objects.select_related(
            "task", "task__publication", "task__student", "task__course"
        ).get(public_id=request_id, task__course=course)
    except TaskExtensionRequest.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def paged_extension_requests(
    *,
    actor: User,
    course_id: str,
    spec: PageSpec,
    status: str = "",
    publication_id: str = "",
    student_id: str = "",
) -> tuple[QuerySet[TaskExtensionRequest], int]:
    course = teaching_course(
        actor=actor,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.MANAGE_EXTENSION,
    )
    requests = TaskExtensionRequest.objects.select_related(
        "task", "task__publication", "task__student"
    ).filter(task__course=course)
    if status:
        requests = requests.filter(status=status)
    if publication_id:
        requests = requests.filter(task__publication__public_id=publication_id)
    if student_id:
        requests = requests.filter(task__student__public_id=student_id)
    total = requests.count()
    return requests.order_by("status", "-created_at", "-id")[
        spec.offset : spec.offset + spec.page_size
    ], total


def visible_extension_requests_for_user(
    *, actor: User, task_id: str
) -> QuerySet[TaskExtensionRequest]:
    return TaskExtensionRequest.objects.filter(
        task__public_id=task_id, requested_by=actor
    ).order_by("-created_at", "-id")
