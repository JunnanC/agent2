from unittest.mock import patch

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.tests.helpers import create_user
from apps.core.models import IdempotencyRecord
from apps.labtemplates.models import ExperimentImage

from ..models import (
    ExperimentTask,
    PublicationAudience,
    PublicationChapter,
    PublicationTask,
    TaskPublication,
)
from ..selectors import publication_for_course
from ..serializers import publication_data
from ..services import publish_publication
from .helpers import context, create_domain, create_draft_publication, create_enrollment

PROXY_HEADERS = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}


class ExperimentApiTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="p06-api"
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
            trace_id="p06-api-image".ljust(32, "0"),
            created_by=self.owner,
        )
        self.enrollment = create_enrollment(self.course, suffix="p06-api-student")
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
            HTTP_IDEMPOTENCY_KEY="p06-create-selected-draft",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["audience_mode"], "SELECTED")
        self.assertEqual(response.json()["data"]["status"], "DRAFT")

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
            HTTP_IDEMPOTENCY_KEY="p06-publish-selected-empty",
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
            IdempotencyRecord.objects.filter(idempotency_key="p06-publish-selected-empty").exists()
        )

        published = client.post(
            url,
            {"selected_enrollment_ids": [self.enrollment.public_id]},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="p06-publish-selected-valid",
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
            "HTTP_IDEMPOTENCY_KEY": "p06-publish-once",
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
            HTTP_IDEMPOTENCY_KEY="p06-nested-publish",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertTrue(data["template_digest"])
        self.assertTrue(data["publication_digest"])
        self.assertEqual(len(data["chapters"]), 1)
        self.assertEqual(len(data["chapters"][0]["tasks"]), 1)
        self.assertEqual(
            data["chapters"][0]["tasks"][0]["image_digest"],
            self.template_version.image.digest,
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
            email="p06-api-stranger@example.edu",
            username="p06-api-stranger",
            password=self.password,
        )
        client, _ = self._client(portal="USER", identifier=stranger.email)
        response = client.get(
            f"/api/v2/tasks/{task.public_id}",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 404, response.content)
