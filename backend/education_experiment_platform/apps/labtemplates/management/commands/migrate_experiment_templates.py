import json
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.labtemplates.legacy import LegacyTemplateAdapter
from apps.labtemplates.models import (
    LegacyTemplateMigration,
    TemplateChapter,
    TemplateTask,
    TemplateVersion,
)


class Command(BaseCommand):
    help = "Convert legacy experiment templates into the chapter/task content tree."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--template-version-id", default="")

    def handle(self, *args: object, **options: object) -> None:
        batch_size = max(1, int(options["batch_size"]))
        limit = max(0, int(options["limit"]))
        dry_run = bool(options["dry_run"])
        queryset = TemplateVersion.objects.select_related(
            "template", "image", "resource_profile"
        ).order_by("id")
        version_id = str(options.get("template_version_id") or "").strip()
        if version_id:
            queryset = queryset.filter(public_id=version_id)
        if limit:
            queryset = queryset[:limit]

        counts: Counter[str] = Counter()
        for offset in range(0, queryset.count(), batch_size):
            for version in queryset[offset : offset + batch_size]:
                status = self._migrate(version, dry_run=dry_run)
                counts[status] += 1
        self.stdout.write(
            json.dumps(
                {
                    "dry_run": dry_run,
                    "migrated": counts[LegacyTemplateMigration.Status.MIGRATED],
                    "skipped": counts[LegacyTemplateMigration.Status.SKIPPED],
                    "migration_required": counts[LegacyTemplateMigration.Status.MIGRATION_REQUIRED],
                    "failed": counts[LegacyTemplateMigration.Status.FAILED],
                },
                ensure_ascii=False,
            )
        )

    def _migrate(self, version: TemplateVersion, *, dry_run: bool) -> str:
        existing = LegacyTemplateMigration.objects.filter(template_version=version).first()
        if existing is not None:
            return existing.status
        if version.chapters.exists():
            if not dry_run:
                LegacyTemplateMigration.objects.create(
                    template_version=version,
                    status=LegacyTemplateMigration.Status.SKIPPED,
                    processed_at=timezone.now(),
                    detail={"reason": "chapter_tree_exists"},
                )
            return LegacyTemplateMigration.Status.SKIPPED

        adapter = LegacyTemplateAdapter.from_version(version)
        if adapter.migration_required:
            if not dry_run:
                LegacyTemplateMigration.objects.create(
                    template_version=version,
                    status=LegacyTemplateMigration.Status.MIGRATION_REQUIRED,
                    error_code=adapter.migration_code,
                    processed_at=timezone.now(),
                    detail={"template_version_id": version.public_id},
                )
            return LegacyTemplateMigration.Status.MIGRATION_REQUIRED

        if dry_run:
            return LegacyTemplateMigration.Status.MIGRATED

        try:
            with transaction.atomic():
                chapter_data = adapter.chapters[0]
                chapter = TemplateChapter.objects.create(
                    template_version=version,
                    title=chapter_data["title"],
                    description=chapter_data["description"],
                    learning_objectives=chapter_data.get("learning_objectives", []),
                    sort_order=chapter_data["sort_order"],
                    status=chapter_data["status"],
                    resource_profile=version.resource_profile,
                )
                task_data = chapter_data["tasks"][0]
                task = TemplateTask.objects.create(
                    chapter=chapter,
                    title=task_data["title"],
                    description=task_data["description"],
                    instructions=task_data["instructions"],
                    task_type=task_data["task_type"],
                    sort_order=task_data["sort_order"],
                    status=task_data["status"],
                    execution_spec=task_data["execution_spec"],
                    resource_profile=version.resource_profile,
                    submission_policy={"required": True},
                    grading_policy={"mode": "MANUAL"},
                )
                LegacyTemplateMigration.objects.create(
                    template_version=version,
                    chapter=chapter,
                    task=task,
                    status=LegacyTemplateMigration.Status.MIGRATED,
                    processed_at=timezone.now(),
                    detail={"chapter_id": chapter.public_id, "task_id": task.public_id},
                )
        except Exception:
            LegacyTemplateMigration.objects.create(
                template_version=version,
                status=LegacyTemplateMigration.Status.FAILED,
                error_code="LEGACY_TEMPLATE_MIGRATION_FAILED",
                processed_at=timezone.now(),
            )
            return LegacyTemplateMigration.Status.FAILED
        return LegacyTemplateMigration.Status.MIGRATED
