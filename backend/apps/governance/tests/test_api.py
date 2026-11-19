import time
from unittest.mock import patch

from django.test import Client, TestCase

from apps.accounts.tests.helpers import create_user
from apps.courses.services import ActorContext, apply_for_course, publish_course, review_enrollment

from ..models import RuntimeAdapter
from ..services import create_quota
from .helpers import create_governance_admin, create_governance_course, create_governance_teacher

PROXY_HEADERS = {
    "HTTP_X_PROXY_CONTEXT": "ingress-v1",
    "REMOTE_ADDR": "127.0.0.1",
}


class GovernanceApiTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        self.admin = create_governance_admin(suffix="api-admin")
        self.teacher = create_governance_teacher(suffix="api-teacher")
        self.student = create_user(
            email="api-student@example.edu",
            username="api-student",
            password=self.password,
            display_name="API Student",
        )

    def _login(self, client: Client, *, portal: str, identifier: str) -> str:
        client.get("/api/v2/auth/csrf", HTTP_X_PORTAL=portal, **PROXY_HEADERS)
        token = str(client.cookies["csrftoken"].value)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": identifier, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
                HTTP_X_PORTAL=portal,
                **PROXY_HEADERS,
            )
        self.assertEqual(response.status_code, 200, response.content)
        return token

    def test_platform_runtime_adapter_create_replays_and_user_cannot_read(self) -> None:
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        payload = {
            "code": "API-FAKE",
            "name": "API Fake Runtime",
            "runtime_type": "CONTAINER",
            "driver": "DOCKER_LOCAL",
            "config_ref": "runtime/api-fake",
            "reason": "API test",
        }
        response = admin_client.post(
            "/api/v2/platform/runtime-adapters",
            payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="runtime-create-api",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 201, response.content)
        replay = admin_client.post(
            "/api/v2/platform/runtime-adapters",
            payload,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="runtime-create-api",
            **PROXY_HEADERS,
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(RuntimeAdapter.objects.count(), 1)

        user_client = Client(enforce_csrf_checks=True)
        user_csrf = self._login(user_client, portal="USER", identifier=self.student.email)
        denied = user_client.get(
            "/api/v2/platform/runtime-adapters",
            HTTP_X_PORTAL="USER",
            HTTP_X_CSRFTOKEN=user_csrf,
            **PROXY_HEADERS,
        )
        self.assertEqual(denied.status_code, 403)

    def test_teaching_and_user_resource_summaries_use_real_course_scope(self) -> None:
        course = create_governance_course(self.teacher, code="GOV-API-001")
        course = publish_course(
            course_id=course.public_id,
            actor=self.teacher,
            expected_version=course.row_version,
            context=ActorContext(self.teacher.public_id, "TEACHING", "a" * 32),
        )
        enrollment = apply_for_course(
            course_id=course.public_id,
            student=self.student,
            application_message="api enrollment",
            context=ActorContext(self.student.public_id, "USER", "b" * 32),
        )
        review_enrollment(
            course_id=course.public_id, enrollment_id=enrollment.public_id,
            decision="APPROVE", note="api enrollment", actor=self.teacher,
            expected_version=enrollment.row_version,
            context=ActorContext(self.teacher.public_id, "TEACHING", "b" * 32),
        )
        admin_context = ActorContext(self.admin.public_id, "PLATFORM", "c" * 32)
        create_quota(
            actor=self.admin,
            scope_type="PLATFORM",
            course_id=None,
            user_id=None,
            values={"max_concurrent_instances": 5, "max_cpu_millicores": 10000},
            reason="api quota",
            context=admin_context,
        )
        teacher_client = Client(enforce_csrf_checks=True)
        teacher_csrf = self._login(teacher_client, portal="TEACHING", identifier=self.teacher.email)
        teaching = teacher_client.get(
            f"/api/v2/teaching/courses/{course.public_id}/governance",
            HTTP_X_PORTAL="TEACHING",
            HTTP_X_CSRFTOKEN=teacher_csrf,
            **PROXY_HEADERS,
        )
        self.assertEqual(teaching.status_code, 200, teaching.content)
        self.assertEqual(teaching.json()["data"]["course_id"], course.public_id)

        student_client = Client(enforce_csrf_checks=True)
        student_csrf = self._login(student_client, portal="USER", identifier=self.student.email)
        summary = student_client.get(
            f"/api/v2/me/courses/{course.public_id}/resource-summary",
            HTTP_X_PORTAL="USER",
            HTTP_X_CSRFTOKEN=student_csrf,
            **PROXY_HEADERS,
        )
        self.assertEqual(summary.status_code, 200, summary.content)
        self.assertEqual(summary.json()["data"]["course_id"], course.public_id)

        other = create_governance_course(self.teacher, code="GOV-API-002")
        hidden = student_client.get(
            f"/api/v2/me/courses/{other.public_id}/resource-summary",
            HTTP_X_PORTAL="USER",
            HTTP_X_CSRFTOKEN=student_csrf,
            **PROXY_HEADERS,
        )
        self.assertEqual(hidden.status_code, 404)

    def test_resource_profile_api_returns_request_and_limit_fields(self) -> None:
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        response = admin_client.post(
            "/api/v2/platform/resource-profiles",
            {
                "code": "API-RESOURCE-PROFILE",
                "name": "API resource profile",
                "runtime_type": "CONTAINER",
                "cpu_millicores": 500,
                "memory_mb": 1024,
                "cpu_request_millicores": 250,
                "cpu_limit_millicores": 750,
                "memory_request_mb": 512,
                "memory_limit_mb": 2048,
                "disk_gb": 10,
                "network_mode": "DENY_ALL",
                "cost_minor_per_hour": 0,
                "currency_code": "CNY",
                "reason": "API resource profile",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="resource-profile-api",
            **PROXY_HEADERS,
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            {
                key: response.json()["data"][key]
                for key in (
                    "cpu_request_millicores",
                    "cpu_limit_millicores",
                    "memory_request_mb",
                    "memory_limit_mb",
                )
            },
            {
                "cpu_request_millicores": 250,
                "cpu_limit_millicores": 750,
                "memory_request_mb": 512,
                "memory_limit_mb": 2048,
            },
        )

    def _create_enabled_fake_runtime(self, code: str) -> RuntimeAdapter:
        return RuntimeAdapter.objects.create(
            code=code,
            name="Fake runtime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            status=RuntimeAdapter.Status.ENABLED,
            config_ref="test/local",
        )

    def test_platform_image_resolve_enqueues_worker_task(self) -> None:
        self._create_enabled_fake_runtime("CATALOG-FAKE")
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        created = admin_client.post(
            "/api/v2/platform/images",
            {
                "registry": "docker.io",
                "repository": "library/ubuntu",
                "display_tag": "22.04",
                "risk_level": "LOW",
                "reason": "catalog import",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-catalog-create",
            **PROXY_HEADERS,
        )
        self.assertEqual(created.status_code, 201, created.content)
        image = created.json()["data"]
        self.assertIsNone(image["digest"])
        self.assertEqual(image["approval_status"], "PENDING")
        image_id = image["public_id"]

        with (
            patch("apps.governance.views.resolve_image_digest_task.delay") as delayed,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            accepted = admin_client.post(
                f"/api/v2/platform/images/{image_id}/resolve",
                {},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="PLATFORM",
                HTTP_IDEMPOTENCY_KEY="image-catalog-resolve",
                HTTP_IF_MATCH=created["ETag"],
                **PROXY_HEADERS,
            )
            self.assertEqual(accepted.status_code, 202, accepted.content)
            self.assertIsNone(accepted.json()["data"]["digest"])
        self.assertEqual(len(callbacks), 1)
        delayed.assert_called_once()
        self.assertEqual(delayed.call_args.args[0], image_id)
        self.assertTrue(delayed.call_args.args[1])

        replay = admin_client.post(
            f"/api/v2/platform/images/{image_id}/resolve",
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-catalog-resolve",
            HTTP_IF_MATCH=created["ETag"],
            **PROXY_HEADERS,
        )
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")

        stale_match = admin_client.post(
            f"/api/v2/platform/images/{image_id}/resolve",
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-catalog-resolve-stale",
            HTTP_IF_MATCH=f'"{999}"',
            **PROXY_HEADERS,
        )
        self.assertEqual(stale_match.status_code, 412, stale_match.content)

    def test_platform_image_rename_changes_display_name_only(self) -> None:
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        created = admin_client.post(
            "/api/v2/platform/images",
            {
                "registry": "docker.io",
                "repository": "library/python",
                "display_name": "标准编程环境",
                "display_tag": "3.13",
                "digest": "sha256:" + "e" * 64,
                "risk_level": "LOW",
                "reason": "rename test",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-rename-create",
            **PROXY_HEADERS,
        )
        self.assertEqual(created.status_code, 201, created.content)
        image_id = created.json()["data"]["public_id"]

        renamed = admin_client.post(
            f"/api/v2/platform/images/{image_id}/rename",
            {"display_name": "编程运行环境", "reason": "更易读的名称"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-rename-1",
            HTTP_IF_MATCH=created["ETag"],
            **PROXY_HEADERS,
        )
        self.assertEqual(renamed.status_code, 200, renamed.content)
        data = renamed.json()["data"]
        self.assertEqual(data["display_name"], "编程运行环境")
        self.assertEqual(data["digest"], "sha256:" + "e" * 64)
        self.assertEqual(data["repository"], "library/python")

    def test_platform_image_scan_and_approval_lifecycle(self) -> None:
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        created = admin_client.post(
            "/api/v2/platform/images",
            {
                "registry": "docker.io",
                "repository": "library/python",
                "display_tag": "3.13",
                "digest": "sha256:" + "f" * 64,
                "risk_level": "LOW",
                "reason": "catalog import with digest",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-lifecycle-create",
            **PROXY_HEADERS,
        )
        self.assertEqual(created.status_code, 201, created.content)
        image_id = created.json()["data"]["public_id"]

        blocked = admin_client.post(
            f"/api/v2/platform/images/{image_id}/decide",
            {"decision": "APPROVED"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-lifecycle-decide-scan",
            HTTP_IF_MATCH=created["ETag"],
            **PROXY_HEADERS,
        )
        self.assertEqual(blocked.status_code, 409, blocked.content)

        missing_ref = admin_client.patch(
            f"/api/v2/platform/images/{image_id}",
            {"scan_status": "CLEAN", "risk_level": "LOW", "reason": "clean scan"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IF_MATCH=created["ETag"],
            **PROXY_HEADERS,
        )
        self.assertEqual(missing_ref.status_code, 200, missing_ref.content)
        self.assertEqual(missing_ref.json()["data"]["scan_status"], "CLEAN")

        approved = admin_client.post(
            f"/api/v2/platform/images/{image_id}/decide",
            {"decision": "APPROVED"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-lifecycle-decide-approve",
            HTTP_IF_MATCH=missing_ref["ETag"],
            **PROXY_HEADERS,
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertEqual(approved.json()["data"]["approval_status"], "APPROVED")

    def test_platform_image_reresolve_enqueues_worker_task(self) -> None:
        self._create_enabled_fake_runtime("CATALOG-RERESOLVE-FAKE")
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        created = admin_client.post(
            "/api/v2/platform/images",
            {
                "registry": "docker.io",
                "repository": "library/ubuntu",
                "display_tag": "22.04",
                "digest": "sha256:" + "b" * 64,
                "risk_level": "LOW",
                "reason": "catalog import with digest",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-reresolve-create",
            **PROXY_HEADERS,
        )
        self.assertEqual(created.status_code, 201, created.content)
        image_id = created.json()["data"]["public_id"]

        with (
            patch("apps.governance.views.reresolve_image_digest_task.delay") as delayed,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            accepted = admin_client.post(
                f"/api/v2/platform/images/{image_id}/re-resolve",
                {"reason": "docker image rebuilt"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="PLATFORM",
                HTTP_IDEMPOTENCY_KEY="image-reresolve-dispatch",
                HTTP_IF_MATCH=created["ETag"],
                **PROXY_HEADERS,
            )
            self.assertEqual(accepted.status_code, 202, accepted.content)
        self.assertEqual(len(callbacks), 1)
        delayed.assert_called_once()
        self.assertEqual(delayed.call_args.args[0], image_id)

        unresolved = admin_client.post(
            "/api/v2/platform/images",
            {
                "registry": "docker.io",
                "repository": "library/python",
                "display_tag": "3.13",
                "risk_level": "LOW",
                "reason": "catalog import without digest",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-reresolve-create-unresolved",
            **PROXY_HEADERS,
        )
        self.assertEqual(unresolved.status_code, 201, unresolved.content)
        blocked = admin_client.post(
            f"/api/v2/platform/images/{unresolved.json()['data']['public_id']}/re-resolve",
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-reresolve-blocked",
            HTTP_IF_MATCH=unresolved["ETag"],
            **PROXY_HEADERS,
        )
        self.assertEqual(blocked.status_code, 409, blocked.content)
        self.assertEqual(
            blocked.json()["error"]["detail"], {"digest": "first_resolution_required"}
        )

    def test_platform_image_requires_recent_auth_for_resolve(self) -> None:
        self._create_enabled_fake_runtime("CATALOG-RECENT-FAKE")
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        created = admin_client.post(
            "/api/v2/platform/images",
            {
                "registry": "docker.io",
                "repository": "library/python",
                "display_tag": "3.13",
                "risk_level": "LOW",
                "reason": "catalog import",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="image-recent-create",
            **PROXY_HEADERS,
        )
        self.assertEqual(created.status_code, 201, created.content)
        image_id = created.json()["data"]["public_id"]
        with patch("apps.governance.views.time.time", return_value=int(time.time()) + 10_000):
            expired = admin_client.post(
                f"/api/v2/platform/images/{image_id}/resolve",
                {},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="PLATFORM",
                HTTP_IDEMPOTENCY_KEY="image-recent-resolve",
                HTTP_IF_MATCH=created["ETag"],
                **PROXY_HEADERS,
            )
        self.assertEqual(expired.status_code, 403, expired.content)
