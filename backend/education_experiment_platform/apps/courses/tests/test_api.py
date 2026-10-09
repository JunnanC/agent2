from unittest.mock import patch

import yaml
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user, grant_admin, grant_teacher

from ..models import Course, Enrollment
from ..services import current_academic_term

PROXY_HEADERS = {
    "HTTP_X_PROXY_CONTEXT": "ingress-v1",
    "REMOTE_ADDR": "127.0.0.1",
}


class CourseApiTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        self.teacher = create_user(
            email="teacher@example.edu",
            username="teacher",
            password=self.password,
        )
        grant_teacher(self.teacher)
        self.student = create_user(
            email="student@example.edu",
            username="student",
            password=self.password,
        )
        self.admin = create_user(
            email="admin@example.edu",
            username="admin",
            password=self.password,
        )
        grant_admin(self.admin)
        self.term = current_academic_term()

    def _login(self, client: Client, *, portal: str, identifier: str) -> str:
        client.get(
            "/api/v2/auth/csrf",
            HTTP_X_PORTAL=portal,
            **PROXY_HEADERS,
        )
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

    def _create_and_publish(self, client: Client, csrf: str) -> dict[str, object]:
        create = client.post(
            "/api/v2/teaching/courses",
            {
                "code": "COURSE-API-001",
                "title": "API Course",
                "summary": "Summary",
                "visibility": "PUBLIC",
                "enrollment_mode": "OPEN",
                "capacity": 1,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="course-create-api",
            **PROXY_HEADERS,
        )
        self.assertEqual(create.status_code, 201, create.content)
        course = create.json()["data"]
        publish = client.post(
            f"/api/v2/teaching/courses/{course['public_id']}/publish",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="TEACHING",
            HTTP_IDEMPOTENCY_KEY="course-publish-api",
            HTTP_IF_MATCH=create["ETag"],
            **PROXY_HEADERS,
        )
        self.assertEqual(publish.status_code, 200, publish.content)
        return publish.json()["data"]

    def test_teacher_course_and_student_enrollment_real_api(self) -> None:
        teacher_client = Client(enforce_csrf_checks=True)
        teacher_csrf = self._login(
            teacher_client,
            portal="TEACHING",
            identifier=self.teacher.email,
        )
        course = self._create_and_publish(teacher_client, teacher_csrf)

        student_client = Client(enforce_csrf_checks=True)
        student_csrf = self._login(
            student_client,
            portal="USER",
            identifier=self.student.email,
        )
        catalog = student_client.get(
            "/api/v2/courses",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json()["data"][0]["public_id"], course["public_id"])
        apply = student_client.post(
            f"/api/v2/courses/{course['public_id']}/enrollments",
            {"application_message": "join"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=student_csrf,
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY="enroll-api",
            **PROXY_HEADERS,
        )
        self.assertEqual(apply.status_code, 201, apply.content)
        self.assertEqual(apply.json()["data"]["status"], Enrollment.Status.ACTIVE)
        replay = student_client.post(
            f"/api/v2/courses/{course['public_id']}/enrollments",
            {"application_message": "join"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=student_csrf,
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY="enroll-api",
            **PROXY_HEADERS,
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_context_returns_current_term_and_role_aware_courses(self) -> None:
        teacher_client = Client(enforce_csrf_checks=True)
        teacher_csrf = self._login(teacher_client, portal="TEACHING", identifier=self.teacher.email)
        course = self._create_and_publish(teacher_client, teacher_csrf)
        Course.objects.filter(public_id=course["public_id"]).update(term=self.term)

        response = teacher_client.get("/api/v2/context", HTTP_X_PORTAL="TEACHING", **PROXY_HEADERS)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["user_role"], "TEACHER")
        self.assertEqual(response.json()["data"]["current_term"]["code"], self.term.code)
        self.assertEqual(response.json()["data"]["courses"][0]["staff_role"], "OWNER")
        self.assertEqual(response.json()["data"]["courses"][0]["id"], course["public_id"])
        self.assertEqual(response.json()["data"]["courses"][0]["code"], course["code"])

        Enrollment.objects.create(
            course=Course.objects.get(public_id=course["public_id"]),
            student=self.student,
            cycle_no=1,
            status=Enrollment.Status.ACTIVE,
            applied_at=timezone.now(),
        )
        student_client = Client(enforce_csrf_checks=True)
        self._login(student_client, portal="USER", identifier=self.student.email)
        student_context = student_client.get(
            "/api/v2/context", HTTP_X_PORTAL="USER", **PROXY_HEADERS
        )
        self.assertEqual(student_context.status_code, 200, student_context.content)
        self.assertEqual(student_context.json()["data"]["user_role"], "STUDENT")
        self.assertEqual(student_context.json()["data"]["courses"][0]["enrollment_role"], "STUDENT")

        teacher_context = teacher_client.get(
            "/api/v2/context", HTTP_X_PORTAL="TEACHING", **PROXY_HEADERS
        )
        self.assertEqual(teacher_context.status_code, 200, teacher_context.content)
        self.assertEqual(teacher_context.json()["data"]["user_role"], "TEACHER")
        self.assertEqual(teacher_context.json()["data"]["courses"][0]["id"], course["public_id"])
        self.assertNotIn("enrollment_role", teacher_context.json()["data"]["courses"][0])

    def test_context_requires_authentication(self) -> None:
        response = Client().get("/api/v2/context", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
        self.assertIn(response.status_code, (401, 403))

    def test_platform_context_returns_role_without_course_memberships(self) -> None:
        admin_client = Client(enforce_csrf_checks=True)
        self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)

        response = admin_client.get(
            "/api/v2/context", HTTP_X_PORTAL="PLATFORM", **PROXY_HEADERS
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["user_role"], "PLATFORM_ADMIN")
        self.assertEqual(response.json()["data"]["current_term"]["code"], self.term.code)
        self.assertEqual(response.json()["data"]["courses"], [])

    def test_platform_freeze_shell_never_changes_course(self) -> None:
        teacher_client = Client(enforce_csrf_checks=True)
        teacher_csrf = self._login(
            teacher_client,
            portal="TEACHING",
            identifier=self.teacher.email,
        )
        course = self._create_and_publish(teacher_client, teacher_csrf)
        admin_client = Client(enforce_csrf_checks=True)
        csrf = self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)

        response = admin_client.post(
            f"/api/v2/platform/courses/{course['public_id']}/freeze",
            {"reason": "compliance check"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="PLATFORM",
            HTTP_IDEMPOTENCY_KEY="freeze-shell",
            **PROXY_HEADERS,
        )

        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["error"]["code"], "FEATURE_NOT_AVAILABLE")
        self.assertEqual(Course.objects.get(public_id=course["public_id"]).status, "PUBLISHED")

    def test_openapi_exposes_course_portal_groups(self) -> None:
        response = Client().get(
            "/api/v2/schema",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        document = yaml.safe_load(response.content)
        expected = {
            ("/api/v2/courses", "get"): ("courses", ["USER"]),
            ("/api/v2/me/enrollments", "get"): ("courses", ["USER"]),
            ("/api/v2/teaching/courses", "post"): (
                "teaching-courses",
                ["TEACHING"],
            ),
            ("/api/v2/teaching/courses/{course_id}/enrollments", "get"): (
                "teaching-enrollments",
                ["TEACHING"],
            ),
            ("/api/v2/platform/courses", "get"): (
                "platform-governance",
                ["PLATFORM"],
            ),
        }
        for (path, method), (tag, portals) in expected.items():
            operation = document["paths"][path][method]
            self.assertIn(tag, operation["tags"])
            self.assertEqual(operation["x-portals"], portals)
