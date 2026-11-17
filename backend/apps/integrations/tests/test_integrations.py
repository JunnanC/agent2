from django.core.signing import BadSignature
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user
from apps.core.errors import RowVersionConflict
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.courses.tests.helpers import create_draft_course, create_teacher
from apps.integrations.authentication import IntegrationPrincipal
from apps.integrations.crypto import digest, sign_webhook, unseal
from apps.integrations.models import (
    APIClientGrant,
    OIDCIdentity,
    OIDCProvider,
    WebhookDelivery,
    WebhookEndpoint,
)
from apps.integrations.services import (
    authenticate_client,
    bind_oidc_identity,
    create_api_client,
    create_webhook_delivery,
    rotate_api_client_secret,
)


class IntegrationContractTests(TestCase):
    def setUp(self) -> None:
        self.actor = create_user(
            email="integration-integrations@example.edu", username="integration-integrations"
        )
        self.other = create_user(
            email="integration-other-integrations@example.edu",
            username="integration-other-integrations",
        )
        self.context = ActorContext(self.actor.public_id, "PLATFORM", "integration-trace")

    def test_oidc_subject_cannot_be_silently_rebound(self) -> None:
        provider = OIDCProvider.objects.create(
            key="integrations-idp",
            name="integrations IdP",
            issuer="https://idp.example.edu",
            issuer_hash=digest("https://idp.example.edu"),
            client_id="client",
            client_secret_ciphertext="sealed",
            allowed_portals=["USER"],
        )
        bind_oidc_identity(
            provider=provider,
            account=self.actor,
            subject="subject-1",
            context=ActorContext(self.actor.public_id, "USER", "integration-trace"),
        )
        with self.assertRaises(RowVersionConflict):
            bind_oidc_identity(
                provider=provider,
                account=self.other,
                subject="subject-1",
                context=ActorContext(self.other.public_id, "USER", "integration-trace"),
            )
        self.assertEqual(OIDCIdentity.objects.count(), 1)

    def test_client_rotation_has_controlled_previous_secret_window(self) -> None:
        client, old_secret = create_api_client(
            actor=self.actor,
            name="integrations client",
            scopes=["courses:read"],
            context=self.context,
        )
        rotated, new_secret = rotate_api_client_secret(
            item=client,
            actor=self.actor,
            expected_version=client.row_version,
            context=self.context,
        )
        self.assertNotEqual(old_secret, new_secret)
        self.assertEqual(
            authenticate_client(client_id=client.client_id, secret=old_secret)[0], rotated
        )
        self.assertEqual(
            authenticate_client(client_id=client.client_id, secret=new_secret)[0], rotated
        )
        self.assertTrue(rotated.previous_secret_expires_at > timezone.now())

    def test_webhook_delivery_is_idempotent_and_signature_binds_body(self) -> None:
        secret = "webhook-secret"
        endpoint = WebhookEndpoint.objects.create(
            name="integrations webhook",
            endpoint_url_ciphertext="sealed-url",
            endpoint_url_digest=digest("https://hooks.example.edu/integrations"),
            secret_ciphertext="sealed-secret",
            event_allowlist=["course.published"],
            created_by=self.actor,
        )
        # The crypto contract is independently testable even when no HTTP receiver exists.
        body = b'{"event":"course.published"}'
        signature = sign_webhook(secret=secret, delivery_id="delivery-1", timestamp=123, body=body)
        self.assertNotEqual(
            signature,
            sign_webhook(secret=secret, delivery_id="delivery-1", timestamp=123, body=b"{}"),
        )
        with self.assertRaises(BadSignature):
            unseal(endpoint.secret_ciphertext)
        first = create_webhook_delivery(
            endpoint=endpoint,
            event_id="event-1",
            event_type="course.published",
            payload={"course_id": "course-integrations"},
        )
        second = create_webhook_delivery(
            endpoint=endpoint,
            event_id="event-1",
            event_type="course.published",
            payload={"course_id": "course-integrations"},
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=endpoint).count(), 1)


class OpenCoursesViewTests(TestCase):
    def setUp(self) -> None:
        self.actor = create_user(
            email="integration-open-courses@example.edu", username="integration-open-courses"
        )
        self.context = ActorContext(self.actor.public_id, "PLATFORM", "integration-trace")
        self.client_model, _secret = create_api_client(
            actor=self.actor,
            name="open courses client",
            scopes=["courses:read"],
            context=self.context,
        )
        owner = create_teacher(suffix="open-courses-owner")
        self.granted_course = create_draft_course(owner, code="OPEN-COURSE-GRANTED")
        Course.objects.filter(pk=self.granted_course.pk).update(status=Course.Status.PUBLISHED)
        self.ungranted_course = create_draft_course(owner, code="OPEN-COURSE-UNGRANTED")
        Course.objects.filter(pk=self.ungranted_course.pk).update(status=Course.Status.PUBLISHED)
        self.granted_course.refresh_from_db()
        self.ungranted_course.refresh_from_db()
        self.factory = RequestFactory()

    def _request(self, *, scopes: tuple[str, ...]) -> object:
        request = self.factory.get("/integrations/open-courses")
        request.user = IntegrationPrincipal(client=self.client_model, scopes=scopes)
        return request

    def test_platform_grant_returns_all_published_courses(self) -> None:
        from apps.integrations.views import OpenCoursesView

        APIClientGrant.objects.create(
            client=self.client_model, scope="courses:read", resource_scope="PLATFORM",
        )
        response = OpenCoursesView().get(self._request(scopes=("courses:read",)))
        public_ids = {item["public_id"] for item in response.data["data"]}
        self.assertEqual(
            public_ids, {self.granted_course.public_id, self.ungranted_course.public_id}
        )

    def test_course_scoped_grant_returns_only_granted_course(self) -> None:
        from apps.integrations.views import OpenCoursesView

        APIClientGrant.objects.create(
            client=self.client_model,
            scope="courses:read",
            resource_scope="COURSE",
            course=self.granted_course,
        )
        response = OpenCoursesView().get(self._request(scopes=("courses:read",)))
        public_ids = {item["public_id"] for item in response.data["data"]}
        self.assertEqual(public_ids, {self.granted_course.public_id})

    def test_missing_scope_returns_no_courses(self) -> None:
        from apps.integrations.views import OpenCoursesView

        APIClientGrant.objects.create(
            client=self.client_model, scope="courses:read", resource_scope="PLATFORM",
        )
        response = OpenCoursesView().get(self._request(scopes=("experiments:read",)))
        self.assertEqual(response.data["data"], [])
