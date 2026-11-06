import os
import re
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.http import HttpResponse
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    PendingRegistration,
    PlatformAdminAssignment,
    TeacherQualification,
    User,
)
from apps.accounts.services import (
    ActorContext,
    change_teacher_qualification,
    grant_teacher_qualification,
)
from apps.core.models import AuditLog

from .helpers import create_user, grant_admin

PROXY_HEADERS = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}


class RegistrationTests(TestCase):
    password = "ValidPassword!234"

    def _client(self, portal: str) -> Client:
        client = Client(enforce_csrf_checks=True)
        response = client.get("/api/v2/auth/csrf", HTTP_X_PORTAL=portal, **PROXY_HEADERS)
        self.assertEqual(response.status_code, 200)
        return client

    def _post(
        self, client: Client, portal: str, path: str, data: dict, **headers: str
    ) -> HttpResponse:
        return client.post(
            path,
            data,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
            HTTP_X_PORTAL=portal,
            **PROXY_HEADERS,
            **headers,
        )

    def _register(self, client: Client, portal: str, email: str) -> str:
        with patch("apps.accounts.views.check_registration_rate_limit"):
            response = self._post(
                client,
                portal,
                "/api/v2/auth/register",
                {
                    "email": email,
                    "username": email.split("@")[0],
                    "display_name": "Applicant",
                    "password": self.password,
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertFalse(User.objects.filter(email=email).exists())
        match = re.search(r"token=([A-Za-z0-9_-]+)", mail.outbox[-1].body)
        assert match is not None
        self.assertIn("http://", mail.outbox[-1].body)
        return match.group(1)

    def _login(self, client: Client, portal: str, email: str) -> int:
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="test-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = self._post(
                client,
                portal,
                "/api/v2/auth/login",
                {"identifier": email, "password": self.password},
            )
        return response.status_code

    def test_student_requires_email_verification_then_can_log_in(self) -> None:
        email = "student-new@example.edu"
        client = self._client("USER")
        token = self._register(client, "USER", email)
        self.assertEqual(self._login(client, "USER", email), 401)
        verified = self._post(client, "USER", "/api/v2/auth/verify-email", {"token": token})
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(User.objects.get(email=email).registration_role, "STUDENT")
        self.assertFalse(PendingRegistration.objects.filter(email=email).exists())
        self.assertEqual(self._login(client, "USER", email), 200)
        replay = self._post(client, "USER", "/api/v2/auth/verify-email", {"token": token})
        self.assertEqual(replay.status_code, 400)

    def test_teacher_cannot_enter_any_portal_until_approved(self) -> None:
        email = "teacher-new@example.edu"
        teacher_client = self._client("TEACHING")
        token = self._register(teacher_client, "TEACHING", email)
        wrong_portal = self._post(
            self._client("USER"), "USER", "/api/v2/auth/verify-email", {"token": token}
        )
        self.assertEqual(wrong_portal.status_code, 400)
        verified = self._post(
            teacher_client, "TEACHING", "/api/v2/auth/verify-email", {"token": token}
        )
        self.assertEqual(verified.status_code, 200)
        user = User.objects.get(email=email)
        qualification = TeacherQualification.objects.get(user=user)
        self.assertEqual(qualification.status, "PENDING")
        self.assertIsNone(qualification.granted_at)
        self.assertEqual(self._login(self._client("USER"), "USER", email), 403)
        self.assertEqual(self._login(teacher_client, "TEACHING", email), 403)

        admin = create_user(email="admin@example.edu", username="admin")
        grant_admin(admin)
        grant_teacher_qualification(
            user_public_id=user.public_id,
            reason="Approved application",
            expected_user_version=user.row_version,
            actor=admin,
            context=ActorContext(admin.public_id, "PLATFORM", "a" * 32),
        )
        self.assertEqual(self._login(teacher_client, "TEACHING", email), 200)
        self.assertEqual(self._login(self._client("USER"), "USER", email), 403)

    def test_expired_link_and_existing_email(self) -> None:
        email = "expired@example.edu"
        client = self._client("USER")
        token = self._register(client, "USER", email)
        PendingRegistration.objects.filter(email=email).update(expires_at=timezone.now())
        self.assertEqual(
            self._post(client, "USER", "/api/v2/auth/verify-email", {"token": token}).status_code,
            400,
        )
        existing = create_user(email="existing@example.edu", username="existing")
        count = len(mail.outbox)
        with patch("apps.accounts.views.check_registration_rate_limit"):
            response = self._post(
                client,
                "USER",
                "/api/v2/auth/register",
                {
                    "email": existing.email,
                    "username": "another",
                    "display_name": "Other",
                    "password": self.password,
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(mail.outbox), count)

    def test_rejected_teacher_stays_out_of_both_portals(self) -> None:
        email = "rejected@example.edu"
        client = self._client("TEACHING")
        token = self._register(client, "TEACHING", email)
        self._post(client, "TEACHING", "/api/v2/auth/verify-email", {"token": token})
        qualification = TeacherQualification.objects.get(user__email=email)
        admin = create_user(email="admin@example.edu", username="admin")
        grant_admin(admin)
        change_teacher_qualification(
            qualification_public_id=qualification.public_id,
            status=TeacherQualification.Status.REJECTED,
            reason="Application rejected",
            expected_version=qualification.row_version,
            actor=admin,
            context=ActorContext(admin.public_id, "PLATFORM", "b" * 32),
        )
        self.assertEqual(self._login(self._client("USER"), "USER", email), 403)
        self.assertEqual(self._login(client, "TEACHING", email), 403)

    def test_mail_failure_does_not_keep_pending_registration(self) -> None:
        client = self._client("USER")
        with (
            patch("apps.accounts.views.check_registration_rate_limit"),
            patch("apps.accounts.registration.send_mail", side_effect=OSError("smtp down")),
        ):
            response = self._post(
                client,
                "USER",
                "/api/v2/auth/register",
                {
                    "email": "mail-failure@example.edu",
                    "username": "mail-failure",
                    "display_name": "Mail Failure",
                    "password": self.password,
                },
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(PendingRegistration.objects.filter(email="mail-failure@example.edu").exists())

    def test_only_server_command_can_grant_platform_admin(self) -> None:
        admin = create_user(email="admin@example.edu", username="admin")
        grant_admin(admin)
        target = create_user(email="target@example.edu", username="target")
        client = self._client("PLATFORM")
        self.assertEqual(self._login(client, "PLATFORM", admin.email), 200)
        response = self._post(
            client,
            "PLATFORM",
            f"/api/v2/platform/users/{target.public_id}/admin-assignment",
            {"reason": "Unauthorized"},
            HTTP_IDEMPOTENCY_KEY="blocked-admin-grant",
        )
        self.assertEqual(response.status_code, 404)
        call_command("add_platform_admin", email=target.email, reason="Approved operator request")
        self.assertTrue(
            PlatformAdminAssignment.objects.filter(user=target, status="ACTIVE").exists()
        )
        self.assertTrue(AuditLog.objects.filter(action="platform.admin.assignment.change").exists())

        with patch.dict(os.environ, {"PLATFORM_ADMIN_BOOTSTRAP_PASSWORD": self.password}):
            call_command(
                "add_platform_admin",
                email="new-admin@example.edu",
                username="new-admin",
                display_name="New Admin",
                reason="Approved operator request",
            )
        self.assertTrue(User.objects.filter(email="new-admin@example.edu").exists())
