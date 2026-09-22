from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from apps.accounts.models import User

from .models import Course, CourseCopyJob, Enrollment, MaterialVersion


@dataclass(frozen=True)
class Blocker:
    type: str
    count: int
    refs: tuple[str, ...] = ()
    message: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "count": self.count,
            "refs": list(self.refs),
            "message": self.message,
        }


EnrollmentBlockerProvider = Callable[[Enrollment], list[Blocker]]
CourseBlockerProvider = Callable[[Course], list[Blocker]]
CourseCopyHandler = Callable[[CourseCopyJob, Course, Course, User, Any], None]

_enrollment_blocker_providers: list[EnrollmentBlockerProvider] = []
_course_archive_blocker_providers: list[CourseBlockerProvider] = []
_course_copy_handlers: list[CourseCopyHandler] = []


def register_enrollment_blocker(provider: EnrollmentBlockerProvider) -> None:
    if provider not in _enrollment_blocker_providers:
        _enrollment_blocker_providers.append(provider)


def register_course_archive_blocker(provider: CourseBlockerProvider) -> None:
    if provider not in _course_archive_blocker_providers:
        _course_archive_blocker_providers.append(provider)


def register_course_copy_handler(handler: CourseCopyHandler) -> None:
    if handler not in _course_copy_handlers:
        _course_copy_handlers.append(handler)


def enrollment_blockers(enrollment: Enrollment) -> list[Blocker]:
    return [item for provider in _enrollment_blocker_providers for item in provider(enrollment)]


def course_archive_blockers(course: Course) -> list[Blocker]:
    return [item for provider in _course_archive_blocker_providers for item in provider(course)]


def run_course_copy_handlers(
    *, job: CourseCopyJob, source: Course, target: Course, actor: User, context: Any
) -> None:
    for handler in _course_copy_handlers:
        handler(job, source, target, actor, context)


def published_material_versions(
    *, course: Course, public_ids: Iterable[str] | None = None
) -> list[MaterialVersion]:
    queryset = MaterialVersion.objects.select_related("material").filter(
        material__course=course,
        status=MaterialVersion.Status.PUBLISHED,
    )
    if public_ids is not None:
        queryset = queryset.filter(public_id__in=list(public_ids))
    return list(queryset.order_by("material__title", "version_no"))


def clear_blocker_providers() -> None:
    _enrollment_blocker_providers.clear()
    _course_archive_blocker_providers.clear()
    _course_copy_handlers.clear()
