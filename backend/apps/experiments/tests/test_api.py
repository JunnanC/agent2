import json
from unittest.mock import patch

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.utils import timezone

from apps.accounts.tests.helpers import create_user
from apps.core.models import IdempotencyRecord, OutboxEvent
from apps.courses.events import ENROLLMENT_STUDENT_DROPPED
from apps.courses.models import Enrollment
from apps.courses.ports import register_enrollment_blocker
from apps.courses.services import enrollment_exit_check
from apps.courses.tests.helpers import create_draft_course, create_teacher
from apps.labtemplates.models import ExperimentImage
from apps.notifications.models import Notification
from apps.notifications.services import consume_notification_event

from ..models import (
    ExperimentRetakeLink,
    ExperimentTask,
    PublicationAudience,
    PublicationChapter,
    PublicationTask,
    TaskPublication,
)
from ..selectors import publication_for_course
from ..serializers import publication_data
from ..services import (
    create_retake_publication,
    enrollment_task_blockers,
    execute_publication_assignment_chunk,
    publish_publication,
)
from .helpers import context, create_domain, create_draft_publication, create_enrollment

PROXY_HEADERS = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}


class ExperimentApiTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="publications-api"
        )
        ExperimentImage.objects.create(
            template_version=self.template_version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry=self.template_version.image.registry,
            repository=self.template_version.image.repository,
            requested_tag=self.template_version.image.display_tag or "stable",
            resolved_digest=self.template_version.image.digest,
            image_asset=self.template_version.image,
            status=ExperimentImage.Status.READY,
            scan_status=ExperimentImage.ScanStatus.CLEAN,
            trace_id="publications-api-image".ljust(32, "0"),
            created_by=self.owner,
        )
        self.enrollment = create_enrollment(self.course, suffix="publications-api-student")
        self.publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
        )

    def _client(self, *, portal: str, identifier: str) -> tuple[Client, str]:
        client = Client(enforce_csrf_checks=True)
        client.get(
            "/api/v2/auth/csrf",
            HTTP_X_PORTAL=portal,
            **PROXY_HEADERS,
        )
        csrf = str(client.cookies["csrftoken"].value)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": identifier, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL=portal,
                **PROXY_HEADERS,
            )
        self.assertEqual(response.status_code, 200, response.content)
        return client, csrf

    def test_selected_draft_can_be_created_before_choosing_students(self) -> None:
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        now = timezone.now()
        response = client.post(
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments",
            {
                "template_version_id": self.template_version.public_id,
                "rubric_version_id": self.rubric_version.public_id,
                "title": "Selected audience draft",
                "description": "Students will be selected when publishing",
                "audience_mode": "SELECTED",
                "late_enrollment_policy": "DO_NOT_ASSIGN",
                "window_start": now.isoformat(),
                "window_end": (now + timezone.timedelta(days=2)).isoformat(),
                "assignment_deadline": (now + timezone.timedelta(days=1)).isoformat(),
                "report_required": True,
                "review_mode": "MANUAL",
                "prerequisites": [],
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="publications-create-selected-draft",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["audience_mode"], "SELECTED")
        self.assertEqual(response.json()["data"]["status"], "DRAFT")

    def test_course_tasks_are_a_list_without_changing_progress_aggregate(self) -> None:
        client, _csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        response = client.get(
            f"/api/v2/teaching/courses/{self.course.public_id}/tasks",
            HTTP_X_PORTAL="TEACHING",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsInstance(response.json()["data"], list)
        aggregate = client.get(
            f"/api/v2/teaching/courses/{self.course.public_id}/progress",
            HTTP_X_PORTAL="TEACHING",
            **PROXY_HEADERS,
        )
        self.assertIn("task_counts", aggregate.json()["data"])

    def test_student_task_list_filters_course_id_and_keeps_legacy_alias(self) -> None:
        first_publication, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        first_task = ExperimentTask.objects.get(
            publication=first_publication, student=self.enrollment.student
        )
        with patch(
            "apps.labtemplates.tests.helpers.create_resources",
            return_value=(
                self.template_version.runtime_adapter,
                self.template_version.image,
                self.template_version.resource_profile,
            ),
        ):
            other_owner, other_course, other_template, other_rubric = create_domain(
                suffix="other-course-filter"
            )
        now = timezone.now()
        Enrollment.objects.create(
            course=other_course,
            student=self.enrollment.student,
            cycle_no=1,
            status=Enrollment.Status.ACTIVE,
            applied_at=now,
            activated_at=now,
        )
        other_publication = create_draft_publication(
            owner=other_owner,
            course=other_course,
            template_version=other_template,
            rubric_version=other_rubric,
        )
        publish_publication(
            course_id=other_course.public_id,
            publication_id=other_publication.public_id,
            actor=other_owner,
            expected_version=other_publication.row_version,
            selected_ids=[],
            context=context(other_owner),
        )

        client, _csrf = self._client(portal="USER", identifier=self.enrollment.student.email)
        for param in ("course_id", "course"):
            with self.subTest(param=param):
                response = client.get(
                    f"/api/v2/tasks?{param}={self.course.public_id}",
                    HTTP_X_PORTAL="USER",
                    **PROXY_HEADERS,
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    [row["public_id"] for row in response.json()["data"]],
                    [first_task.public_id],
                )
                self.assertEqual(response.json()["meta"]["total"], 1)
        unfiltered = client.get("/api/v2/tasks", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
        self.assertEqual(unfiltered.json()["meta"]["total"], 2)

        combined = client.get(
            f"/api/v2/tasks?course_id={self.course.public_id}&status=ASSIGNED&page_size=1",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(combined.status_code, 200, combined.content)
        self.assertEqual(
            [row["public_id"] for row in combined.json()["data"]], [first_task.public_id]
        )
        self.assertEqual(combined.json()["meta"]["total"], 1)

        invalid = client.get(
            "/api/v2/tasks?course_id=not-a-course",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(invalid.status_code, 200, invalid.content)
        self.assertEqual(invalid.json()["data"], [])
        self.assertEqual(invalid.json()["meta"]["total"], 0)

        conflicting = client.get(
            f"/api/v2/tasks?course_id={self.course.public_id}&course=not-a-course",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(conflicting.status_code, 400, conflicting.content)

    def test_retake_creation_links_tasks_and_allows_only_one_per_original_task(self) -> None:
        second_enrollment = create_enrollment(self.course, suffix="retake-second-student")
        source_publication, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        source_task = ExperimentTask.objects.get(
            publication=source_publication, student=self.enrollment.student
        )
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{source_publication.public_id}/retakes"
        )
        now = timezone.now()
        payload = {
            "selected_enrollment_ids": [self.enrollment.public_id, second_enrollment.public_id],
            "window_start": (now + timezone.timedelta(hours=1)).isoformat(),
            "window_end": (now + timezone.timedelta(days=2)).isoformat(),
        }
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "TEACHING",
            "HTTP_IDEMPOTENCY_KEY": "retake-create-once",
            **PROXY_HEADERS,
        }
        response = client.post(url, payload, content_type="application/json", **headers)
        self.assertEqual(response.status_code, 201, response.content)
        retake_publication_id = response.json()["data"]["public_id"]
        self.assertEqual(
            response.json()["data"]["retake_of_publication_id"], source_publication.public_id
        )
        link = ExperimentRetakeLink.objects.get(source_task=source_task)
        self.assertEqual(link.retake_publication.public_id, retake_publication_id)
        self.assertEqual(link.retake_task.student, source_task.student)
        self.assertEqual(link.retake_task.publication.public_id, retake_publication_id)
        self.assertEqual(
            ExperimentRetakeLink.objects.filter(retake_publication=link.retake_publication).count(),
            2,
        )

        replay = client.post(url, payload, content_type="application/json", **headers)
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(ExperimentRetakeLink.objects.filter(source_task=source_task).count(), 1)
        self.assertEqual(TaskPublication.objects.filter(retake_of=source_publication).count(), 1)

        repeat = client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="retake-create-twice",
            **PROXY_HEADERS,
        )
        self.assertEqual(repeat.status_code, 422, repeat.content)
        self.assertEqual(TaskPublication.objects.filter(retake_of=source_publication).count(), 1)

    def test_retake_creation_rejects_empty_student_list(self) -> None:
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        now = timezone.now()
        response = client.post(
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{self.publication.public_id}/retakes",
            {
                "selected_enrollment_ids": [],
                "window_start": (now + timezone.timedelta(hours=1)).isoformat(),
                "window_end": (now + timezone.timedelta(days=2)).isoformat(),
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="retake-empty-list",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(TaskPublication.objects.filter(retake_of=self.publication).exists())

    def test_retake_creation_rejects_active_student_without_source_task(self) -> None:
        source_publication, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        other_enrollment = create_enrollment(self.course, suffix="retake-no-source-task")
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        now = timezone.now()
        response = client.post(
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{source_publication.public_id}/retakes",
            {
                "selected_enrollment_ids": [other_enrollment.public_id],
                "window_start": (now + timezone.timedelta(hours=1)).isoformat(),
                "window_end": (now + timezone.timedelta(days=2)).isoformat(),
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="retake-without-source-task",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(
            response.json()["error"]["detail"]["selected_enrollment_ids"],
            "所选学生没有对应的原实验任务",
        )
        self.assertFalse(TaskPublication.objects.filter(retake_of=source_publication).exists())

    def test_retake_permissions_and_invalid_audience_leave_no_partial_records(self) -> None:
        source, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        outsider = create_teacher(suffix="retake-outsider")
        client, csrf = self._client(portal="TEACHING", identifier=outsider.email)
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{source.public_id}/retakes"
        )
        start = timezone.now() + timezone.timedelta(hours=1)
        end = start + timezone.timedelta(days=1)
        payload = {
            "selected_enrollment_ids": [self.enrollment.public_id],
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
        }
        forbidden = client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="retake-forbidden",
            **PROXY_HEADERS,
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.content)
        other_course = create_draft_course(outsider, code="RETAKE-OTHER")
        invalid_enrollment = create_enrollment(other_course, suffix="retake-other-student")
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        invalid = client.post(
            url,
            {
                **payload,
                "selected_enrollment_ids": [
                    self.enrollment.public_id,
                    invalid_enrollment.public_id,
                ],
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="retake-cross-course",
            **PROXY_HEADERS,
        )
        self.assertEqual(invalid.status_code, 422, invalid.content)
        with (
            patch(
                "apps.experiments.services._copy_publication_snapshots", side_effect=RuntimeError
            ),
            self.assertRaises(RuntimeError),
        ):
            create_retake_publication(
                course_id=self.course.public_id,
                publication_id=source.public_id,
                selected_enrollment_ids=[self.enrollment.public_id],
                window_start=start,
                window_end=end,
                actor=self.owner,
                context=context(self.owner),
            )
        self.assertFalse(TaskPublication.objects.filter(retake_of=source).exists())
        self.assertFalse(ExperimentRetakeLink.objects.exists())

    def test_async_retake_assignment_completes_the_task_link(self) -> None:
        with override_settings(PUBLICATION_SYNC_LIMIT=100):
            source_publication, _ = publish_publication(
                course_id=self.course.public_id,
                publication_id=self.publication.public_id,
                actor=self.owner,
                expected_version=self.publication.row_version,
                selected_ids=[],
                context=context(self.owner),
            )
        source_task = ExperimentTask.objects.get(
            publication=source_publication, student=self.enrollment.student
        )
        with override_settings(PUBLICATION_SYNC_LIMIT=0):
            retake_publication, status = create_retake_publication(
                course_id=self.course.public_id,
                publication_id=source_publication.public_id,
                selected_enrollment_ids=[self.enrollment.public_id],
                window_start=timezone.now() + timezone.timedelta(hours=1),
                window_end=timezone.now() + timezone.timedelta(days=2),
                actor=self.owner,
                context=context(self.owner),
            )
        self.assertEqual(status, 202)
        link = ExperimentRetakeLink.objects.get(source_task=source_task)
        self.assertIsNone(link.retake_task_id)

        execute_publication_assignment_chunk(
            publication_id=retake_publication.public_id,
            enrollment_ids=[self.enrollment.public_id],
            context=context(self.owner),
        )
        link.refresh_from_db()
        self.assertIsNotNone(link.retake_task_id)
        self.assertEqual(link.retake_task.student, source_task.student)

    def test_student_can_drop_with_pending_task_and_keeps_learning_history(self) -> None:
        register_enrollment_blocker(enrollment_task_blockers)
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        task = ExperimentTask.objects.get(publication=published, student=self.enrollment.student)
        self.assertEqual(
            enrollment_exit_check(enrollment=self.enrollment)[0].type, "UNFINISHED_TASK"
        )
        client, csrf = self._client(portal="USER", identifier=self.enrollment.student.email)
        path = f"/api/v2/me/enrollments/{self.enrollment.public_id}"
        before = client.get("/api/v2/tasks", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
        self.assertEqual(before.status_code, 200, before.content)
        self.assertEqual([row["public_id"] for row in before.json()["data"]], [task.public_id])
        for status in (
            ExperimentTask.Status.ASSIGNED,
            ExperimentTask.Status.IN_PROGRESS,
            ExperimentTask.Status.IN_PROGRESS,
            ExperimentTask.Status.UNDER_REVIEW,
        ):
            with self.subTest(status=status):
                ExperimentTask.objects.filter(pk=task.pk).update(status=status)
                check = client.get(f"{path}/drop-check", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
                self.assertEqual(check.status_code, 200, check.content)
                self.assertEqual(check.json()["data"], {"allowed": True, "blockers": []})
        headers = {
            "HTTP_X_PORTAL": "USER",
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_IDEMPOTENCY_KEY": "drop-with-pending",
            "HTTP_IF_MATCH": f'"{self.enrollment.row_version}"',
            **PROXY_HEADERS,
        }
        stale_headers = {
            **headers,
            "HTTP_IDEMPOTENCY_KEY": "drop-with-stale-version",
            "HTTP_IF_MATCH": f'"{self.enrollment.row_version + 1}"',
        }
        stale = client.post(
            f"{path}/drop",
            {"reason": "选课调整"},
            content_type="application/json",
            **stale_headers,
        )
        self.assertEqual(stale.status_code, 412, stale.content)
        self.assertEqual(stale.json()["error"]["code"], "ROW_VERSION_CONFLICT")
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "ACTIVE")
        dropped = client.post(
            f"{path}/drop",
            {"reason": "选课调整"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(dropped.status_code, 200, dropped.content)
        self.assertEqual(dropped.json()["data"]["status"], "DROPPED")
        replay = client.post(
            f"{path}/drop",
            {"reason": "选课调整"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(replay.status_code, 200, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        event = OutboxEvent.objects.get(
            event_type=ENROLLMENT_STUDENT_DROPPED,
            aggregate_ref=self.enrollment.public_id,
        )
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "DROPPED")
        self.assertFalse(Notification.objects.filter(kind=ENROLLMENT_STUDENT_DROPPED).exists())
        self.assertTrue(consume_notification_event(event_id=event.pk))
        notice = Notification.objects.get(kind=ENROLLMENT_STUDENT_DROPPED)
        self.assertEqual(notice.account, self.owner)
        self.assertEqual(notice.portal, "TEACHING")
        self.assertIn("退课已生效，无需教师审批", notice.body_masked)
        teacher, _ = self._client(portal="TEACHING", identifier=self.owner.email)
        inbox = teacher.get("/api/v2/notifications", HTTP_X_PORTAL="TEACHING", **PROXY_HEADERS)
        self.assertEqual(inbox.status_code, 200, inbox.content)
        self.assertEqual([row["public_id"] for row in inbox.json()["data"]], [notice.public_id])
        after = client.get("/api/v2/tasks", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
        self.assertEqual(after.status_code, 200, after.content)
        self.assertEqual(after.json()["data"], [])
        detail = client.get(
            f"/api/v2/tasks/{task.public_id}",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.json()["data"]["allowed_actions"], [])
        course = client.get(
            f"/api/v2/courses/{self.course.public_id}",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(course.status_code, 403, course.content)
        history = client.get("/api/v2/me/learning-history", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
        self.assertEqual(history.status_code, 200, history.content)
        experiments = [
            experiment
            for year in history.json()["data"]["years"]
            for term in year["terms"]
            for row in term["courses"]
            for experiment in row["experiments"]
        ]
        self.assertEqual([row["task_id"] for row in experiments], [task.public_id])
        task.refresh_from_db()
        self.assertEqual(task.status, ExperimentTask.Status.UNDER_REVIEW)

    def test_selected_publish_validates_then_freezes_chosen_students(self) -> None:
        publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="api-selected",
            audience_mode=TaskPublication.AudienceMode.SELECTED,
        )
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{publication.public_id}/publish"
        )
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "TEACHING",
            "HTTP_IF_MATCH": f'"{publication.row_version}"',
            **PROXY_HEADERS,
        }
        rejected = client.post(
            url,
            {"selected_enrollment_ids": []},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="publications-publish-selected-empty",
            **headers,
        )
        self.assertEqual(rejected.status_code, 422, rejected.content)
        self.assertEqual(
            rejected.json()["error"]["detail"]["selected_enrollment_ids"],
            "指定学生模式至少选择一名在读学生",
        )
        publication.refresh_from_db()
        self.assertEqual(publication.status, TaskPublication.Status.DRAFT)
        self.assertFalse(PublicationAudience.objects.filter(publication=publication).exists())
        self.assertFalse(ExperimentTask.objects.filter(publication=publication).exists())
        self.assertFalse(
            IdempotencyRecord.objects.filter(
                idempotency_key="publications-publish-selected-empty"
            ).exists()
        )

        published = client.post(
            url,
            {"selected_enrollment_ids": [self.enrollment.public_id]},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="publications-publish-selected-valid",
            **headers,
        )
        self.assertEqual(published.status_code, 201, published.content)
        self.assertEqual(published.json()["data"]["audience_count"], 1)
        self.assertEqual(
            ExperimentTask.objects.get(publication=publication).enrollment,
            self.enrollment,
        )

    def test_publish_api_returns_201_and_replays_without_duplicate_tasks(self) -> None:
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{self.publication.public_id}/publish"
        )
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "TEACHING",
            "HTTP_IDEMPOTENCY_KEY": "publications-publish-once",
            "HTTP_IF_MATCH": f'"{self.publication.row_version}"',
            **PROXY_HEADERS,
        }
        response = client.post(url, {}, content_type="application/json", **headers)
        self.assertEqual(response.status_code, 201, response.content)
        replay = client.post(url, {}, content_type="application/json", **headers)
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(ExperimentTask.objects.filter(publication=self.publication).count(), 1)

    def test_publish_api_returns_nested_immutable_publication_snapshot(self) -> None:
        client, csrf = self._client(portal="TEACHING", identifier=self.owner.email)
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/experiments/"
            f"{self.publication.public_id}/publish"
        )
        response = client.post(
            url,
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IF_MATCH=f'"{self.publication.row_version}"',
            HTTP_IDEMPOTENCY_KEY="publications-nested-publish",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertTrue(data["template_digest"])
        self.assertTrue(data["publication_digest"])
        self.assertEqual(len(data["chapters"]), 1)
        self.assertEqual(len(data["chapters"][0]["tasks"]), 1)
        self.assertEqual(
            data["chapters"][0]["tasks"][0]["image_digest"], "",
        )
        self.assertEqual(PublicationChapter.objects.filter(publication=self.publication).count(), 1)
        self.assertEqual(PublicationTask.objects.count(), 1)

    def test_publication_selector_preloads_nested_response_data(self) -> None:
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        item = publication_for_course(
            actor=self.owner,
            course_id=self.course.public_id,
            publication_id=published.public_id,
        )
        with CaptureQueriesContext(connection) as queries:
            data = publication_data(item)
        self.assertEqual(len(queries), 0)
        self.assertEqual(len(data["chapters"]), 1)
        self.assertEqual(len(data["chapters"][0]["tasks"]), 1)

    def test_student_scope_hides_another_students_task(self) -> None:
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        task = ExperimentTask.objects.get(publication=published)
        stranger = create_user(
            email="publications-api-stranger@example.edu",
            username="publications-api-stranger",
            password=self.password,
        )
        client, _ = self._client(portal="USER", identifier=stranger.email)
        response = client.get(
            f"/api/v2/tasks/{task.public_id}",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 404, response.content)


class DashboardWeeklyStudyTests(TestCase):
    """GET /me/dashboard aggregates per-day judge-run minutes for the week."""

    password = "ValidPassword!234"
    proxy_headers = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}

    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)
        self.teacher = self.owner

    def _client(self, identifier: str) -> Client:
        client = Client(enforce_csrf_checks=True)
        client.get("/api/v2/auth/csrf", HTTP_X_PORTAL="USER", **self.proxy_headers)
        csrf = str(client.cookies["csrftoken"].value)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": identifier, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="USER",
                **self.proxy_headers,
            )
        self.assertEqual(response.status_code, 200, response.content)
        return client

    def _csrf(self, client: Client) -> str:
        return str(client.cookies["csrftoken"].value)

    def _post(
        self,
        client: Client,
        path: str,
        *,
        key: str,
        token: str,
        body: dict[str, object] | None = None,
        if_match: int | None = None,
    ) -> tuple[int, dict[str, dict[str, object]]]:
        response = client.post(
            path,
            data=(json.dumps(body) if body else "{}"),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf(client),
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY=key,
            **({"HTTP_IF_MATCH": f'"{if_match}"'} if if_match is not None else {}),
            **({"HTTP_X_WORKSPACE_TOKEN": token} if token else {}),
            **self.proxy_headers,
        )
        try:
            return response.status_code, dict(response.json())
        except ValueError:
            return response.status_code, {}

    def test_dashboard_reports_weekly_study_minutes(self) -> None:
        from ..models import AssessmentRun
        from .test_assessment_workers import AssessmentWorkerTests

        source = AssessmentWorkerTests._run(self)
        client = self._client(self.student.email)
        today = timezone.localtime(timezone.now())
        monday = (today - timezone.timedelta(days=today.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        last_monday = monday - timezone.timedelta(days=7)

        for _key, started_at, duration_ms in (
            ("dash-run-1", monday + timezone.timedelta(hours=9), 120000),  # 本周 2 分钟
            ("dash-run-2", last_monday + timezone.timedelta(hours=9), 600000),  # 上周 10 分钟
        ):
            AssessmentRun.objects.create(
                task=self.task,
                question=source.question,
                snapshot=source.snapshot,
                started_at=started_at,
                finished_at=started_at + timezone.timedelta(milliseconds=duration_ms),
                duration_ms=duration_ms,
                status="COMPLETED",
            )

        response = client.get(
            "/api/v2/me/dashboard",
            HTTP_X_PORTAL="USER",
            **self.proxy_headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        weekly = response.json()["data"]["weekly_study"]
        self.assertEqual(weekly["total_minutes"], 2)
        self.assertEqual(weekly["last_week_minutes"], 10)
        self.assertEqual(weekly["minutes_by_day"][0], 2)
        self.assertTrue(weekly["has_records"])
        self.assertNotIn("workspace_token", response.content.decode())
