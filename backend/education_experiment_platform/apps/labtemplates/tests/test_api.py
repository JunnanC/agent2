from unittest.mock import patch

from django.test import Client, TestCase

from apps.courses.tests.helpers import create_draft_course, create_teacher

from ..models import Template

PROXY_HEADERS = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}


class TemplateApiTests(TestCase):
    password = "ValidPassword!234"

    def setUp(self) -> None:
        self.owner = create_teacher(suffix="p05-api-owner")
        self.course = create_draft_course(self.owner, code="P05-API-1")
        self.other_course = create_draft_course(self.owner, code="P05-API-2")
        self.client = Client(enforce_csrf_checks=True)
        self.client.get("/api/v2/auth/csrf", HTTP_X_PORTAL="TEACHING", **PROXY_HEADERS)
        self.csrf = str(self.client.cookies["csrftoken"].value)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = self.client.post(
                "/api/v2/auth/login",
                {"identifier": self.owner.email, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self.csrf,
                HTTP_X_PORTAL="TEACHING",
                **PROXY_HEADERS,
            )
        self.assertEqual(response.status_code, 200, response.content)

    def _headers(self) -> dict[str, str]:
        return {
            "HTTP_X_CSRFTOKEN": self.csrf,
            "HTTP_X_PORTAL": "TEACHING",
            **PROXY_HEADERS,
        }

    def test_create_replays_and_patch_enforces_preconditions(self) -> None:
        url = f"/api/v2/teaching/courses/{self.course.public_id}/templates"
        payload = {"name": "API Template", "category": "systems"}
        response = self.client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="template-create-1",
            **self._headers(),
        )
        self.assertEqual(response.status_code, 201, response.content)
        replay = self.client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="template-create-1",
            **self._headers(),
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(Template.objects.count(), 1)
        template_id = response.json()["data"]["public_id"]
        detail = f"{url}/{template_id}"
        missing = self.client.patch(
            detail,
            {"description": "changed"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(missing.status_code, 428)
        stale = self.client.patch(
            detail,
            {"description": "changed"},
            content_type="application/json",
            HTTP_IF_MATCH='"99"',
            **self._headers(),
        )
        self.assertEqual(stale.status_code, 412)

    def test_cross_course_template_is_hidden(self) -> None:
        create = self.client.post(
            f"/api/v2/teaching/courses/{self.course.public_id}/templates",
            {"name": "Scoped"},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="template-scope-1",
            **self._headers(),
        )
        template_id = create.json()["data"]["public_id"]
        hidden = self.client.get(
            f"/api/v2/teaching/courses/{self.other_course.public_id}/templates/{template_id}",
            **self._headers(),
        )
        self.assertEqual(hidden.status_code, 404)
