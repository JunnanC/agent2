import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from django.db.models import Avg, Count, Q
from django.http import HttpRequest
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAuthenticatedAccount, IsPlatformPortal
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask

from .authentication import IntegrationPrincipal, IntegrationTokenAuthentication, enforce_rate_limit
from .crypto import digest, generate_secret, seal
from .models import (
    APIClient,
    APIClientGrant,
    OIDCIdentity,
    OIDCProvider,
    WebhookDelivery,
    WebhookEndpoint,
)
from .serializers import (
    APIClientGrantSerializer,
    APIClientSerializer,
    OIDCProviderSerializer,
    P13IntegrationResponseSerializer,
    TokenSerializer,
    WebhookSerializer,
    attempt_data,
    client_data,
    delivery_data,
    grant_data,
    identity_data,
    provider_data,
    webhook_data,
)
from .services import (
    authenticate_client,
    bind_oidc_identity,
    create_access_token,
    create_api_client,
    create_oidc_provider,
    rotate_api_client_secret,
    rotate_oidc_secret,
    unlink_oidc_identity,
)

IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


class P13APIView(APIView):
    serializer_class = P13IntegrationResponseSerializer


def _body(request: HttpRequest, data: Any) -> dict[str, Any]:
    return {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}


def _ctx(request: HttpRequest) -> ActorContext:
    return ActorContext(
        actor_ref=request.user.public_id,
        portal=str(getattr(request, "portal", "PLATFORM")),
        trace_id=str(getattr(request, "trace_id", "")),
    )


def _idempotent(
    request: HttpRequest, *, payload: Any, operation: Callable[[], StoredResponse]
) -> Response:
    result = execute_idempotent(
        principal=PrincipalScope(request.user.public_id, "SESSION", str(request.portal)),
        method=request.method,
        endpoint=request.path,
        key=getattr(request, "idempotency_key", None),
        payload=payload,
        operation=operation,
    )
    response = Response(result.body, status=result.status_code, headers=dict(result.headers))
    response["Cache-Control"] = "private, no-store"
    if result.replayed:
        response["X-Idempotent-Replayed"] = "true"
    return response


class IsIntegrationPrincipal(BasePermission):
    def has_permission(self, request, view) -> bool:  # type: ignore[no-untyped-def]
        return isinstance(getattr(request, "user", None), IntegrationPrincipal)


class OAuthTokenView(P13APIView):
    authentication_classes: list = []
    permission_classes: list = []

    @extend_schema(
        request=TokenSerializer, tags=["external-api"], extensions={"x-portals": ["INTEGRATION"]}
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = TokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client, _ = authenticate_client(
            client_id=serializer.validated_data["client_id"],
            secret=serializer.validated_data["client_secret"],
        )
        enforce_rate_limit(client)
        requested = set(filter(None, serializer.validated_data.get("scope", "").split()))
        scopes = set(client.allowed_scopes) | set(
            APIClientGrant.objects.filter(client=client, status="ACTIVE").values_list(
                "scope", flat=True
            )
        )
        if requested:
            scopes &= requested
        return Response({
            "access_token": create_access_token(client=client, scopes=sorted(scopes)),
            "token_type": "Bearer",
            "expires_in": 900,
            "scope": " ".join(sorted(scopes)),
        })


def _has_scope(request: HttpRequest, scope: str) -> bool:
    principal: IntegrationPrincipal = request.user
    return scope in principal.scopes or "*" in principal.scopes


def _course_granted(request: HttpRequest, course: Course) -> bool:
    principal: IntegrationPrincipal = request.user
    requested_scopes = {"courses:read", "course:read", "*"}
    if not any(_has_scope(request, scope) for scope in requested_scopes):
        return False
    return (
        APIClientGrant.objects.filter(client=principal.client, status="ACTIVE")
        .filter(scope__in=requested_scopes)
        .filter(Q(resource_scope="PLATFORM") | Q(course=course))
        .exists()
    )


class OpenCoursesView(P13APIView):
    authentication_classes = [IntegrationTokenAuthentication]
    permission_classes = [IsIntegrationPrincipal]

    @extend_schema(tags=["external-api"], extensions={"x-portals": ["INTEGRATION"]})
    def get(self, request: HttpRequest) -> Response:
        courses = [
            course
            for course in Course.objects.filter(status=Course.Status.PUBLISHED)
            if _course_granted(request, course)
        ]
        return Response(
            _body(
                request,
                [
                    {
                        "public_id": item.public_id,
                        "code": item.code,
                        "title": item.title,
                        "status": item.status,
                    }
                    for item in courses
                ],
            )
        )


class OpenCourseExperimentsView(P13APIView):
    authentication_classes = [IntegrationTokenAuthentication]
    permission_classes = [IsIntegrationPrincipal]

    @extend_schema(tags=["external-api"], extensions={"x-portals": ["INTEGRATION"]})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = Course.objects.filter(public_id=course_id).first()
        if course is None or not _course_granted(request, course):
            raise ResourceNotFound()
        rows = (
            ExperimentTask.objects.filter(course=course)
            .values("publication__public_id", "publication__title", "publication__status")
            .annotate(task_count=Count("id"))
        )
        return Response(_body(request, list(rows)))


class OpenCourseProgressView(P13APIView):
    authentication_classes = [IntegrationTokenAuthentication]
    permission_classes = [IsIntegrationPrincipal]

    @extend_schema(tags=["external-api"], extensions={"x-portals": ["INTEGRATION"]})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = Course.objects.filter(public_id=course_id).first()
        if course is None or not _course_granted(request, course):
            raise ResourceNotFound()
        rows = (
            ExperimentTask.objects.filter(course=course)
            .values("status")
            .annotate(count=Count("id"), average_progress=Avg("progress"))
        )
        return Response(_body(request, list(rows)))


class PlatformOIDCProviderView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=OIDCProviderSerializer,
        parameters=[IDEMPOTENCY_KEY],
        operation_id="platform_integrations_oidc_providers_list",
        tags=["platform-integrations"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return Response(
            _body(
                request,
                [provider_data(item) for item in OIDCProvider.objects.all().order_by("key")],
            )
        )

    def post(self, request: HttpRequest) -> Response:
        serializer = OIDCProviderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        payload = dict(values)
        values.setdefault("client_secret", generate_secret("oidc_"))

        def operation() -> StoredResponse:
            item, secret = create_oidc_provider(
                actor=request.user, data=values, context=_ctx(request)
            )
            data = provider_data(item)
            data["client_secret"] = secret
            return StoredResponse(
                201, _body(request, data), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent(request, payload=payload, operation=operation)


class PlatformOIDCProviderDetailView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(operation_id="platform_integrations_oidc_providers_detail")
    def get(self, request: HttpRequest, provider_id: str) -> Response:
        item = OIDCProvider.objects.filter(public_id=provider_id).first()
        if item is None:
            raise ResourceNotFound()
        return Response(
            _body(request, provider_data(item)),
            headers={"ETag": etag_for_version(item.row_version)},
        )

    def patch(self, request: HttpRequest, provider_id: str) -> Response:
        item = OIDCProvider.objects.filter(public_id=provider_id).first()
        if item is None:
            raise ResourceNotFound()
        serializer = OIDCProviderSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        values = {
            key: value for key, value in serializer.validated_data.items() if key != "client_secret"
        }
        if "issuer" in values:
            values["issuer_hash"] = digest(values["issuer"])
        from apps.core.concurrency import compare_and_swap

        updated = compare_and_swap(
            OIDCProvider,
            pk=item.pk,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=values,
        )
        return Response(
            _body(request, provider_data(updated)),
            headers={"ETag": etag_for_version(updated.row_version)},
        )


class PlatformOIDCProviderRotateView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(parameters=[IDEMPOTENCY_KEY, IF_MATCH])
    def post(self, request: HttpRequest, provider_id: str) -> Response:
        item = OIDCProvider.objects.filter(public_id=provider_id).first()
        if item is None:
            raise ResourceNotFound()

        def operation() -> StoredResponse:
            updated, secret = rotate_oidc_secret(
                item=item,
                actor=request.user,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_ctx(request),
            )
            data = provider_data(updated)
            data["client_secret"] = secret
            return StoredResponse(
                200, _body(request, data), {"ETag": etag_for_version(updated.row_version)}
            )

        return _idempotent(request, payload={"provider_id": provider_id}, operation=operation)


class PlatformOIDCIdentityView(P13APIView):
    permission_classes = [IsPlatformPortal]

    def get(self, request: HttpRequest) -> Response:
        rows = OIDCIdentity.objects.select_related("provider", "account").order_by("-created_at")
        return Response(_body(request, [identity_data(item) for item in rows]))

    @extend_schema(parameters=[IDEMPOTENCY_KEY, IF_MATCH])
    def post(self, request: HttpRequest, identity_id: str) -> Response:
        item = OIDCIdentity.objects.filter(public_id=identity_id).first()
        if item is None:
            raise ResourceNotFound()

        def operation() -> StoredResponse:
            updated = unlink_oidc_identity(
                item=item,
                actor=request.user,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_ctx(request),
            )
            return StoredResponse(
                200,
                _body(request, identity_data(updated)),
                {"ETag": etag_for_version(updated.row_version)},
            )

        return _idempotent(request, payload={"identity_id": identity_id}, operation=operation)


class PlatformAPIClientView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(operation_id="platform_integrations_api_clients_list")
    def get(self, request: HttpRequest) -> Response:
        return Response(
            _body(request, [client_data(item) for item in APIClient.objects.order_by("name")])
        )

    @extend_schema(
        request=APIClientSerializer,
        parameters=[IDEMPOTENCY_KEY],
        operation_id="platform_integrations_api_clients_create",
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = APIClientSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item, secret = create_api_client(
                actor=request.user,
                name=serializer.validated_data["name"],
                scopes=serializer.validated_data.get("scopes", []),
                context=_ctx(request),
                rate_limit_per_minute=serializer.validated_data.get("rate_limit_per_minute", 60),
            )
            data = client_data(item)
            data["client_secret"] = secret
            return StoredResponse(
                201, _body(request, data), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformAPIClientGrantView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(operation_id="platform_integrations_api_client_grants_list")
    def get(self, request: HttpRequest, client_id: str) -> Response:
        client = APIClient.objects.filter(public_id=client_id).first()
        if client is None:
            raise ResourceNotFound()
        rows = [grant_data(item) for item in client.grants.select_related("course")]
        return Response(_body(request, rows))

    @extend_schema(
        request=APIClientGrantSerializer,
        parameters=[IDEMPOTENCY_KEY],
        operation_id="platform_integrations_api_client_grants_create",
    )
    def post(self, request: HttpRequest, client_id: str) -> Response:
        client = APIClient.objects.filter(public_id=client_id).first()
        if client is None:
            raise ResourceNotFound()
        serializer = APIClientGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        course_id = str(values.pop("course_id", ""))
        resource_scope = values.get("resource_scope", "PLATFORM")
        course = Course.objects.filter(public_id=course_id).first() if course_id else None
        if resource_scope == "COURSE" and course is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"course_id": "course_id is required for COURSE grants"})
        if resource_scope == "PLATFORM" and course is not None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"course_id": "PLATFORM grants cannot target a course"})
        values["course"] = course

        def operation() -> StoredResponse:
            item, _ = APIClientGrant.objects.get_or_create(client=client, **values)
            return StoredResponse(
                201, _body(request, grant_data(item)), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformAPIClientDetailView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(operation_id="platform_integrations_api_clients_detail")
    def get(self, request: HttpRequest, client_id: str) -> Response:
        item = APIClient.objects.filter(public_id=client_id).first()
        if item is None:
            raise ResourceNotFound()
        return Response(
            _body(request, client_data(item)), headers={"ETag": etag_for_version(item.row_version)}
        )

    def patch(self, request: HttpRequest, client_id: str) -> Response:
        item = APIClient.objects.filter(public_id=client_id).first()
        if item is None:
            raise ResourceNotFound()
        serializer = APIClientSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        from apps.core.concurrency import compare_and_swap

        values = (
            {"allowed_scopes": serializer.validated_data["scopes"]}
            if "scopes" in serializer.validated_data
            else {}
        )
        values.update({
            key: value for key, value in serializer.validated_data.items() if key != "scopes"
        })
        updated = compare_and_swap(
            APIClient,
            pk=item.pk,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=values,
        )
        return Response(
            _body(request, client_data(updated)),
            headers={"ETag": etag_for_version(updated.row_version)},
        )


class PlatformAPIClientRotateView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(parameters=[IDEMPOTENCY_KEY, IF_MATCH])
    def post(self, request: HttpRequest, client_id: str) -> Response:
        item = APIClient.objects.filter(public_id=client_id).first()
        if item is None:
            raise ResourceNotFound()

        def operation() -> StoredResponse:
            updated, secret = rotate_api_client_secret(
                item=item,
                actor=request.user,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_ctx(request),
            )
            data = client_data(updated)
            data["client_secret"] = secret
            return StoredResponse(
                200, _body(request, data), {"ETag": etag_for_version(updated.row_version)}
            )

        return _idempotent(request, payload={"client_id": client_id}, operation=operation)


class PlatformWebhookEndpointView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(operation_id="platform_integrations_webhook_endpoints_list")
    def get(self, request: HttpRequest) -> Response:
        return Response(
            _body(
                request, [webhook_data(item) for item in WebhookEndpoint.objects.order_by("name")]
            )
        )

    @extend_schema(request=WebhookSerializer, parameters=[IDEMPOTENCY_KEY])
    def post(self, request: HttpRequest) -> Response:
        serializer = WebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        url = str(values.pop("endpoint_url"))
        if not url.startswith("https://"):
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"endpoint_url": "HTTPS is required"})
        course_id = str(values.pop("course_id", ""))
        course = Course.objects.filter(public_id=course_id).first() if course_id else None
        if course_id and course is None:
            raise ResourceNotFound()
        allowlist = values.get("event_allowlist", [])
        if not allowlist:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"event_allowlist": "at least one event type is required"})
        secret = str(values.pop("secret", "") or generate_secret("whsec_"))

        def operation() -> StoredResponse:
            item = WebhookEndpoint.objects.create(
                name=values["name"],
                endpoint_url_ciphertext=seal(url),
                endpoint_url_digest=digest(url),
                secret_ciphertext=seal(secret),
                event_allowlist=values.get("event_allowlist", []),
                course=course,
                created_by=request.user,
            )
            data = webhook_data(item)
            data["secret"] = secret
            return StoredResponse(
                201, _body(request, data), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformWebhookEndpointDetailView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(operation_id="platform_integrations_webhook_endpoints_detail")
    def get(self, request: HttpRequest, endpoint_id: str) -> Response:
        item = WebhookEndpoint.objects.filter(public_id=endpoint_id).first()
        if item is None:
            raise ResourceNotFound()
        return Response(
            _body(request, webhook_data(item)), headers={"ETag": etag_for_version(item.row_version)}
        )

    def patch(self, request: HttpRequest, endpoint_id: str) -> Response:
        item = WebhookEndpoint.objects.filter(public_id=endpoint_id).first()
        if item is None:
            raise ResourceNotFound()
        serializer = WebhookSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        from apps.core.concurrency import compare_and_swap

        values = dict(serializer.validated_data)
        if "endpoint_url" in values:
            url = str(values.pop("endpoint_url"))
            if not url.startswith("https://"):
                from rest_framework.exceptions import ValidationError

                raise ValidationError({"endpoint_url": "HTTPS is required"})
            values["endpoint_url_ciphertext"] = seal(url)
            values["endpoint_url_digest"] = digest(url)
        values.pop("secret", None)
        if "course_id" in values:
            course_id = str(values.pop("course_id") or "")
            course = Course.objects.filter(public_id=course_id).first() if course_id else None
            if course_id and course is None:
                raise ResourceNotFound()
            values["course"] = course
        updated = compare_and_swap(
            WebhookEndpoint,
            pk=item.pk,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=values,
        )
        return Response(
            _body(request, webhook_data(updated)),
            headers={"ETag": etag_for_version(updated.row_version)},
        )


class PlatformWebhookRotateView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(parameters=[IDEMPOTENCY_KEY, IF_MATCH])
    def post(self, request: HttpRequest, endpoint_id: str) -> Response:
        item = WebhookEndpoint.objects.filter(public_id=endpoint_id).first()
        if item is None:
            raise ResourceNotFound()
        from apps.core.concurrency import compare_and_swap

        def operation() -> StoredResponse:
            secret = generate_secret("whsec_")
            updated = compare_and_swap(
                WebhookEndpoint,
                pk=item.pk,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                changes={
                    "previous_secret_ciphertext": item.secret_ciphertext,
                    "previous_secret_expires_at": timezone.now() + timedelta(minutes=15),
                    "secret_ciphertext": seal(secret),
                },
            )
            data = webhook_data(updated)
            data["secret"] = secret
            return StoredResponse(
                200, _body(request, data), {"ETag": etag_for_version(updated.row_version)}
            )

        return _idempotent(request, payload={"endpoint_id": endpoint_id}, operation=operation)


class PlatformWebhookDeliveryView(P13APIView):
    permission_classes = [IsPlatformPortal]

    def get(self, request: HttpRequest) -> Response:
        rows = WebhookDelivery.objects.select_related("endpoint").order_by("-created_at")
        return Response(_body(request, [delivery_data(item) for item in rows]))


class PlatformWebhookAttemptView(P13APIView):
    permission_classes = [IsPlatformPortal]

    def get(self, request: HttpRequest, delivery_id: str) -> Response:
        item = WebhookDelivery.objects.filter(public_id=delivery_id).first()
        if item is None:
            raise ResourceNotFound()
        return Response(
            _body(
                request, [attempt_data(attempt) for attempt in item.attempts.order_by("attempt_no")]
            )
        )


class PlatformWebhookRetryView(P13APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(parameters=[IDEMPOTENCY_KEY, IF_MATCH])
    def post(self, request: HttpRequest, delivery_id: str) -> Response:
        item = WebhookDelivery.objects.filter(public_id=delivery_id).first()
        if item is None:
            raise ResourceNotFound()
        if item.status not in (WebhookDelivery.Status.RETRY, WebhookDelivery.Status.DEAD):
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"status": "only failed or dead deliveries can be retried"})
        from apps.core.concurrency import compare_and_swap

        def operation() -> StoredResponse:
            updated = compare_and_swap(
                WebhookDelivery,
                pk=item.pk,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                changes={
                    "status": WebhookDelivery.Status.PENDING,
                    "next_retry_at": timezone.now(),
                    "last_error_code": "",
                },
            )
            return StoredResponse(
                200,
                _body(request, delivery_data(updated)),
                {"ETag": etag_for_version(updated.row_version)},
            )

        return _idempotent(request, payload={"delivery_id": delivery_id}, operation=operation)


class UserOIDCIdentityView(P13APIView):
    permission_classes = [IsAuthenticatedAccount]

    def get(self, request: HttpRequest) -> Response:
        return Response(
            _body(
                request,
                [
                    identity_data(item)
                    for item in OIDCIdentity.objects.filter(
                        account=request.user, status=OIDCIdentity.Status.ACTIVE
                    ).select_related("provider")
                ],
            )
        )

    @extend_schema(parameters=[IDEMPOTENCY_KEY, IF_MATCH])
    def post(self, request: HttpRequest, identity_id: str) -> Response:
        item = OIDCIdentity.objects.filter(public_id=identity_id, account=request.user).first()
        if item is None:
            raise ResourceNotFound()

        def operation() -> StoredResponse:
            updated = unlink_oidc_identity(
                item=item,
                actor=request.user,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_ctx(request),
            )
            return StoredResponse(
                200,
                _body(request, identity_data(updated)),
                {"ETag": etag_for_version(updated.row_version)},
            )

        return _idempotent(request, payload={"identity_id": identity_id}, operation=operation)


class OIDCStartView(P13APIView):
    permission_classes: list[type[BasePermission]] = []

    def get(self, request: HttpRequest, provider_key: str) -> Response:
        provider = OIDCProvider.objects.filter(
            key=provider_key, status=OIDCProvider.Status.ACTIVE
        ).first()
        if provider is None:
            raise ResourceNotFound()
        request_portal = str(getattr(request, "portal", ""))
        if provider.allowed_portals and request_portal not in provider.allowed_portals:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("OIDC provider is not enabled for this portal")
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(32)
        request.session[f"oidc:{state}"] = {
            "provider": provider_key,
            "nonce": nonce,
            "verifier": verifier,
            "portal": str(getattr(request, "portal", "")),
        }
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        query = urlencode({
            "client_id": provider.client_id,
            "response_type": "code",
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return Response(
            _body(
                request,
                {
                    "authorization_url": f"{provider.issuer.rstrip('/')}/authorize?{query}",
                    "state": state,
                },
            )
        )


class OIDCCallbackView(P13APIView):
    permission_classes: list[type[BasePermission]] = []

    def get(self, request: HttpRequest, provider_key: str) -> Response:
        state = str(request.query_params.get("state", ""))
        stored = request.session.pop(f"oidc:{state}", None)
        if (
            not stored
            or stored.get("provider") != provider_key
            or stored.get("nonce") != request.query_params.get("nonce")
        ):
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("OIDC state or nonce invalid")
        provider = OIDCProvider.objects.filter(
            key=provider_key, status=OIDCProvider.Status.ACTIVE
        ).first()
        if provider is None:
            raise ResourceNotFound()
        stored_portal = str(stored.get("portal", ""))
        request_portal = str(getattr(request, "portal", ""))
        if provider.allowed_portals and (
            stored_portal not in provider.allowed_portals
            or request_portal not in provider.allowed_portals
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("OIDC provider is not enabled for this portal")
        issuer = str(request.query_params.get("iss", "")).rstrip("/")
        if issuer != provider.issuer.rstrip("/"):
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("OIDC issuer invalid")
        code_verifier = str(request.query_params.get("code_verifier", ""))
        code = str(request.query_params.get("code", ""))
        if code and (
            not code_verifier
            or not hmac.compare_digest(code_verifier, str(stored.get("verifier", "")))
        ):
            from rest_framework.exceptions import AuthenticationFailed

            raise AuthenticationFailed("OIDC PKCE verifier invalid")
        if not getattr(request.user, "is_authenticated", False):
            from rest_framework.exceptions import NotAuthenticated

            raise NotAuthenticated()
        subject = str(request.query_params.get("subject", request.query_params.get("sub", "")))
        if not subject:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({
                "subject": "OIDC subject is required for the local callback adapter"
            })
        item = bind_oidc_identity(
            provider=provider,
            account=request.user,
            subject=subject,
            context=_ctx(request),
        )
        return Response(_body(request, identity_data(item)))
