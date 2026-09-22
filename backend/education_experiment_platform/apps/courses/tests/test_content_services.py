from io import StringIO
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.tests.helpers import create_user
from apps.courses.errors import InvitationInvalid, PrerequisiteCycle
from apps.courses.models import (
    CourseCopyItem,
    Enrollment,
    EnrollmentImportItem,
    Material,
)
from apps.courses.services import ActorContext, publish_course

from ..content_services import (
    add_course_prerequisite,
    change_chapter_status,
    change_material_version_status,
    consume_invitation,
    create_chapter,
    create_copy_job,
    create_invitation,
    create_material,
    create_material_version,
    execute_copy_job,
    execute_import,
    precheck_import,
)
from .helpers import create_draft_course, create_teacher


class CourseContentServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner = create_teacher()
        self.course = create_draft_course(self.owner)
        self.context = ActorContext(self.owner.public_id, "TEACHING", "c" * 32)
        self.course = publish_course(
            course_id=self.course.public_id,
            actor=self.owner,
            expected_version=self.course.row_version,
            context=self.context,
        )

    def test_material_publishing_uses_new_immutable_versions(self) -> None:
        chapter = create_chapter(
            course_id=self.course.public_id,
            actor=self.owner,
            title="Week 1",
            summary="",
            position=1,
            context=self.context,
        )
        chapter = change_chapter_status(
            chapter_id=chapter.public_id,
            actor=self.owner,
            expected_version=chapter.row_version,
            status="PUBLISHED",
            context=self.context,
        )
        material = create_material(
            course_id=self.course.public_id,
            actor=self.owner,
            chapter_id=chapter.public_id,
            title="Reading",
            kind="TEXT",
            text_content="v1",
            link_url="",
            asset_id=None,
            context=self.context,
        )
        first = change_material_version_status(
            version_id=material.current_version.public_id,
            actor=self.owner,
            expected_version=material.current_version.row_version,
            status="PUBLISHED",
            context=self.context,
        )
        second = create_material_version(
            material_id=material.public_id,
            actor=self.owner,
            expected_version=first.row_version,
            text_content="v2",
            link_url="",
            asset_id=None,
            context=self.context,
        )
        self.assertEqual(first.text_content, "v1")
        self.assertEqual(second.version_no, 2)
        self.assertEqual(Material.objects.get(pk=material.pk).current_version_id, first.pk)

    def test_invitation_only_exposes_raw_code_once_and_enforces_usage(self) -> None:
        invitation, raw = create_invitation(
            course_id=self.course.public_id,
            actor=self.owner,
            max_uses=1,
            expires_at=timezone.now() + timezone.timedelta(hours=1),
            context=self.context,
        )
        self.assertNotEqual(invitation.code_digest, raw)
        self.assertNotIn(raw, invitation.code_masked)
        with self.assertRaises(InvitationInvalid):
            consume_invitation(course=self.course, code="wrong")
        consume_invitation(course=self.course, code=raw)
        with self.assertRaises(InvitationInvalid):
            consume_invitation(course=self.course, code=raw)

    def test_prerequisite_cycle_is_rejected(self) -> None:
        other = create_draft_course(self.owner, code="COURSE-TEST-002")
        add_course_prerequisite(
            course_id=self.course.public_id,
            prerequisite_course_id=other.public_id,
            actor=self.owner,
            context=self.context,
        )
        with self.assertRaises(PrerequisiteCycle):
            add_course_prerequisite(
                course_id=other.public_id,
                prerequisite_course_id=self.course.public_id,
                actor=self.owner,
                context=self.context,
            )

    def test_copy_maps_current_material_version_without_roster(self) -> None:
        chapter = create_chapter(
            course_id=self.course.public_id,
            actor=self.owner,
            title="Week 1",
            summary="",
            position=1,
            context=self.context,
        )
        chapter = change_chapter_status(
            chapter_id=chapter.public_id,
            actor=self.owner,
            expected_version=chapter.row_version,
            status="PUBLISHED",
            context=self.context,
        )
        material = create_material(
            course_id=self.course.public_id,
            actor=self.owner,
            chapter_id=chapter.public_id,
            title="Reading",
            kind="TEXT",
            text_content="copy me",
            link_url="",
            asset_id=None,
            context=self.context,
        )
        version = change_material_version_status(
            version_id=material.current_version.public_id,
            actor=self.owner,
            expected_version=material.current_version.row_version,
            status="PUBLISHED",
            context=self.context,
        )
        job = create_copy_job(
            course_id=self.course.public_id,
            actor=self.owner,
            options={"code": "COURSE-COPY-001"},
            context=self.context,
        )
        copied = execute_copy_job(job_id=job.public_id, actor=self.owner, context=self.context)
        target_material = Material.objects.get(course=copied.target_course, title="Reading")
        self.assertIsNotNone(target_material.current_version_id)
        self.assertEqual(target_material.current_version.text_content, "copy me")
        self.assertEqual(CourseCopyItem.objects.filter(job=job).count(), 2)
        self.assertFalse(Enrollment.objects.filter(course=copied.target_course).exists())
        self.assertNotEqual(target_material.current_version_id, version.pk)

    def test_import_retries_only_unsuccessful_rows(self) -> None:
        first = create_user(email="first@example.edu", username="first")
        second = create_user(email="second@example.edu", username="second")
        job = precheck_import(
            course_id=self.course.public_id,
            actor=self.owner,
            rows=StringIO("email\nfirst@example.edu\nsecond@example.edu\n"),
            filename="roster.csv",
            context=self.context,
        )

        def create_or_fail(*, student: User, **kwargs: object) -> Enrollment:
            if student == second:
                raise RuntimeError("temporary")
            return Enrollment.objects.create(
                course=self.course,
                student=student,
                cycle_no=1,
                status=Enrollment.Status.ACTIVE,
                applied_at=timezone.now(),
            )

        with patch("apps.courses.content_services.apply_for_course", side_effect=create_or_fail):
            execute_import(job_id=job.public_id, actor=self.owner, context=self.context)
        self.assertEqual(
            EnrollmentImportItem.objects.get(job=job, normalized_identity=first.email).status,
            "SUCCEEDED",
        )
        self.assertEqual(
            EnrollmentImportItem.objects.get(job=job, normalized_identity=second.email).status,
            "ERROR",
        )

        with patch(
            "apps.courses.content_services.apply_for_course", side_effect=create_or_fail
        ) as apply_mock:
            apply_mock.side_effect = lambda *, student, **kwargs: Enrollment.objects.create(
                course=self.course,
                student=student,
                cycle_no=1,
                status=Enrollment.Status.ACTIVE,
                applied_at=timezone.now(),
            )
            execute_import(job_id=job.public_id, actor=self.owner, context=self.context)
        self.assertEqual(
            EnrollmentImportItem.objects.filter(job=job, status="SUCCEEDED").count(), 2
        )
        self.assertEqual(Enrollment.objects.filter(course=self.course).count(), 2)
