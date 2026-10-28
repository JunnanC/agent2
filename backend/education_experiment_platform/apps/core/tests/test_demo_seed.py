"""Demo dataset tests: full-lifecycle build, idempotent replay, and scoped purge."""

from __future__ import annotations

from collections import Counter
from typing import Final

from django.test import TestCase

from apps.accounts.models import User
from apps.core.demo import build_demo_dataset
from apps.core.demo.config import SMALL, context_for
from apps.core.demo.purge import purge_demo_data
from apps.courses.models import Course, Enrollment
from apps.experiments.models import ExperimentTask
from apps.reviews.models import Review

DEMO_PASSWORD: Final[str] = "Demo-Seed-Only-2026!"

COUNTED_MODELS: Final[dict[str, object]] = {
    "User": User,
    "Course": Course,
    "Enrollment": Enrollment,
    "ExperimentTask": ExperimentTask,
    "Review": Review,
}

CONTROL_USERNAME: Final[str] = "control-keeper"


class DemoDatasetTests(TestCase):
    def _run(self) -> dict[str, object]:
        context = context_for(SMALL, seed=42, password=DEMO_PASSWORD)
        return build_demo_dataset(context)

    def _snapshot(self) -> dict[str, int]:
        return {
            "User": User.objects.count(),
            "Course": Course.objects.count(),
            "Enrollment": Enrollment.objects.count(),
            "ExperimentTask": ExperimentTask.objects.count(),
            "Review": Review.objects.count(),
        }

    def test_small_dataset_reaches_full_lifecycle(self) -> None:
        summary = self._run()

        assert summary["students"] == SMALL.students
        assert len(summary["courses"]) == SMALL.courses  # type: ignore[arg-type]
        statuses = summary.get("task_statuses")
        assert isinstance(statuses, dict) and statuses

        tasks = ExperimentTask.objects.all()
        assert tasks.count() > 0
        valid = set(ExperimentTask.Status.values)
        for task in tasks:
            self.assertIn(task.status, valid)
        print("TASK STATUS:", dict(Counter(task.status for task in tasks)))

        self.assertGreater(Review.objects.count(), 0)
        self.assertGreater(
            ExperimentTask.objects.filter(
                status=ExperimentTask.Status.COMPLETED
            ).count(),
            0,
        )
        self.assertGreater(
            ExperimentTask.objects.filter(status=ExperimentTask.Status.UNDER_REVIEW).count(),
            0,
        )

    def test_replay_is_idempotent(self) -> None:
        self._run()
        before = self._snapshot()
        self._run()
        after = self._snapshot()
        self.assertEqual(before, after)

    def test_purge_keeps_non_demo_rows(self) -> None:
        keeper = User.objects.create(
            username=CONTROL_USERNAME,
            display_name="控制组课程",
            email="control-keeper@example.edu",
            account_status="ACTIVE",
            password="not-a-login",
        )
        control = Course.objects.create(
            code="CTRL-KEEP-01",
            title="控制组 课程",
            owner=keeper,
            status="PUBLISHED",
        )
        self._run()
        self.assertGreater(User.objects.filter(username__startswith="demo-").count(), 0)

        purge_demo_data()

        self.assertEqual(User.objects.filter(username__startswith="demo-").count(), 0)
        self.assertEqual(
            ExperimentTask.objects.filter(publication__course__code__startswith="DEMO-").count(),
            0,
        )
        remaining_course = Course.objects.filter(code="CTRL-KEEP-01").first()
        self.assertIsNotNone(remaining_course)
        self.assertIn(remaining_course, Course.objects.filter(code__startswith="CTRL-"))
        self.assertGreater(Course.objects.filter(code__startswith="CTRL-").count(), 0)
        del control, remaining_course

    def test_second_purge_is_safe(self) -> None:
        self._run()
        first = purge_demo_data()
        second = purge_demo_data()
        self.assertTrue(any(first.values()))
        leftover = {key: value for key, value in second.items() if value}
        self.assertEqual(leftover, {})
