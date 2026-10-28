from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.governance.models import ImageAsset

from ..legacy import LegacyTemplateAdapter
from ..models import LegacyTemplateMigration, TemplateChapter, TemplateTask, TemplateVersion
from .helpers import create_template_version


class LegacyTemplateMigrationTests(TestCase):
    def test_legacy_version_gets_default_chapter_and_task_idempotently(self) -> None:
        _owner, _course, _template, version = create_template_version(suffix="legacy-default")

        first = StringIO()
        call_command("migrate_experiment_templates", stdout=first)
        version.refresh_from_db()

        chapter = TemplateChapter.objects.get(template_version=version)
        task = TemplateTask.objects.get(chapter=chapter)
        self.assertEqual(chapter.title, "实验内容")
        self.assertEqual(task.title, "实验任务")
        self.assertEqual(
            LegacyTemplateMigration.objects.get(template_version=version).status,
            LegacyTemplateMigration.Status.MIGRATED,
        )

        call_command("migrate_experiment_templates", stdout=StringIO())
        self.assertEqual(TemplateChapter.objects.filter(template_version=version).count(), 1)
        self.assertEqual(TemplateTask.objects.filter(chapter=chapter).count(), 1)

    def test_dry_run_does_not_write_and_tag_only_image_requires_migration(self) -> None:
        _owner, _course, _template, version = create_template_version(suffix="legacy-tag")
        ImageAsset.objects.filter(pk=version.image_id).update(digest="")
        version.refresh_from_db()

        adapter = LegacyTemplateAdapter.from_version(version)
        self.assertTrue(adapter.migration_required)
        self.assertEqual(adapter.migration_code, "MIGRATION_REQUIRED")

        output = StringIO()
        call_command("migrate_experiment_templates", "--dry-run", stdout=output)
        self.assertFalse(TemplateChapter.objects.filter(template_version=version).exists())
        self.assertFalse(LegacyTemplateMigration.objects.filter(template_version=version).exists())
        self.assertIn('"migration_required": 1', output.getvalue())

    def test_revalidate_command_reports_governed_digest_state(self) -> None:
        _owner, _course, _template, version = create_template_version(suffix="legacy-image")
        output = StringIO()
        call_command("revalidate_experiment_images", stdout=output)
        self.assertIn('"valid":', output.getvalue())
        self.assertTrue(TemplateVersion.objects.filter(pk=version.pk).exists())
