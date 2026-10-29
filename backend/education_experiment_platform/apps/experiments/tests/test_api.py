import json
from unittest.mock import patch

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.tests.helpers import create_user
from apps.core.models import IdempotencyRecord
from apps.governance.models import Quota, RuntimeAdapter
from apps.labtemplates.models import ExperimentImage
from apps.provisioning.adapters import reset_fake_runtime
from apps.provisioning.services import execute_provisioning_job, start_provisioning

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


class DashboardWeeklyStudyTests(TestCase):
    """GET /me/dashboard aggregates per-day judge-run minutes for the week."""

    password = "ValidPassword!234"
    proxy_headers = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}

    def setUp(self) -> None:
        reset_fake_runtime()
        self.teacher, self.course, template_version, rubric_version = create_domain(
            suffix="p15-dashboard"
        )
        RuntimeAdapter.objects.filter(pk=template_version.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        enrollment = create_enrollment(self.course, suffix="p15-dashboard-student")
        self.student = enrollment.student
        quota_values = {
            "max_concurrent_instances": 10,
            "max_concurrent_starts": 10,
            "max_cpu_millicores": 20_000,
            "max_memory_mb": 40_000,
            "max_disk_gb": 200,
        }
        Quota.objects.create(
            scope_type=Quota.ScopeType.PLATFORM, scope_key="PLATFORM", **quota_values
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.COURSE,
            scope_key=f"COURSE:{self.course.public_id}",
            course=self.course,
            **quota_values,
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.USER,
            scope_key=f"USER:{self.student.public_id}",
            user=self.student,
            **quota_values,
        )
        publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=template_version,
            rubric_version=rubric_version,
            suffix="p15-dashboard",
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.teacher,
            expected_version=publication.row_version,
            selected_ids=[],
            context=context(self.teacher),
        )
        self.task = ExperimentTask.objects.get(publication=published, student=self.student)
        _, job = start_provisioning(
            task_id=self.task.public_id,
            actor=self.student,
            expected_version=self.task.row_version,
            context=context(self.student, "USER"),
        )
        execute_provisioning_job(job_id=job.public_id)
        self.task.refresh_from_db()

    def tearDown(self) -> None:
        reset_fake_runtime()

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
        from apps.workspaces.models import WorkspaceExecutionRun

        client = self._client(self.student.email)
        enter_status, enter_payload = self._post(
            client,
            f"/api/v2/tasks/{self.task.public_id}/enter",
            key="dash-enter",
            token="",
            body=None,
            if_match=self.task.row_version,
        )
        self.assertEqual(enter_status, 200, enter_payload)
        session = enter_payload["data"].get("session")
        assert isinstance(session, dict)
        token = str(session.get("workspace_token", ""))

        today = timezone.localtime(timezone.now())
        monday = (today - timezone.timedelta(days=today.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        last_monday = monday - timezone.timedelta(days=7)

        for key, started_at, duration_ms in (
            ("dash-run-1", monday + timezone.timedelta(hours=9), 120000),  # 本周 2 分钟
            ("dash-run-2", last_monday + timezone.timedelta(hours=9), 600000),  # 上周 10 分钟
        ):
            status, payload = self._post(
                client,
                f"/api/v2/tasks/{self.task.public_id}/execution-runs",
                key=key,
                token=token,
            )
            self.assertEqual(status, 201, payload)
            run_id = str(payload["data"].get("public_id"))
            WorkspaceExecutionRun.objects.filter(public_id=run_id).update(
                started_at=started_at,
                finished_at=started_at + timezone.timedelta(minutes=duration_ms // 60000),
                duration_ms=duration_ms,
                status=WorkspaceExecutionRun.Status.PASSED,
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
