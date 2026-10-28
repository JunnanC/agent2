from http.cookies import SimpleCookie
from unittest.mock import patch

import yaml
from django.http import HttpResponse
from django.test import Client, TestCase

from apps.accounts.models import TeacherQualification, User
from apps.accounts.services import (
    ActorContext,
    change_teacher_qualification,
    revoke_platform_admin,
    set_account_status,
)

from .helpers import create_user, grant_admin, grant_teacher

PROXY_HEADERS = {
    "HTTP_X_PROXY_CONTEXT": "ingress-v1",
    "REMOTE_ADDR": "127.0.0.1",
}


class AccountApiTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        self.user = create_user(password=self.password)

    def _csrf(self, client: Client, portal: str) -> str:
        response = client.get(
            "/api/v2/auth/csrf",
            HTTP_X_PORTAL=portal,
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        return str(client.cookies["csrftoken"].value)

    def _login(
        self,
        client: Client,
        portal: str,
        identifier: str = "user@example.edu",
    ) -> HttpResponse:
        token = self._csrf(client, portal)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            return client.post(
                "/api/v2/auth/login",
                {"identifier": identifier, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=token,
                HTTP_X_PORTAL=portal,
                **PROXY_HEADERS,
            )

    def test_user_login_me_logout_and_cookie_contract(self) -> None:
        client = Client(enforce_csrf_checks=True)
        response = self._login(client, "USER")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["portal"], "USER")
        cookie: SimpleCookie = client.cookies
        self.assertEqual(cookie["sessionid"]["domain"], "")
        self.assertTrue(cookie["sessionid"]["httponly"])
        self.assertEqual(cookie["sessionid"]["samesite"], "Lax")

        me = client.get("/api/v2/me", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["data"]["public_id"], self.user.public_id)
        self.assertEqual(me["Cache-Control"], "private, no-store")

        csrf = client.cookies["csrftoken"].value
        logout = client.post(
            "/api/v2/auth/logout",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(logout.status_code, 204)

    def test_login_failure_does_not_disclose_account_existence(self) -> None:
        client = Client(enforce_csrf_checks=True)
        token = self._csrf(client, "USER")
        results = []
        with patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"):
            for identifier in ("missing@example.edu", "user@example.edu"):
                response = client.post(
                    "/api/v2/auth/login",
                    {"identifier": identifier, "password": "wrong-password"},
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=token,
                    HTTP_X_PORTAL="USER",
                    **PROXY_HEADERS,
                )
                results.append((response.status_code, response.json()["error"]["code"]))
        self.assertEqual(results, [(401, "INVALID_CREDENTIALS"), (401, "INVALID_CREDENTIALS")])

    def test_copied_user_session_is_rejected_by_other_portals(self) -> None:
        for portal in ("TEACHING", "PLATFORM"):
            user_client = Client(enforce_csrf_checks=True)
            self.assertEqual(self._login(user_client, "USER").status_code, 200)
            other_client = Client(enforce_csrf_checks=True)
            other_client.cookies["sessionid"] = user_client.cookies["sessionid"].value

            response = other_client.get(
                "/api/v2/me",
                HTTP_X_PORTAL=portal,
                **PROXY_HEADERS,
            )

            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "SESSION_PORTAL_MISMATCH")

    def test_teacher_qualification_revocation_invalidates_existing_session(self) -> None:
        qualification = grant_teacher(self.user)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(client, "TEACHING").status_code, 200)

        change_teacher_qualification(
            qualification_public_id=qualification.public_id,
            status=TeacherQualification.Status.REVOKED,
            reason="test",
            expected_version=qualification.row_version,
            actor=self.user,
            context=ActorContext(self.user.public_id, "PLATFORM", "c" * 32),
        )
        response = client.get(
            "/api/v2/me",
            HTTP_X_PORTAL="TEACHING",
            **PROXY_HEADERS,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "TEACHER_QUALIFICATION_REQUIRED")

    def test_platform_admin_revocation_invalidates_existing_session(self) -> None:
        assignment = grant_admin(self.user)
        other_admin = create_user(email="admin@example.edu", username="admin")
        grant_admin(other_admin)
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(client, "PLATFORM").status_code, 200)

        revoke_platform_admin(
            assignment_public_id=assignment.public_id,
            reason="test",
            expected_version=assignment.row_version,
            actor=other_admin,
            context=ActorContext(other_admin.public_id, "PLATFORM", "d" * 32),
        )
        response = client.get(
            "/api/v2/me",
            HTTP_X_PORTAL="PLATFORM",
            **PROXY_HEADERS,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PLATFORM_ACCESS_REQUIRED")

    def test_account_disable_invalidates_existing_session(self) -> None:
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(client, "USER").status_code, 200)
        self.user.refresh_from_db()

        set_account_status(
            user_public_id=self.user.public_id,
            status=User.AccountStatus.DISABLED,
            reason="test",
            expected_version=self.user.row_version,
            context=ActorContext("admin", "PLATFORM", "e" * 32),
        )
        response = client.get(
            "/api/v2/me",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "SESSION_EXPIRED")

    def test_password_change_keeps_current_session_and_revokes_other_sessions(self) -> None:
        first = Client(enforce_csrf_checks=True)
        second = Client(enforce_csrf_checks=True)
        self.assertEqual(self._login(first, "USER").status_code, 200)
        second_login = self._login(second, "USER")
        csrf = second.cookies["csrftoken"].value

        changed = second.post(
            "/api/v2/me/password",
            {
                "current_password": self.password,
                "new_password": "NewValidPassword!567",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
            HTTP_IF_MATCH=second_login["ETag"],
            HTTP_IDEMPOTENCY_KEY="password-change-1",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )

        self.assertEqual(changed.status_code, 200)
        self.assertEqual(
            second.get("/api/v2/me", HTTP_X_PORTAL="USER", **PROXY_HEADERS).status_code,
            200,
        )
        expired = first.get("/api/v2/me", HTTP_X_PORTAL="USER", **PROXY_HEADERS)
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(expired.json()["error"]["code"], "SESSION_EXPIRED")

    def test_password_change_replays_the_original_idempotent_response(self) -> None:
        client = Client(enforce_csrf_checks=True)
        login_response = self._login(client, "USER")
        self.user.refresh_from_db()
        initial_security_version = self.user.security_version
        csrf = client.cookies["csrftoken"].value
        request = {
            "path": "/api/v2/me/password",
            "data": {
                "current_password": self.password,
                "new_password": "NewValidPassword!567",
            },
            "content_type": "application/json",
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_IF_MATCH": login_response["ETag"],
            "HTTP_IDEMPOTENCY_KEY": "password-change-replay",
            "HTTP_X_PORTAL": "USER",
            **PROXY_HEADERS,
        }

        first = client.post(**request)
        replay = client.post(**request)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(replay["ETag"], first["ETag"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.security_version, initial_security_version + 1)

    def test_openapi_exposes_p02_paths_tags_and_portals(self) -> None:
        response = Client().get(
            "/api/v2/schema",
            HTTP_X_PORTAL="USER",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        document = yaml.safe_load(response.content)
        expected_operations = {
            ("/api/v2/auth/login", "post"): ("auth", ["USER", "TEACHING", "PLATFORM"]),
            ("/api/v2/me", "get"): ("me", ["USER", "TEACHING", "PLATFORM"]),
            ("/api/v2/me/verification", "get"): ("me", ["USER"]),
            ("/api/v2/platform/users", "get"): ("platform-accounts", ["PLATFORM"]),
            ("/api/v2/platform/teacher-qualifications", "get"): (
                "platform-accounts",
                ["PLATFORM"],
            ),
            ("/api/v2/platform/admin-assignments", "get"): (
                "platform-accounts",
                ["PLATFORM"],
            ),
            ("/api/v2/platform/verifications", "get"): (
                "platform-accounts",
                ["PLATFORM"],
            ),
        }
        for (path, method), (tag, portals) in expected_operations.items():
            operation = document["paths"][path][method]
            self.assertIn(tag, operation["tags"])
            self.assertEqual(operation["x-portals"], portals)

    def test_forged_portal_without_trusted_proxy_is_rejected(self) -> None:
        response = Client().get(
            "/api/v2/me",
            HTTP_X_PORTAL="PLATFORM",
            REMOTE_ADDR="198.51.100.10",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "PROXY_CONTEXT_UNTRUSTED")

    def test_session_step_up_rejects_wrong_password_and_accepts_correct_one(self) -> None:
        from django.contrib.sessions.backends.db import SessionStore

        client = Client(enforce_csrf_checks=True)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            self.assertEqual(self._login(client, "USER").status_code, 200)
            csrf = client.cookies["csrftoken"].value

            wrong = client.post(
                "/api/v2/auth/session/step-up",
                {"password": "wrong-password"},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="USER",
                HTTP_IDEMPOTENCY_KEY="step-up-wrong",
                **PROXY_HEADERS,
            )
            accepted = client.post(
                "/api/v2/auth/session/step-up",
                {"password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
                HTTP_X_PORTAL="USER",
                HTTP_IDEMPOTENCY_KEY="step-up-ok",
                **PROXY_HEADERS,
            )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.json()["error"]["code"], "INVALID_CREDENTIALS")
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["data"]["recent"])

        session_key = client.cookies["sessionid"].value
        session = SessionStore(session_key=session_key)
        auth_time = session.get("account_auth_time")
        self.assertIsInstance(auth_time, int)
        self.assertGreater(auth_time, 0)

    def test_session_step_up_requires_authentication(self) -> None:
        client = Client(enforce_csrf_checks=True)
        token = self._csrf(client, "USER")
        response = client.post(
            "/api/v2/auth/session/step-up",
            {"password": self.password},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_X_PORTAL="USER",
            HTTP_IDEMPOTENCY_KEY="step-up-anon",
            **PROXY_HEADERS,
        )
        self.assertEqual(response.status_code, 401)
