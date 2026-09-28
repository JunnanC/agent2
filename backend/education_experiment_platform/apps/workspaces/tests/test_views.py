from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase, override_settings
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.tests.helpers import create_user
from apps.core.models import OutboxEvent
from apps.experiments.models import ExperimentTask
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.provisioning.models import ProvisioningJob

from ..models import WorkspaceSession
from ..views import _set_workspace_cookie


class WorkspaceCookieTests(SimpleTestCase):
    @override_settings(SESSION_COOKIE_SECURE=False, WORKSPACE_COOKIE_NAME="workspace_ticket")
    def test_workspace_cookie_is_available_over_local_http(self) -> None:
        response = _set_workspace_cookie(
            Response(), session_id="session-local", token="ticket", max_age=900
        )

        cookie = response.cookies["workspace_ticket"]
        self.assertFalse(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/workspace/session-local/")

    @override_settings(SESSION_COOKIE_SECURE=True, WORKSPACE_COOKIE_NAME="workspace_ticket")
    def test_workspace_cookie_remains_secure_for_https_deployments(self) -> None:
        response = _set_workspace_cookie(
            Response(), session_id="session-prod", token="ticket", max_age=900
        )

        self.assertTrue(response.cookies["workspace_ticket"]["secure"])


class WorkspaceInternalAuthorizationTests(SimpleTestCase):
    @override_settings(WORKSPACE_INTERNAL_KEY="internal-secret")
    def test_internal_authorization_does_not_require_browser_csrf(self) -> None:
        response = Client(enforce_csrf_checks=True).post(
            "/internal/workspace-authorize",
            HTTP_X_WORKSPACE_INTERNAL_KEY="wrong-secret",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "WORKSPACE_INTERNAL_DENIED")


class WorkbenchReadOnlyApiTests(TestCase):
    password = "ValidPassword!234"
    proxy_headers = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}

    def setUp(self) -> None:
        self.teacher, self.course, template_version, rubric_version = create_domain(
            suffix="p15-workbench"
        )
        enrollment = create_enrollment(self.course, suffix="p15-workbench-student")
        self.student = enrollment.student
        publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=template_version,
            rubric_version=rubric_version,
            suffix="p15-workbench",
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.teacher,
            expected_version=publication.row_version,
            selected_ids=[],
            context=type(
                "Context",
                (),
                {
                    "actor_ref": self.teacher.public_id,
                    "portal": "TEACHING",
                    "trace_id": "p15" * 8,
                },
            )(),
        )
        self.task = ExperimentTask.objects.get(publication=published, student=self.student)

    def _client(self, user: User, *, portal: str = "USER") -> Client:
        client = Client(enforce_csrf_checks=True)
        client.get(
            "/api/v2/auth/csrf",
            HTTP_X_PORTAL=portal,
            **self.proxy_headers,
        )
        csrf = str(client.cookies["csrftoken"].value)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": user.email, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL=portal,
                **self.proxy_headers,
            )
        self.assertEqual(response.status_code, 200, response.content)
        return client

    def test_user_workbench_is_scoped_and_has_no_side_effects_or_sensitive_fields(self) -> None:
        client = self._client(self.student)
        before = {
            "sessions": WorkspaceSession.objects.count(),
            "jobs": ProvisioningJob.objects.count(),
            "outbox": OutboxEvent.objects.count(),
        }
        response = client.get(
            f"/api/v2/tasks/{self.task.public_id}/workbench",
            HTTP_X_PORTAL="USER",
            **self.proxy_headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()["data"]
        self.assertEqual(payload["task"]["public_id"], self.task.public_id)
        self.assertIn("provisioning", payload)
        self.assertIn("submission", payload)
        serialized = response.content.decode()
        for forbidden in ("execution_spec", "workspace_token", "object_key", "container_id"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(
            before,
            {
                "sessions": WorkspaceSession.objects.count(),
                "jobs": ProvisioningJob.objects.count(),
                "outbox": OutboxEvent.objects.count(),
            },
        )

    def test_other_student_and_non_user_portal_cannot_read_workbench(self) -> None:
        stranger = create_user(
            email="p15-workbench-stranger@example.edu",
            username="p15-workbench-stranger",
            password=self.password,
        )
        response = self._client(stranger).get(
            f"/api/v2/tasks/{self.task.public_id}/workbench",
            HTTP_X_PORTAL="USER",
            **self.proxy_headers,
        )
        self.assertEqual(response.status_code, 404, response.content)
        teacher_response = self._client(self.teacher, portal="TEACHING").get(
            f"/api/v2/tasks/{self.task.public_id}/workbench",
            HTTP_X_PORTAL="TEACHING",
            **self.proxy_headers,
        )
        self.assertEqual(teacher_response.status_code, 403, teacher_response.content)
