from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from apps.analytics.class_grade_views import TeachingClassGradesExportView
from apps.analytics.class_grades import ReleasedExperiment, ReleasedResult, analyze_released_grades

DEADLINE = datetime(2026, 10, 1, tzinfo=UTC)
WEEK = timedelta(days=7)
EXPERIMENTS = [
    ReleasedExperiment(key, title, DEADLINE + offset, DEADLINE + offset + WEEK)
    for key, title, offset in [
        ("P1", "知识点", WEEK * 0),
        ("P2", "编程", WEEK),
        ("P3", "报告", WEEK * 2),
    ]
]


def row(
    pub,
    student,
    score,
    max_score,
    *,
    kind="CHOICE",
    joined=DEADLINE - WEEK,
    status="SUBMITTED",
    expected=True,
):
    return ReleasedResult(
        pub,
        student,
        f"虚构学生 {student}",
        f"{pub}-{student}",
        joined,
        expected,
        status,
        {kind: (Decimal(score), Decimal(max_score))},
    )


RESULTS = [
    row("P1", "A", 20, 20),
    row("P2", "A", 40, 80, kind="PROGRAMMING"),
    row("P1", "B", 20, 20, joined=DEADLINE + timedelta(days=1)),
    row(
        "P2",
        "B",
        1,
        80,
        kind="PROGRAMMING",
        joined=DEADLINE + timedelta(days=1),
        status="NOT_SUBMITTED",
    ),
    row("P3", "B", 0, 50, kind="REPORT", expected=False),
    row("P1", "X", 0, 20, joined=None),
]


class ReleasedGradeTests(SimpleTestCase):
    def test_weights_missing_late_enrollment_and_unmatched(self):
        report = analyze_released_grades(EXPERIMENTS, RESULTS, set(), [])
        first, second = report["students"]
        self.assertEqual((first["rank"], first["percent"], first["failed"]), (1, 60, False))
        self.assertEqual((second["rank"], second["percent"], second["max_score"]), (2, 0, 80))
        self.assertEqual(report["summary"]["completion_rate"], 66.67)
        self.assertEqual(report["summary"]["failure_rate"], 50)
        self.assertEqual(report["results"][-1]["status"], "NOT_SUBMITTED")
        self.assertEqual(
            report["awaiting_confirmation"],
            [{"task_id": "P1-X", "reason": "ENROLLMENT_UNCONFIRMED"}],
        )
        self.assertTrue(report["parts"][1]["suggestion"])

    def test_empty_releases_are_not_zero_grades(self):
        report = analyze_released_grades([], [], set(), [])
        self.assertIsNone(report["summary"]["percent"])
        self.assertIsNone(report["summary"]["completion_rate"])
        self.assertIsNone(report["summary"]["failure_rate"])

    def test_exports_one_multiple_and_all_against_same_aggregation(self):
        import csv
        from io import StringIO
        from unittest.mock import MagicMock

        view = TeachingClassGradesExportView()
        for ids, expected_experiments, first_max in [
            ("P2", 1, 80),
            ("P1,P2", 2, 100),
            ("", 3, 100),
        ]:
            request = view.initialize_request(
                APIRequestFactory().get("/", {"publication_ids": ids})
            )
            request.user = MagicMock()
            with (
                patch("apps.analytics.class_grade_views.teaching_course", return_value=MagicMock()),
                patch(
                    "apps.analytics.class_grade_views.current_released_results",
                    return_value=(EXPERIMENTS, RESULTS, []),
                ),
            ):
                csv_output = view.get(request, "class-A").data["data"]["csv"]
            rows = list(csv.reader(StringIO(csv_output)))
            self.assertEqual(
                len([
                    r
                    for r in rows
                    if len(r) == 5
                    and r[0] in {"P1", "P2", "P3"}
                    and r[1] in {e.title for e in EXPERIMENTS}
                ]),
                expected_experiments,
            )
            self.assertEqual(float(next(r for r in rows if r[0] == "A")[5]), first_max)
            self.assertIn("未提交", csv_output)
