from unittest.mock import patch

from django.test import Client, TestCase

from apps.accounts.tests.helpers import create_user
from apps.courses.services import ActorContext, apply_for_course, publish_course

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
            "driver": "FAKE",
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
        apply_for_course(
            course_id=course.public_id,
            student=self.student,
            application_message="api enrollment",
            context=ActorContext(self.student.public_id, "USER", "b" * 32),
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
