from datetime import timedelta
from unittest.mock import patch

import yaml
from django.http import HttpResponse
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user, grant_admin, grant_teacher

from ..content_services import create_invitation
from ..models import AcademicTerm, Course, CourseSchedule, Enrollment, Invitation
from ..services import ActorContext, current_academic_term

PROXY_HEADERS = {
    "HTTP_X_PROXY_CONTEXT": "ingress-v1",
    "REMOTE_ADDR": "127.0.0.1",
}


class CourseApiTests(TestCase):
    password = "ValidPassword!234"

    def test_platform_can_read_teaching_class_rosters_without_changing_enrollments(self) -> None:
        from .helpers import create_draft_course

        courses = [create_draft_course(self.teacher, code=f"ROSTER-{index}") for index in (1, 2)]
        for course in courses:
            Course.objects.filter(pk=course.pk).update(status="PUBLISHED")
            Enrollment.objects.create(
                course=course,
                student=self.student,
                cycle_no=1,
                status="ACTIVE",
                applied_at=timezone.now(),
            )
        admin_client = Client()
        self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)
        for course in courses:
            response = admin_client.get(
                f"/api/v2/platform/courses/{course.public_id}/members",
                HTTP_X_PORTAL="PLATFORM",
                **PROXY_HEADERS,
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["data"]["class"]["public_id"], course.public_id)
            self.assertEqual(
                [item["student_id"] for item in response.json()["data"]["members"]],
                [self.student.public_id],
            )
        student_client = Client()
        self._login(student_client, portal="USER", identifier=self.student.email)
        response = student_client.get(
            f"/api/v2/platform/courses/{courses[0].public_id}/members",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            Enrollment.objects.filter(student=self.student, status="ACTIVE").count(),
            2,
        )

    def _code(self, course_id):
        _, code = create_invitation(
            course_id=course_id,
            actor=self.teacher,
            max_uses=100,
            expires_at=timezone.now() + timedelta(days=1),
            context=ActorContext(self.teacher.public_id, "TEACHING", "a" * 32),
        )
        return code

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

    def test_invitation_resolution_returns_published_course_and_rejects_invalid_code(self) -> None:
        teacher_client = Client(enforce_csrf_checks=True)
        csrf = self._login(teacher_client, portal="TEACHING", identifier=self.teacher.email)
        data = self._create_and_publish(teacher_client, csrf)
        course = Course.objects.get(public_id=data["public_id"])
        invitation, code = create_invitation(
            course_id=course.public_id,
            actor=self.teacher,
            max_uses=1,
            expires_at=timezone.now() + timedelta(days=1),
            context=ActorContext(self.teacher.public_id, "TEACHING", "i" * 32),
        )
        student_client = Client(enforce_csrf_checks=True)
        self._login(student_client, portal="USER", identifier=self.student.email)
        endpoint = "/api/v2/courses/invitations/resolve"
        response = student_client.get(
            endpoint, {"code": code}, HTTP_X_PORTAL="USER", **PROXY_HEADERS
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["data"]["public_id"], course.public_id)
        invitation.refresh_from_db()
        self.assertEqual(invitation.used_count, 0)
        Invitation.objects.filter(pk=invitation.pk).update(used_count=1)
        for value in (code, "invalid-code"):
            response = student_client.get(
                endpoint, {"code": value}, HTTP_X_PORTAL="USER", **PROXY_HEADERS
            )
            self.assertEqual(response.status_code, 400, response.content)

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
        invitation_code = self._code(course["public_id"])
        apply = student_client.post(
            f"/api/v2/courses/{course['public_id']}/enrollments",
            {"application_message": "join", "invitation_code": invitation_code},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=student_csrf,
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY="enroll-api",
            **PROXY_HEADERS,
        )
        self.assertEqual(apply.status_code, 201, apply.content)
        self.assertEqual(apply.json()["data"]["status"], Enrollment.Status.PENDING)
        replay = student_client.post(
            f"/api/v2/courses/{course['public_id']}/enrollments",
            {"application_message": "join", "invitation_code": invitation_code},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=student_csrf,
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY="enroll-api",
            **PROXY_HEADERS,
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_term_timetables_and_platform_drill_down(self) -> None:
        from apps.courses.tests.helpers import create_draft_course, create_teacher

        other = create_teacher(suffix="another-timetable-teacher")
        current = create_draft_course(self.teacher, code="DS-01")
        unrelated = create_draft_course(other, code="DS-02")
        past = create_draft_course(self.teacher, code="OLD-DS-01")
        now = timezone.now()
        old_term = AcademicTerm.objects.create(
            code="FIXTURE-OLD",
            name="往期学期",
            starts_at=now - timedelta(days=100),
            ends_at=now - timedelta(days=10),
            status=AcademicTerm.Status.CLOSED,
        )
        Course.objects.filter(pk=past.pk).update(term=old_term, status=Course.Status.ARCHIVED)
        for course in (current, unrelated, past):
            CourseSchedule.objects.create(course=course, weekday=1, start_period=1, end_period=2)
        Enrollment.objects.create(
            course=current,
            student=self.student,
            cycle_no=1,
            status=Enrollment.Status.PENDING,
            applied_at=now,
        )
        Enrollment.objects.create(
            course=past,
            student=self.student,
            cycle_no=1,
            status=Enrollment.Status.ACTIVE,
            applied_at=now,
            activated_at=now,
        )
        clients = {}
        for role, actor in (
            ("TEACHING", self.teacher),
            ("USER", self.student),
            ("PLATFORM", self.admin),
        ):
            clients[role] = Client()
            self._login(clients[role], portal=role, identifier=actor.email)

        def get(role, path, params=None):
            return clients[role].get(
                f"/api/v2/{path}", params or {}, HTTP_X_PORTAL=role, **PROXY_HEADERS
            )

        def ids(response):
            self.assertEqual(response.status_code, 200, response.content)
            return [row["course_id"] for row in response.json()["data"]["classes"]]

        self.assertEqual(ids(get("TEACHING", "teaching/timetable")), [current.public_id])
        self.assertEqual(ids(get("USER", "me/timetable")), [])
        self.assertEqual(
            ids(get("USER", "me/timetable", {"term_id": old_term.public_id})), [past.public_id]
        )
        self.assertEqual(get("USER", "me/timetable-imports").status_code, 404)
        endpoint = "platform/term-classes"
        self.assertEqual(get("USER", endpoint).status_code, 403)
        self.assertEqual(get("TEACHING", endpoint).status_code, 403)
        self.assertEqual(
            ids(
                get("PLATFORM", endpoint, {"role": "TEACHER", "person_id": self.teacher.public_id})
            ),
            [current.public_id],
        )
        self.assertEqual(
            ids(
                get(
                    "PLATFORM",
                    endpoint,
                    {
                        "role": "STUDENT",
                        "person_id": self.student.public_id,
                        "term_id": old_term.public_id,
                    },
                )
            ),
            [past.public_id],
        )
        page = get("PLATFORM", endpoint, {"page": 2, "page_size": 1})
        self.assertEqual(ids(page), [unrelated.public_id])
        self.assertEqual(page.json()["data"]["total"], 2)
        self.assertEqual(
            get("TEACHING", f"teaching/courses/{unrelated.public_id}/analytics/grades").status_code,
            404,
        )
        self.assertEqual(
            get("USER", f"teaching/courses/{current.public_id}/analytics/grades").status_code, 403
        )

    def test_student_withdraw_reapply_approval_and_exit_enforce_course_access(self) -> None:
        teacher_client = Client(enforce_csrf_checks=True)
        teacher_csrf = self._login(teacher_client, portal="TEACHING", identifier=self.teacher.email)
        course = self._create_and_publish(teacher_client, teacher_csrf)
        course_id = course["public_id"]
        student_client = Client(enforce_csrf_checks=True)
        student_csrf = self._login(student_client, portal="USER", identifier=self.student.email)

        def post(
            client: Client,
            portal: str,
            csrf: str,
            path: str,
            payload: dict[str, object],
            key: str,
            version: int | None = None,
        ) -> HttpResponse:
            headers = {
                "HTTP_X_CSRFTOKEN": csrf,
                "HTTP_X_PORTAL": portal,
                "HTTP_IDEMPOTENCY_KEY": key,
                **PROXY_HEADERS,
            }
            if version is not None:
                headers["HTTP_IF_MATCH"] = f'"{version}"'
            return client.post(path, payload, content_type="application/json", **headers)

        def assert_access(allowed: bool) -> None:
            for suffix in (
                "",
                "/chapters",
                "/materials",
                "/announcements",
                "/calendar",
                "/questions",
            ):
                response = student_client.get(
                    f"/api/v2/courses/{course_id}{suffix}", HTTP_X_PORTAL="USER", **PROXY_HEADERS
                )
                self.assertEqual(response.status_code, 200 if allowed else 403, response.content)

        apply_path = f"/api/v2/courses/{course_id}/enrollments"
        invitation_code = self._code(course_id)
        application = post(
            student_client,
            "USER",
            student_csrf,
            apply_path,
            {"invitation_code": invitation_code},
            "lifecycle-apply",
        )
        self.assertEqual(application.status_code, 201, application.content)
        pending = application.json()["data"]
        self.assertEqual(pending["status"], "PENDING")
        assert_access(False)

        withdrawn = post(
            student_client,
            "USER",
            student_csrf,
            f"/api/v2/me/enrollments/{pending['public_id']}/withdraw",
            {},
            "lifecycle-withdraw",
            pending["row_version"],
        )
        self.assertEqual(withdrawn.status_code, 200, withdrawn.content)
        self.assertEqual(withdrawn.json()["data"]["status"], "WITHDRAWN")
        assert_access(False)

        reapplied = post(
            student_client,
            "USER",
            student_csrf,
            apply_path,
            {"invitation_code": invitation_code},
            "lifecycle-reapply",
        )
        self.assertEqual(reapplied.status_code, 201, reapplied.content)
        new_pending = reapplied.json()["data"]
        self.assertEqual(new_pending["cycle_no"], 2)
        assert_access(False)
        review_path = (
            f"/api/v2/teaching/courses/{course_id}/enrollments/{new_pending['public_id']}/review"
        )
        outsider = create_user(
            email="outsider@example.edu", username="outsider", password=self.password
        )
        grant_teacher(outsider)
        outsider_client = Client(enforce_csrf_checks=True)
        outsider_csrf = self._login(outsider_client, portal="TEACHING", identifier=outsider.email)
        forbidden = post(
            outsider_client,
            "TEACHING",
            outsider_csrf,
            review_path,
            {"decision": "APPROVE"},
            "outsider-approve",
            new_pending["row_version"],
        )
        self.assertIn(forbidden.status_code, (403, 404), forbidden.content)
        approved = post(
            teacher_client,
            "TEACHING",
            teacher_csrf,
            review_path,
            {"decision": "APPROVE", "note": "同意选课"},
            "lifecycle-approve",
            new_pending["row_version"],
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        active = approved.json()["data"]
        self.assertEqual(active["status"], "ACTIVE")
        assert_access(True)
        timetable = student_client.get(
            "/api/v2/me/timetable", HTTP_X_PORTAL="USER", **PROXY_HEADERS
        )
        self.assertEqual(timetable.status_code, 200)
        self.assertEqual(
            [row["course_id"] for row in timetable.json()["data"]["classes"]], [course_id]
        )

        check = student_client.get(
            f"/api/v2/me/enrollments/{active['public_id']}/drop-check",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(check.status_code, 200, check.content)
        self.assertTrue(check.json()["data"]["allowed"])
        dropped = post(
            student_client,
            "USER",
            student_csrf,
            f"/api/v2/me/enrollments/{active['public_id']}/drop",
            {"reason": "选课调整"},
            "lifecycle-drop",
            active["row_version"],
        )
        self.assertEqual(dropped.status_code, 200, dropped.content)
        self.assertEqual(dropped.json()["data"]["status"], "DROPPED")
        assert_access(False)
        active_list = student_client.get(
            "/api/v2/me/enrollments?status=ACTIVE", HTTP_X_PORTAL="USER", **PROXY_HEADERS
        )
        self.assertEqual(active_list.status_code, 200, active_list.content)
        self.assertEqual(active_list.json()["data"], [])

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

    def test_openapi_describes_context_response(self) -> None:
        response = Client().get(
            "/api/v2/schema",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )

        self.assertEqual(response.status_code, 200)
        document = yaml.safe_load(response.content)
        context_response = document["paths"]["/api/v2/context"]["get"]["responses"]["200"]
        self.assertIn("content", context_response)
        self.assertIn("application/json", context_response["content"])

    def test_platform_context_returns_role_without_course_memberships(self) -> None:
        admin_client = Client(enforce_csrf_checks=True)
        self._login(admin_client, portal="PLATFORM", identifier=self.admin.email)

        response = admin_client.get("/api/v2/context", HTTP_X_PORTAL="PLATFORM", **PROXY_HEADERS)

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
