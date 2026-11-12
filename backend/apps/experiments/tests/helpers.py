from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.tests.helpers import create_user
from apps.courses.models import Course, Enrollment
from apps.courses.services import ActorContext
from apps.labtemplates.models import (
    ExperimentImage,
    Template,
    TemplateChapter,
    TemplateTask,
    TemplateVersion,
)
from apps.labtemplates.tests.helpers import create_template_version
from apps.reviews.models import Rubric, RubricVersion

from ..models import TaskPublication
from ..services import create_publication


def context(actor: User, portal: str = "TEACHING") -> ActorContext:
    return ActorContext(actor.public_id, portal, "6" * 32)


def create_domain(
    *, suffix: str = "publications"
) -> tuple[User, Course, TemplateVersion, RubricVersion]:
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
    template_version.refresh_from_db()
    ExperimentImage.objects.create(
        template_version=template_version,
        source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
        registry=template_version.image.registry,
        repository=template_version.image.repository,
        requested_tag=template_version.image.display_tag or "stable",
        resolved_digest=template_version.image.digest,
        image_asset=template_version.image,
        status=ExperimentImage.Status.READY,
        scan_status=ExperimentImage.ScanStatus.CLEAN,
        trace_id=f"{suffix}-domain-image".ljust(32, "0")[:32],
        created_by=owner,
    )
    chapter = TemplateChapter.objects.create(
        template_version=template_version,
        title="Introduction",
        description="First chapter",
        learning_objectives=["Understand the environment"],
        sort_order=1,
        status=TemplateChapter.Status.PUBLISHED,
        resource_profile=template_version.resource_profile,
    )
    TemplateTask.objects.create(
        chapter=chapter,
        title="First task",
        description="Run the first task",
        instructions="Follow the instructions",
        task_type="SINGLE_CHOICE",
        question_spec={"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
        marking_spec={"correct_option_ids": ["b"]}, max_score=100,
        sort_order=1,
        status=TemplateTask.Status.PUBLISHED,
        resource_profile=template_version.resource_profile,
        submission_policy={"required": True},
        grading_policy={"mode": "MANUAL"},
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
    from apps.labtemplates.services import compute_spec_digest
    TemplateVersion.objects.filter(pk=template_version.pk).update(
        spec_digest=compute_spec_digest(template_version),
    )
    template_version.refresh_from_db()
    course.refresh_from_db()
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
            "description": "publications test publication",
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
