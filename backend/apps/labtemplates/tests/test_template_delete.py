from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.services import ActorContext, create_user, grant_teacher_qualification
from apps.core.errors import RowVersionConflict
from apps.courses.models import Course
from apps.courses.services import (
    appoint_course_assistant,
    create_course,
    grant_course_capability,
)

from ..errors import TemplateDeleteForbidden, TemplateNameExists, TemplateStateConflict
from ..models import Template
from ..selectors import templates_for_course
from ..services import create_template, delete_template, update_template
from .helpers import context


class TemplateDeleteServiceTests(TestCase):
    def _teacher(self, suffix: str) -> tuple[User, Course]:
        user = create_user(
            email=f"{suffix}@example.edu",
            username=f"{suffix}",
            display_name=f"Teacher {suffix}",
            password="ValidPassword!234",
            context=ActorContext("system", "SYSTEM", suffix * 32),
        )
        grant_teacher_qualification(
            user_public_id=user.public_id,
            reason="test",
            expected_user_version=user.row_version,
            actor=user,
            context=context(user, "qual"),
        )
        course = create_course(
            actor=user,
            code=f"COURSE-DEL-{suffix.upper()}",
            title="Delete flow course",
            summary="",
            description="",
            visibility=Course.Visibility.PUBLIC,
            enrollment_mode=Course.EnrollmentMode.OPEN,
            capacity=30,
            enrollment_start=None,
            enrollment_end=None,
            teaching_start=None,
            teaching_end=None,
            context=context(user, "course"),
        )
        return user, course

    def _create_template_for(self, owner: User, course: Course, name: str) -> Template:
        return create_template(
            course_id=course.public_id,
            actor=owner,
            name=name,
            category="test",
            description="",
            context=context(owner, "create"),
        )

    def _appoint_assistant(self, course: Course, owner: User, assistant: User) -> None:
        staff = appoint_course_assistant(
            course_id=course.public_id,
            user_id=assistant.public_id,
            actor=owner,
            reason="assist delete matrix",
            context=context(owner, "assist"),
        )
        grant_course_capability(
            course_id=course.public_id,
            staff_id=staff.public_id,
            capability="MANAGE_TEMPLATE",
            expires_at=None,
            actor=owner,
            reason="assist delete matrix",
            context=context(owner, "grant"),
        )

    def test_owner_can_delete_own_draft_template(self) -> None:
        owner, course = self._teacher("delete-owner")
        template = self._create_template_for(owner, course, "draft-lab")
        deleted = delete_template(
            course_id=course.public_id,
            template_id=template.public_id,
            actor=owner,
            expected_version=template.row_version,
            context=context(owner, "delete"),
        )
        self.assertEqual(deleted.status, Template.Status.WITHDRAWN)
        remaining = templates_for_course(actor=owner, course_id=course.public_id)
        self.assertFalse(remaining.filter(public_id=template.public_id).exists())

    def test_course_staff_non_owner_cannot_delete(self) -> None:
        owner, course = self._teacher("matrix-owner")
        template = self._create_template_for(owner, course, "shared-lab")
        impostor, _ = self._teacher("matrix-assistant")
        self._appoint_assistant(course, owner, impostor)
        with self.assertRaises(TemplateDeleteForbidden):
            delete_template(
                course_id=course.public_id,
                template_id=template.public_id,
                actor=impostor,
                expected_version=template.row_version,
                context=context(impostor, "delete2"),
            )

    def test_published_template_requires_withdraw_first(self) -> None:
        owner, course = self._teacher("published-owner")
        template = self._create_template_for(owner, course, "published-lab")
        Template.objects.filter(pk=template.pk).update(status=Template.Status.PUBLISHED)
        refreshed = Template.objects.get(pk=template.pk)
        with self.assertRaises(TemplateStateConflict):
            delete_template(
                course_id=course.public_id,
                template_id=refreshed.public_id,
                actor=owner,
                expected_version=refreshed.row_version,
                context=context(owner, "delete3"),
            )

    def test_second_delete_hits_row_version_guard(self) -> None:
        owner, course = self._teacher("twice-owner")
        template = self._create_template_for(owner, course, "twice-lab")
        delete_template(
            course_id=course.public_id,
            template_id=template.public_id,
            actor=owner,
            expected_version=template.row_version,
            context=context(owner, "delete4"),
        )
        with self.assertRaises((RowVersionConflict, TemplateStateConflict)):
            delete_template(
                course_id=course.public_id,
                template_id=template.public_id,
                actor=owner,
                expected_version=template.row_version,
                context=context(owner, "delete5"),
            )

    def test_delete_frees_name_for_recreation(self) -> None:
        owner, course = self._teacher("reuse-owner")
        first = self._create_template_for(owner, course, "recycled-lab")
        delete_template(
            course_id=course.public_id,
            template_id=first.public_id,
            actor=owner,
            expected_version=first.row_version,
            context=context(owner, "delete6"),
        )
        recreated = self._create_template_for(owner, course, "recycled-lab")
        self.assertEqual(recreated.status, Template.Status.DRAFT)
        self.assertNotEqual(recreated.public_id, first.public_id)
        archived = Template.objects.get(public_id=first.public_id)
        self.assertEqual(archived.status, Template.Status.WITHDRAWN)
        self.assertNotEqual(archived.name, "recycled-lab")
        self.assertIn("[archived", archived.name)

    def test_creation_reuses_name_held_by_legacy_withdrawn_template(self) -> None:
        owner, course = self._teacher("legacy-owner")
        first = self._create_template_for(owner, course, "legacy-lab")
        Template.objects.filter(pk=first.pk).update(status=Template.Status.WITHDRAWN)
        recreated = self._create_template_for(owner, course, "legacy-lab")
        self.assertEqual(recreated.status, Template.Status.DRAFT)
        archived = Template.objects.get(public_id=first.public_id)
        self.assertIn("[archived", archived.name)

    def test_active_duplicate_name_reports_name_exists(self) -> None:
        owner, course = self._teacher("dupe-owner")
        self._create_template_for(owner, course, "dupe-lab")
        with self.assertRaises(TemplateNameExists):
            self._create_template_for(owner, course, "dupe-lab")

    def test_update_to_active_duplicate_name_reports_name_exists(self) -> None:
        owner, course = self._teacher("upd-owner")
        first = self._create_template_for(owner, course, "first-lab")
        second = self._create_template_for(owner, course, "second-lab")
        with self.assertRaises(TemplateNameExists):
            update_template(
                course_id=course.public_id,
                template_id=second.public_id,
                actor=owner,
                expected_version=second.row_version,
                changes={"name": first.name},
                context=context(owner, "upd"),
            )
