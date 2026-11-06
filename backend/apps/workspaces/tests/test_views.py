import json
from typing import cast
from unittest.mock import patch

from django.test import Client, SimpleTestCase, TestCase, override_settings
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.tests.helpers import create_user
from apps.core.models import ObjectAsset, OutboxEvent
from apps.courses.services import ActorContext
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import Quota, RuntimeAdapter
from apps.provisioning.adapters import reset_fake_runtime
from apps.provisioning.models import ProvisioningJob
from apps.provisioning.services import execute_provisioning_job, start_provisioning

from ..models import WorkspaceExecutionRun, WorkspaceSession
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


class WorkbenchApiBase(TestCase):
    password = "ValidPassword!234"
    proxy_headers = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}

    def setUp(self) -> None:
        text = patch("apps.workspaces.workbench.asset_text", return_value=None)
        text.start()
        self.addCleanup(text.stop)
        reset_fake_runtime()
        self.teacher, self.course, template_version, rubric_version = create_domain(
            suffix="workbench-workbench"
        )
        RuntimeAdapter.objects.filter(pk=template_version.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        enrollment = create_enrollment(self.course, suffix="workbench-workbench-student")
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
            suffix="workbench-workbench",
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.teacher,
            expected_version=publication.row_version,
            selected_ids=[],
            context=ActorContext(self.teacher.public_id, "TEACHING", "workbench".ljust(32, "0")),
        )
        self.task = published.tasks.get(student=self.student)
        _, job = start_provisioning(
            task_id=self.task.public_id,
            actor=self.student,
            expected_version=self.task.row_version,
            context=ActorContext(self.student.public_id, "USER", "s" * 32),
        )
        execute_provisioning_job(job_id=job.public_id)
        self.task.refresh_from_db()

    def tearDown(self) -> None:
        reset_fake_runtime()

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

    def _csrf(self, client: Client) -> str:
        return str(client.cookies["csrftoken"].value)

    def _enter_task(self, client: Client, *, key: str) -> dict[str, object]:
        """Enter the task over REST; returns the ``data`` payload."""
        response = client.post(
            f"/api/v2/tasks/{self.task.public_id}/enter",
            data="{}",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf(client),
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY=key,
            HTTP_IF_MATCH=f'"{self.task.row_version}"',
            **self.proxy_headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return dict(response.json()["data"])

    def _post_execution_run(
        self,
        client: Client,
        *,
        key: str,
        token: str | None = None,
    ) -> tuple[int, dict[str, dict[str, object]]]:
        response = client.post(
            f"/api/v2/tasks/{self.task.public_id}/execution-runs",
            data="{}",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf(client),
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY=key,
            **({"HTTP_X_WORKSPACE_TOKEN": token} if token else {}),
            **self.proxy_headers,
        )
        try:
            return response.status_code, dict(response.json())
        except ValueError:
            return response.status_code, {}


class WorkbenchReadOnlyApiTests(WorkbenchApiBase):
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
        self.assertEqual(
            payload["workspace"],
            {
                "mode": "READ_ONLY",
                "entrypoint": "main.py",
                "language": "python",
                "language_policy": {},
                "toolchain_version": None,
                "capture_supported": False,
                "last_synchronized_version": 0,
                "last_synchronized_snapshot_id": None,
                "active_storage_job": None,
            },
        )
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
            email="workbench-workbench-stranger@example.edu",
            username="workbench-workbench-stranger",
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


class ExecutionRunApiTests(WorkbenchApiBase):
    def test_detail_returns_public_outputs_but_never_hidden_inputs_or_logs(self) -> None:
        client = self._client(self.student)
        data = self._enter_task(client, key="public-output-enter")
        session = cast(dict[str, str], data["session"])
        status, payload = self._post_execution_run(
            client, key="public-output-run", token=session["workspace_token"]
        )
        self.assertEqual(status, 201)
        run_data = cast(dict[str, str], payload["data"])
        run = WorkspaceExecutionRun.objects.get(public_id=run_data["public_id"])
        asset = ObjectAsset.objects.create(
            bucket="private", object_key="test-result", digest_sha256="a" * 64,
            size_bytes=1, purpose="TEST_REPORT", owner_type="WORKSPACE_EXECUTION",
            owner_ref=run.public_id, scan_status="CLEAN",
        )
        WorkspaceExecutionRun.objects.filter(pk=run.pk).update(test_report_asset=asset)
        report = {"status": "FAILED", "results": [
            {"status": "FAILED", "input": f"input-{i}", "expected": f"expected-{i}",
             "stdout": f"actual-{i}", "stderr": f"log-{i}"} for i in range(5)
        ]}
        with patch("apps.workspaces.presentation.asset_text", return_value=json.dumps(report)):
            response = client.get(
                f"/api/v2/tasks/{self.task.public_id}/execution-runs/{run.public_id}",
                HTTP_X_PORTAL="USER", HTTP_X_WORKSPACE_TOKEN=session["workspace_token"],
                **self.proxy_headers,
            )
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()["data"]["test_cases"]
        self.assertEqual(result[0]["expected"], "expected-0")
        self.assertEqual(result[3], {"status": "FAILED", "hidden": True})
        for private in ("input-3", "expected-3", "actual-3", "log-3"):
            self.assertNotIn(private, response.content.decode())

    def test_enter_then_create_run_creates_passed_execution(self) -> None:
        client = self._client(self.student)
        data = self._enter_task(client, key="rest-enter-run-1")
        session = data.get("session")
        assert isinstance(session, dict)
        token = str(session.get("workspace_token", ""))
        self.assertTrue(token)
        session_id = str(session.get("public_id", ""))
        task_payload = data.get("task")
        assert isinstance(task_payload, dict)
        self.assertEqual(str(task_payload.get("status")), "IN_PROGRESS")

        status, payload = self._post_execution_run(client, key="rest-exec-run-1", token=token)
        self.assertEqual(status, 201, payload)
        run = payload["data"]
        assert isinstance(run, dict)
        self.assertEqual(run.get("status"), "PASSED")
        self.assertEqual(run.get("result_summary"), "PASSED by FakeRuntime")
        self.assertEqual(run.get("session_id"), session_id)
        execution_id = str(run.get("public_id"))

        replay_status, replay_payload = self._post_execution_run(
            client, key="rest-exec-run-1", token=token
        )
        self.assertEqual(replay_status, 201, replay_payload)
        self.assertEqual(replay_payload["data"].get("public_id"), execution_id)

        list_response = client.get(
            f"/api/v2/tasks/{self.task.public_id}/execution-runs",
            HTTP_X_PORTAL="USER",
            HTTP_X_WORKSPACE_TOKEN=token,
            **self.proxy_headers,
        )
        self.assertEqual(list_response.status_code, 200, list_response.content)
        items = list_response.json()["data"]["items"]
        self.assertEqual([row["public_id"] for row in items], [execution_id])

    def test_create_run_requires_workspace_token(self) -> None:
        client = self._client(self.student)
        self._enter_task(client, key="rest-enter-run-2")
        status, payload = self._post_execution_run(client, key="rest-exec-run-2")
        self.assertEqual(status, 401, payload)
        self.assertEqual(payload["error"].get("code"), "WORKSPACE_SESSION_INVALID")

        forged_status, forged_payload = self._post_execution_run(
            client, key="rest-exec-run-3", token="forged-token"
        )
        self.assertEqual(forged_status, 401, forged_payload)
        self.assertEqual(
            forged_payload["error"].get("code"), "WORKSPACE_SESSION_INVALID"
        )
