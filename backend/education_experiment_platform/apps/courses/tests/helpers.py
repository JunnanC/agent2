from apps.accounts.models import User
from apps.accounts.tests.helpers import create_user, grant_teacher
from apps.courses.models import Course
from apps.courses.services import ActorContext, create_course


def create_teacher(*, suffix: str = "owner") -> User:
    user = create_user(
        email=f"{suffix}@example.edu",
        username=suffix,
        display_name=suffix.title(),
    )
    grant_teacher(user)
    return user


def create_draft_course(
    owner: User,
    *,
    code: str = "COURSE-TEST-001",
    capacity: int | None = 10,
) -> Course:
    return create_course(
        actor=owner,
        code=code,
        title="Test Course",
        summary="Summary",
        description="Description",
        visibility=Course.Visibility.PUBLIC,
        enrollment_mode=Course.EnrollmentMode.OPEN,
        capacity=capacity,
        enrollment_start=None,
        enrollment_end=None,
        teaching_start=None,
        teaching_end=None,
        context=ActorContext(owner.public_id, "TEACHING", "a" * 32),
    )
