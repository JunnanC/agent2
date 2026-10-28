from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.pagination import PageSpec

from .authentication import (
    enforce_csrf,
    establish_portal_session,
    portal_admission,
    refresh_current_session_security,
)
from .errors import InvalidCredentials
from .metrics import PORTAL_LOGIN_TOTAL
from .models import IdentityVerification, PlatformAdminAssignment, TeacherQualification, User
from .permissions import IsAuthenticatedAccount, IsPlatformPortal, IsUserPortal
from .security import (
    check_login_rate_limit,
    clear_login_rate_limit,
    client_ip,
    opaque_login_subject,
)
from .selectors import (
    eligible_portals,
    paged_admin_assignments,
    paged_teacher_qualifications,
    paged_users,
    paged_verifications,
    portal_permissions,
)
from .serializers import (
    AdminAssignmentListResponseSerializer,
    AdminAssignmentResponseSerializer,
    AdminAssignmentUpdateSerializer,
    CsrfResponseSerializer,
    IdentityReviewSerializer,
    IdentityVerificationUpdateSerializer,
    LoginInputSerializer,
    MeResponseSerializer,
    PasswordChangeSerializer,
    ProfileUpdateSerializer,
    QualificationGrantSerializer,
    QualificationListResponseSerializer,
    QualificationResponseSerializer,
    SessionStepUpInputSerializer,
    SessionStepUpResponseSerializer,
    TeacherQualificationUpdateSerializer,
    UserCreateSerializer,
    UserListResponseSerializer,
    UserResponseSerializer,
    UserStatusUpdateSerializer,
    VerificationListResponseSerializer,
    VerificationResponseSerializer,
    admin_assignment_data,
    qualification_data,
    user_data,
    verification_data,
)
from .services import (
    ActorContext,
    authenticate_credentials,
    change_password,
    change_teacher_qualification,
    create_user,
    grant_platform_admin,
    grant_teacher_qualification,
    record_login,
    review_identity_verification,
    revoke_all_sessions,
    revoke_platform_admin,
    set_account_status,
    update_identity_verification,
    update_own_profile,
    verify_session_password,
)


def _context(request: HttpRequest, *, actor_ref: str | None = None) -> ActorContext:
    user = getattr(request, "user", None)
    return ActorContext(
        actor_ref=actor_ref or (user.public_id if user else "anonymous"),
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
        client_ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )


def _meta(request: HttpRequest) -> dict[str, str]:
    return {"trace_id": str(getattr(request, "trace_id", ""))}


def _response(
    request: HttpRequest,
    data: Any,
    *,
    status: int = 200,
    etag: str | None = None,
) -> Response:
    response = Response({"data": data, "meta": _meta(request)}, status=status)
    response["Cache-Control"] = "private, no-store"
    if etag:
        response["ETag"] = etag
    return response


def _page_response(
    request: HttpRequest, data: list[dict[str, object]], *, spec: PageSpec, total: int
) -> Response:
    response = Response({
        "data": data,
        "meta": {
            "page": spec.page,
            "page_size": spec.page_size,
            "total": total,
            **_meta(request),
        },
    })
    response["Cache-Control"] = "private, no-store"
    return response


def _me_data(user: User, portal: str) -> dict[str, object]:
    from apps.courses.selectors import course_scope_summaries

    teacher = TeacherQualification.objects.filter(user=user).first()
    admin = PlatformAdminAssignment.objects.filter(user=user).first()
    return {
        **user_data(user),
        "portal": portal,
        "eligible_portals": eligible_portals(user),
        "teacher_qualification": teacher.status if teacher else None,
        "platform_admin_assignment": admin.status if admin else None,
        "permissions": portal_permissions(portal),
        "course_scopes": course_scope_summaries(actor=user, portal=portal),
    }


def _idempotent_response(
    request: HttpRequest,
    *,
    payload: Any,
    operation: Callable[[], StoredResponse],
) -> Response:
    user: User = request.user  # type: ignore[assignment]
    result = execute_idempotent(
        principal=PrincipalScope(user.public_id, "SESSION", str(request.portal)),
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


class CsrfView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    @extend_schema(
        responses={200: CsrfResponseSerializer},
        tags=["auth"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        get_token(request)
        return _response(request, {"csrf": "ready"})


class LoginView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    @extend_schema(
        request=LoginInputSerializer,
        responses={200: MeResponseSerializer},
        tags=["auth"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        enforce_csrf(request)
        serializer = LoginInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data["identifier"]
        portal = str(request.portal)
        ip_address = client_ip(request)
        rate_key = check_login_rate_limit(
            identifier=identifier,
            ip_address=ip_address,
            portal=portal,
        )
        try:
            user = authenticate_credentials(identifier, serializer.validated_data["password"])
            portal_admission(user, portal)
        except Exception as exc:
            code = getattr(exc, "code", "INVALID_CREDENTIALS")
            subject = opaque_login_subject(identifier, ip_address, portal)
            append_audit(
                actor_ref=subject,
                actor_portal=portal,
                actor_context={},
                action="auth.login",
                target_type="account",
                target_ref=subject,
                result="DENIED",
                error_code=code,
                client_ip_hash=hash_client_ip(ip_address, salt=settings.AUDIT_IP_HASH_SALT),
                user_agent_summary=request.headers.get("User-Agent", ""),
                trace_id=str(request.trace_id),
            )
            PORTAL_LOGIN_TOTAL.labels(portal=portal, result="denied").inc()
            if isinstance(exc, InvalidCredentials):
                raise
            raise
        user = record_login(user, expected_version=user.row_version)
        establish_portal_session(request, user=user, portal=portal)
        clear_login_rate_limit(rate_key)
        append_audit(
            actor_ref=user.public_id,
            actor_portal=portal,
            actor_context={},
            action="auth.login",
            target_type="account",
            target_ref=user.public_id,
            result="SUCCEEDED",
            client_ip_hash=hash_client_ip(ip_address, salt=settings.AUDIT_IP_HASH_SALT),
            user_agent_summary=request.headers.get("User-Agent", ""),
            trace_id=str(request.trace_id),
        )
        PORTAL_LOGIN_TOTAL.labels(portal=portal, result="succeeded").inc()
        return _response(
            request,
            _me_data(user, portal),
            etag=etag_for_version(user.row_version),
        )


class LogoutView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Session removed")},
        tags=["auth"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        enforce_csrf(request)
        request.session.flush()
        return Response(status=204)


class SessionStepUpView(APIView):
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        request=SessionStepUpInputSerializer,
        responses={200: SessionStepUpResponseSerializer},
        tags=["auth"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        enforce_csrf(request)
        serializer = SessionStepUpInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user: User = request.user  # type: ignore[assignment]
        portal = str(request.portal)
        ip_address = client_ip(request)
        rate_key = check_login_rate_limit(
            identifier=user.username,
            ip_address=ip_address,
            portal=portal,
        )
        if not verify_session_password(user, serializer.validated_data["password"]):
            append_audit(
                actor_ref=user.public_id,
                actor_portal=portal,
                actor_context={},
                action="auth.session.step_up",
                target_type="account",
                target_ref=user.public_id,
                result="DENIED",
                error_code="INVALID_CREDENTIALS",
                client_ip_hash=hash_client_ip(ip_address, salt=settings.AUDIT_IP_HASH_SALT),
                user_agent_summary=request.headers.get("User-Agent", ""),
                trace_id=str(request.trace_id),
            )
            PORTAL_LOGIN_TOTAL.labels(portal=portal, result="denied").inc()
            raise InvalidCredentials()
        refresh_current_session_security(request, user=user)
        clear_login_rate_limit(rate_key)
        append_audit(
            actor_ref=user.public_id,
            actor_portal=portal,
            actor_context={},
            action="auth.session.step_up",
            target_type="account",
            target_ref=user.public_id,
            result="SUCCEEDED",
            client_ip_hash=hash_client_ip(ip_address, salt=settings.AUDIT_IP_HASH_SALT),
            user_agent_summary=request.headers.get("User-Agent", ""),
            trace_id=str(request.trace_id),
        )
        PORTAL_LOGIN_TOTAL.labels(portal=portal, result="succeeded").inc()
        return _response(
            request,
            {
                "recent": True,
                "authenticated_at": timezone.now(),
            },
            etag=etag_for_version(user.row_version),
        )


class LogoutAllView(APIView):
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="All portal sessions revoked")},
        tags=["auth"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        user: User = request.user  # type: ignore[assignment]
        revoke_all_sessions(
            user=user,
            expected_version=user.row_version,
            context=_context(request),
            action="auth.logout_all",
        )
        request.session.flush()
        return Response(status=204)


class MeView(APIView):
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        responses={200: MeResponseSerializer},
        tags=["me"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        user: User = request.user  # type: ignore[assignment]
        return _response(
            request,
            _me_data(user, str(request.portal)),
            etag=etag_for_version(user.row_version),
        )

    @extend_schema(
        request=ProfileUpdateSerializer,
        responses={200: MeResponseSerializer},
        tags=["me"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def patch(self, request: HttpRequest) -> Response:
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user: User = request.user  # type: ignore[assignment]
        changed = update_own_profile(
            user=user,
            display_name=serializer.validated_data["display_name"],
            expected_version=parse_if_match(request.headers.get("If-Match")),
            context=_context(request),
        )
        return _response(
            request,
            _me_data(changed, str(request.portal)),
            etag=etag_for_version(changed.row_version),
        )


class PasswordView(APIView):
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        request=PasswordChangeSerializer,
        responses={200: MeResponseSerializer},
        tags=["me"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user: User = request.user  # type: ignore[assignment]
        expected_version = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            changed = change_password(
                user=user,
                current_password=serializer.validated_data["current_password"],
                new_password=serializer.validated_data["new_password"],
                expected_version=expected_version,
                context=_context(request),
            )
            refresh_current_session_security(request, user=changed)
            body = {"data": _me_data(changed, str(request.portal)), "meta": _meta(request)}
            return StoredResponse(200, body, {"ETag": etag_for_version(changed.row_version)})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class MyVerificationView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        responses={200: VerificationResponseSerializer},
        tags=["me"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest) -> Response:
        user: User = request.user  # type: ignore[assignment]
        verification = IdentityVerification.objects.select_related("user", "material_asset").get(
            user=user
        )
        return _response(
            request,
            verification_data(verification),
            etag=etag_for_version(verification.row_version),
        )

    @extend_schema(
        request=IdentityVerificationUpdateSerializer,
        responses={200: VerificationResponseSerializer},
        tags=["me"],
        extensions={"x-portals": ["USER"]},
    )
    def put(self, request: HttpRequest) -> Response:
        serializer = IdentityVerificationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user: User = request.user  # type: ignore[assignment]
        verification = update_identity_verification(
            user=user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            context=_context(request),
            **serializer.validated_data,
        )
        return _response(
            request,
            verification_data(verification),
            etag=etag_for_version(verification.row_version),
        )


class PlatformUsersView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_users_list",
        responses={200: UserListResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = PageSpec.parse(
            request.query_params.get("page", 1),
            request.query_params.get("page_size", 20),
        )
        users, total = paged_users(spec=spec, query=request.query_params.get("q", ""))
        return _page_response(request, [user_data(user) for user in users], spec=spec, total=total)

    @extend_schema(
        request=UserCreateSerializer,
        responses={201: UserResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            user = create_user(context=_context(request), **serializer.validated_data)
            body = {"data": user_data(user), "meta": _meta(request)}
            return StoredResponse(201, body, {"ETag": etag_for_version(user.row_version)})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class PlatformUserDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    def _get_user(self, user_id: str) -> User:
        try:
            return User.objects.get(public_id=user_id)
        except User.DoesNotExist as exc:
            raise ResourceNotFound() from exc

    @extend_schema(
        operation_id="platform_user_retrieve",
        responses={200: UserResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest, user_id: str) -> Response:
        user = self._get_user(user_id)
        return _response(request, user_data(user), etag=etag_for_version(user.row_version))

    @extend_schema(
        request=UserStatusUpdateSerializer,
        responses={200: UserResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def patch(self, request: HttpRequest, user_id: str) -> Response:
        serializer = UserStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changed = set_account_status(
            user_public_id=user_id,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            context=_context(request),
            status=serializer.validated_data["account_status"],
            reason=serializer.validated_data["reason"],
        )
        return _response(request, user_data(changed), etag=etag_for_version(changed.row_version))


class PlatformRevokeSessionsView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=None,
        responses={200: UserResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, user_id: str) -> Response:
        try:
            user = User.objects.get(public_id=user_id)
        except User.DoesNotExist as exc:
            raise ResourceNotFound() from exc

        def operation() -> StoredResponse:
            changed = revoke_all_sessions(
                user=user,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_context(request),
                action="platform.account.sessions.revoke",
            )
            body = {"data": user_data(changed), "meta": _meta(request)}
            return StoredResponse(200, body, {"ETag": etag_for_version(changed.row_version)})

        return _idempotent_response(request, payload={}, operation=operation)


class TeacherQualificationsView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        responses={200: QualificationListResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = PageSpec.parse(
            request.query_params.get("page", 1),
            request.query_params.get("page_size", 20),
        )
        values, total = paged_teacher_qualifications(
            spec=spec, status=request.query_params.get("status", "")
        )
        return _page_response(
            request, [qualification_data(item) for item in values], spec=spec, total=total
        )


class GrantTeacherQualificationView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=QualificationGrantSerializer,
        responses={201: QualificationResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, user_id: str) -> Response:
        serializer = QualificationGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = grant_teacher_qualification(
                user_public_id=user_id,
                reason=serializer.validated_data["reason"],
                expected_user_version=expected_version,
                actor=request.user,
                context=_context(request),
            )
            body = {"data": qualification_data(value), "meta": _meta(request)}
            return StoredResponse(201, body, {"ETag": etag_for_version(value.row_version)})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TeacherQualificationDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=TeacherQualificationUpdateSerializer,
        responses={200: QualificationResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def patch(self, request: HttpRequest, qualification_id: str) -> Response:
        serializer = TeacherQualificationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changed = change_teacher_qualification(
            qualification_public_id=qualification_id,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            actor=request.user,
            context=_context(request),
            **serializer.validated_data,
        )
        return _response(
            request,
            qualification_data(changed),
            etag=etag_for_version(changed.row_version),
        )


class AdminAssignmentsView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        responses={200: AdminAssignmentListResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = PageSpec.parse(
            request.query_params.get("page", 1),
            request.query_params.get("page_size", 20),
        )
        values, total = paged_admin_assignments(
            spec=spec, status=request.query_params.get("status", "")
        )
        return _page_response(
            request, [admin_assignment_data(item) for item in values], spec=spec, total=total
        )


class GrantAdminAssignmentView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=QualificationGrantSerializer,
        responses={201: AdminAssignmentResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, user_id: str) -> Response:
        serializer = QualificationGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = grant_platform_admin(
                user_public_id=user_id,
                reason=serializer.validated_data["reason"],
                expected_user_version=expected_version,
                actor=request.user,
                context=_context(request),
            )
            body = {"data": admin_assignment_data(value), "meta": _meta(request)}
            return StoredResponse(201, body, {"ETag": etag_for_version(value.row_version)})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class AdminAssignmentDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=AdminAssignmentUpdateSerializer,
        responses={200: AdminAssignmentResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def patch(self, request: HttpRequest, assignment_id: str) -> Response:
        serializer = AdminAssignmentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changed = revoke_platform_admin(
            assignment_public_id=assignment_id,
            reason=serializer.validated_data["reason"],
            expected_version=parse_if_match(request.headers.get("If-Match")),
            actor=request.user,
            context=_context(request),
        )
        return _response(
            request,
            admin_assignment_data(changed),
            etag=etag_for_version(changed.row_version),
        )


class VerificationsView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        responses={200: VerificationListResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = PageSpec.parse(
            request.query_params.get("page", 1),
            request.query_params.get("page_size", 20),
        )
        values, total = paged_verifications(
            spec=spec, status=request.query_params.get("status", "")
        )
        return _page_response(
            request, [verification_data(item) for item in values], spec=spec, total=total
        )


class ReviewVerificationView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=IdentityReviewSerializer,
        responses={200: VerificationResponseSerializer},
        tags=["platform-accounts"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, verification_id: str) -> Response:
        serializer = IdentityReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected_version = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            changed = review_identity_verification(
                verification_public_id=verification_id,
                decision=serializer.validated_data["decision"],
                reason=serializer.validated_data.get("reason", ""),
                expected_version=expected_version,
                actor=request.user,
                context=_context(request),
            )
            body = {"data": verification_data(changed), "meta": _meta(request)}
            return StoredResponse(200, body, {"ETag": etag_for_version(changed.row_version)})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)
