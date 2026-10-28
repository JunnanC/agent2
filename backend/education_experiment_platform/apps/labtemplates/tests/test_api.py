from unittest.mock import patch

from django.test import Client, TestCase

from apps.courses.tests.helpers import create_draft_course, create_teacher

from ..image_services import create_experiment_image
from ..models import ExperimentImage, Template, TemplateVersion
from ..services import create_template, create_version
from .helpers import context, create_resources

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

    def _version(self, suffix: str = "api-image") -> TemplateVersion:
        adapter, image, profile = create_resources(self.owner, suffix=suffix)
        template = create_template(
            course_id=self.course.public_id,
            actor=self.owner,
            name=f"Image API {suffix}",
            category="",
            description="",
            context=context(self.owner, f"template-{suffix}"),
        )
        return create_version(
            course_id=self.course.public_id,
            template_id=template.public_id,
            actor=self.owner,
            data={
                "runtime_type": "CONTAINER",
                "runtime_adapter_id": adapter.public_id,
                "image_id": image.public_id,
                "resource_profile_id": profile.public_id,
            },
            context=context(self.owner, f"version-{suffix}"),
        )

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

    def test_content_routes_require_if_match_and_map_missing_chapter(self) -> None:
        adapter, image, profile = create_resources(self.owner, suffix="api-content")
        template = create_template(
            course_id=self.course.public_id,
            actor=self.owner,
            name="Content API",
            category="",
            description="",
            context=context(self.owner, "v"),
        )
        version = create_version(
            course_id=self.course.public_id,
            template_id=template.public_id,
            actor=self.owner,
            data={
                "runtime_type": "CONTAINER",
                "runtime_adapter_id": adapter.public_id,
                "image_id": image.public_id,
                "resource_profile_id": profile.public_id,
            },
            context=context(self.owner, "w"),
        )
        url = (
            f"/api/v2/teaching/courses/{self.course.public_id}/"
            f"template-versions/{version.public_id}/chapters"
        )
        listing = self.client.get(url, **self._headers())
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing["ETag"], '"1"')
        missing_match = self.client.post(
            url, {"title": "Chapter"}, content_type="application/json", **self._headers()
        )
        self.assertEqual(missing_match.status_code, 428)
        missing_chapter = self.client.post(
            f"/api/v2/teaching/courses/{self.course.public_id}/template-chapters/{'0' * 26}/tasks",
            {"title": "Task", "task_type": "CODE"},
            content_type="application/json",
            HTTP_IF_MATCH='"1"',
            HTTP_IDEMPOTENCY_KEY="missing-chapter-task",
            **self._headers(),
        )
        self.assertEqual(missing_chapter.status_code, 404)

    def test_image_api_is_course_scoped_and_enforces_preconditions(self) -> None:
        version = self._version("api-image-routes")
        image = create_experiment_image(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry="registry.example.edu",
            repository="labs/api",
            requested_tag="v1",
            actor=self.owner,
            context=context(self.owner, "api-image"),
        )
        base_url = f"/api/v2/teaching/courses/{self.course.public_id}/experiment-images"
        self.assertEqual(self.client.get(base_url, **self._headers()).status_code, 200)
        detail_url = f"{base_url}/{image.public_id}"
        detail = self.client.get(detail_url, **self._headers())
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail["ETag"], '"1"')
        missing = self.client.get(f"{base_url}/{'0' * 26}", **self._headers())
        self.assertEqual(missing.status_code, 404)
        cross_course = self.client.get(
            f"/api/v2/teaching/courses/{self.other_course.public_id}/experiment-images/"
            f"{image.public_id}",
            **self._headers(),
        )
        self.assertEqual(cross_course.status_code, 404)
        events = self.client.get(f"{detail_url}/events", **self._headers())
        self.assertEqual(events.status_code, 200, events.content)
        self.assertTrue(events.json()["data"])
        cross_events = self.client.get(
            f"/api/v2/teaching/courses/{self.other_course.public_id}/experiment-images/"
            f"{image.public_id}/events",
            **self._headers(),
        )
        self.assertEqual(cross_events.status_code, 404)

        prepare_url = f"{detail_url}/prepare"
        missing_match = self.client.post(
            prepare_url,
            {},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="image-prepare-missing-match",
            **self._headers(),
        )
        self.assertEqual(missing_match.status_code, 428)
        stale = self.client.post(
            prepare_url,
            {},
            content_type="application/json",
            HTTP_IF_MATCH='"99"',
            HTTP_IDEMPOTENCY_KEY="image-prepare-stale",
            **self._headers(),
        )
        self.assertEqual(stale.status_code, 412)

        with patch("apps.labtemplates.views.prepare_experiment_image_task.delay"):
            prepared = self.client.post(
                prepare_url,
                {},
                content_type="application/json",
                HTTP_IF_MATCH='"1"',
                HTTP_IDEMPOTENCY_KEY="image-prepare-ok",
                **self._headers(),
            )
        self.assertEqual(prepared.status_code, 202, prepared.content)
        replay = self.client.post(
            prepare_url,
            {},
            content_type="application/json",
            HTTP_IF_MATCH='"1"',
            HTTP_IDEMPOTENCY_KEY="image-prepare-ok",
            **self._headers(),
        )
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")

        missing_retire_match = self.client.post(
            f"{detail_url}/retire",
            {},
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="image-retire-missing-match",
            **self._headers(),
        )
        self.assertEqual(missing_retire_match.status_code, 428)
        stale_headers = self._headers()
        stale_headers["HTTP_IF_MATCH"] = '"99"'
        stale_headers["HTTP_IDEMPOTENCY_KEY"] = "image-retire-stale"
        stale_retire = self.client.post(
            f"{detail_url}/retire",
            {},
            content_type="application/json",
            **stale_headers,
        )
        self.assertEqual(stale_retire.status_code, 412)
        retire_headers = self._headers()
        retire_headers["HTTP_IF_MATCH"] = '"1"'
        retire_headers["HTTP_IDEMPOTENCY_KEY"] = "image-retire-ok"
        retired = self.client.post(
            f"{detail_url}/retire",
            {},
            content_type="application/json",
            **retire_headers,
        )
        self.assertEqual(retired.status_code, 200, retired.content)
        self.assertEqual(retired.json()["data"]["status"], ExperimentImage.Status.RETIRED)

    def test_image_create_replays_and_rejects_invalid_reference(self) -> None:
        version = self._version("api-image-create")
        url = f"/api/v2/teaching/courses/{self.course.public_id}/experiment-images"
        payload = {
            "template_version_id": version.public_id,
            "source_type": ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            "registry": "registry.example.edu",
            "repository": "labs/api-create",
            "requested_tag": "v1",
        }
        created = self.client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="image-create-1",
            **self._headers(),
        )
        self.assertEqual(created.status_code, 201, created.content)
        replay = self.client.post(
            url,
            payload,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="image-create-1",
            **self._headers(),
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        invalid = dict(payload, registry="https://registry.example.edu")
        response = self.client.post(
            url,
            invalid,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="image-create-invalid",
            **self._headers(),
        )
        self.assertEqual(response.status_code, 400, response.content)
