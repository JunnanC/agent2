from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone

from ..grade_release import release_grades
from ..models import PublishedExperimentGrade, TaskPublication
from .helpers import create_domain, create_enrollment


@skipUnless(connection.vendor == "mysql", "requires real MySQL row locks")
class GradeReleaseConcurrencyTests(TransactionTestCase):
    def test_two_teachers_requests_publish_one_snapshot(self) -> None:
        with patch("apps.core.tasks.relay_outbox.apply_async"):
            owner, course, _template, _rubric = create_domain(suffix="release-race")
        enrollment = create_enrollment(course)
        now = timezone.now()
        publication = TaskPublication.objects.create(
            course=course, title="Publication with a pending student",
            window_start=now - timedelta(hours=2), window_end=now - timedelta(hours=1),
            audience_mode="ALL_ACTIVE", review_mode="MANUAL", status="PUBLISHED",
            report_required=True,
            experiment_spec={"part_maxima": {"CHOICE": "0", "PROGRAMMING": "0", "REPORT": "25"}},
        )
        publication.tasks.create(
            course=course, enrollment=enrollment, student=enrollment.student,
            effective_deadline=publication.window_end, runtime_type="CONTAINER",
        )
        gate = Barrier(2)

        def publish() -> object:
            close_old_connections()
            try:
                gate.wait(timeout=10)
                return release_grades(publication, actor=owner)["grades_published_at"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.map(lambda _: publish(), range(2))
        assert first is not None and first == second
        assert PublishedExperimentGrade.objects.count() == 1
