from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase, override_settings

from apps.courses.models import Course
from apps.experiments.tests.helpers import create_domain
from apps.labtemplates.models import Template

from ..seed_names import rename_seed_labels


@override_settings(DEBUG=True)
class SeedNameTests(TestCase):
    def setUp(self) -> None:
        self.teacher, self.course, self.version, _ = create_domain(suffix="seed-names")
        Course.objects.filter(pk=self.course.pk).update(title="P03 课程协作实践")
        Template.objects.filter(pk=self.version.template_id).update(name="P05 容器实验模板")

    def test_rename_preserves_ids_relations_and_is_idempotent(self) -> None:
        self.course.refresh_from_db()
        previous_version = self.course.row_version
        self.assertEqual(rename_seed_labels(), 2)
        self.course.refresh_from_db()
        self.version.template.refresh_from_db()
        self.assertEqual(self.course.title, "课程协作实践")
        self.assertEqual(self.course.row_version, previous_version + 1)
        self.assertEqual(self.version.template.name, "容器实验模板")
        self.assertEqual(self.version.template.course_id, self.course.pk)
        self.assertEqual(rename_seed_labels(), 0)
        self.assertEqual(Course.objects.count(), 1)
        self.assertEqual(Template.objects.count(), 1)

    def test_name_collision_rolls_back_all_changes(self) -> None:
        Template.objects.create(
            course=self.course, name="容器实验模板", category="systems", owner=self.teacher
        )
        with self.assertRaises(IntegrityError):
            rename_seed_labels()
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "P03 课程协作实践")

    @override_settings(DEBUG=False)
    def test_command_rejects_production_before_changing_data(self) -> None:
        from unittest.mock import patch

        with (
            patch.dict("os.environ", {"APP_ENV": "production"}),
            self.assertRaises(CommandError),
        ):
            call_command("rename_seed_labels")
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "P03 课程协作实践")
