"""Generate the full demo dataset for the three portals (disposable-only)."""

from __future__ import annotations

import os
from typing import Final

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.demo import build_demo_dataset, context_for
from apps.core.demo.config import DEFAULT_DEMO_PASSWORD, SCALE_PRESETS
from apps.core.demo.purge import purge_demo_data

ALLOWED_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"local", "integration", "test"})


class Command(BaseCommand):
    help = (
        "Create the complete demo dataset (accounts, courses, experiments, workspaces, "
        "reports, reviews, archives, agents, notifications, analytics) for the three "
        "portals. Disposable-only: runs when APP_ENV is local/integration/test (or DEBUG)."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument("--scale", choices=sorted(SCALE_PRESETS), default="demo")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--password", default=DEFAULT_DEMO_PASSWORD)
        parser.add_argument("--purge", action="store_true", help="Delete demo data only.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Skip writes; print what would be created.",
        )

    def handle(self, *args: object, **options: object) -> None:
        gate = os.getenv("APP_ENV", "")
        if gate not in ALLOWED_ENVIRONMENTS and not settings.DEBUG:
            raise CommandError(
                "seed_demo_full is restricted to disposable environments "
                "(APP_ENV local/integration/test or DEBUG)"
            )
        scale = str(options["scale"])
        if options["purge"]:
            replaced = purge_demo_data()
            self.stdout.write(self.style.SUCCESS(f"Purged demo data: {replaced}"))
            return
        config = SCALE_PRESETS[scale]
        ctx = context_for(config, seed=int(str(options["seed"])), password=str(options["password"]))
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run: would create "
                    f"{config.teachers} teachers, {config.students} students, "
                    f"{config.courses} courses, and full-lifecycle tasks."
                )
            )
            return
        summary = build_demo_dataset(ctx)
        self._print_summary(summary, config.scale)

    def _print_summary(self, summary: dict[str, object], scale: str) -> None:
        accounts = summary.get("accounts", {})
        assert isinstance(accounts, dict)
        admin_name = accounts.get("admin", "")
        teachers = sum(isinstance(t, str) for t in list(accounts.get("teachers", [])))
        self.stdout.write(self.style.SUCCESS(f"Demo dataset ({scale}) created."))
        self.stdout.write(self.style.HTTP_INFO(f"admin: {admin_name}"))
        self.stdout.write(self.style.HTTP_INFO(f"teachers created: {teachers}"))
        courses = summary.get("courses", [])
        if not isinstance(courses, list):
            courses = []
        self.stdout.write(
            self.style.HTTP_INFO(
                f"students: {summary.get('students', 0)}; "
                f"courses: {len(courses)}; "
                f"publications: {summary.get('publications', 0)}"
            )
        )
        entities = summary.get("entities", {})
        assert isinstance(entities, dict)
        for name, value in sorted(entities.items()):
            self.stdout.write(f"  {name}: {value}")
        statuses = summary.get("task_statuses", {})
        assert isinstance(statuses, dict)
        if statuses:
            self.stdout.write(self.style.MIGRATE_HEADING("Task status distribution:"))
            for value in sorted(statuses):
                self.stdout.write(f"  {value}: {statuses[value]}")
