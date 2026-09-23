from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.tests.helpers import create_user
from apps.courses.models import Course, Enrollment
from apps.courses.services import ActorContext
from apps.labtemplates.models import Template, TemplateVersion
from apps.labtemplates.tests.helpers import create_template_version
from apps.reviews.models import Rubric, RubricVersion

from ..models import TaskPublication
from ..services import create_publication


def context(actor: User, portal: str = "TEACHING") -> ActorContext:
    return ActorContext(actor.public_id, portal, "6" * 32)


def create_domain(*, suffix: str = "p06") -> tuple[User, Course, TemplateVersion, RubricVersion]:
    owner, course, template, template_version = create_template_version(suffix=suffix)
    now = timezone.now()
    Course.objects.filter(pk=course.pk).update(
        status=Course.Status.PUBLISHED,
        published_at=now,
    )
    TemplateVersion.objects.filter(pk=template_version.pk).update(
        status=TemplateVersion.Status.PUBLISHED,
        spec_digest=(suffix[0] if suffix else "a") * 64,
        published_by=owner,
        published_at=now,
    )
    Template.objects.filter(pk=template.pk).update(
        status=Template.Status.PUBLISHED,
        current_version=template_version,
    )
    rubric = Rubric.objects.create(
        course=course,
        name=f"Rubric {suffix}",
        owner=owner,
        status=Rubric.Status.PUBLISHED,
    )
    rubric_version = RubricVersion.objects.create(
        rubric=rubric,
        version_no=1,
        title="Published rubric",
        total_score="100.00",
        status=RubricVersion.Status.PUBLISHED,
        created_by=owner,
        published_by=owner,
        published_at=now,
    )
    Rubric.objects.filter(pk=rubric.pk).update(current_version=rubric_version)
    course.refresh_from_db()
    template_version.refresh_from_db()
    return owner, course, template_version, rubric_version


def create_enrollment(course: Course, *, suffix: str = "student") -> Enrollment:
    student = create_user(
        email=f"{suffix}@example.edu",
        username=suffix,
        display_name=suffix.title(),
    )
    now = timezone.now()
    return Enrollment.objects.create(
        course=course,
        student=student,
        cycle_no=1,
        status=Enrollment.Status.ACTIVE,
        applied_at=now,
        activated_at=now,
    )


def create_draft_publication(
    *,
    owner: User,
    course: Course,
    template_version: TemplateVersion,
    rubric_version: RubricVersion,
    suffix: str = "",
    audience_mode: str = TaskPublication.AudienceMode.ALL_ACTIVE,
    prerequisites: list[dict[str, str]] | None = None,
) -> TaskPublication:
    now = timezone.now()
    return create_publication(
        course_id=course.public_id,
        actor=owner,
        data={
            "template_version_id": template_version.public_id,
            "rubric_version_id": rubric_version.public_id,
            "title": f"Experiment {suffix}".strip(),
            "description": "P06 test publication",
            "audience_mode": audience_mode,
            "late_enrollment_policy": TaskPublication.LateEnrollmentPolicy.ASSIGN_UNTIL_DEADLINE,
            "window_start": now - timezone.timedelta(minutes=5),
            "window_end": now + timezone.timedelta(days=2),
            "assignment_deadline": now + timezone.timedelta(days=1),
            "report_required": True,
            "review_mode": TaskPublication.ReviewMode.MANUAL,
            "prerequisites": prerequisites or [],
        },
        context=context(owner),
    )
