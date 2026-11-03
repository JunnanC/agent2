import time
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import SESSION_AUTH_TIME
from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.pagination import PageSpec

from .errors import ActiveEnrollmentRequired, FeatureNotAvailable, InvitationInvalid
from .models import CourseStaff, CourseStaffGrant, Enrollment, Invitation
from .selectors import (
    active_enrollment,
    active_staff,
    paged_courses,
    paged_enrollments,
    require_owner,
    student_courses_for_term,
    teacher_courses_for_term,
    visible_course,
    visible_enrollment,
)
from .serializers import (
    CheckResponseSerializer,
    ContextResponseSerializer,
    CourseCreateSerializer,
    CourseListResponseSerializer,
    CourseResponseSerializer,
    CourseUpdateSerializer,
    EnrollmentApplySerializer,
    EnrollmentListResponseSerializer,
    EnrollmentResponseSerializer,
    EnrollmentReviewSerializer,
    GrantCreateSerializer,
    GrantListResponseSerializer,
    GrantResponseSerializer,
    OwnershipTransferSerializer,
    ReasonSerializer,
    StaffCreateSerializer,
    StaffListResponseSerializer,
    StaffResponseSerializer,
    check_data,
    course_data,
    enrollment_data,
    grant_data,
    staff_data,
)
from .services import (
    ActorContext,
    apply_for_course,
    appoint_course_assistant,
    archive_check,
    archive_course,
    close_course,
    drop_enrollment,
    enrollment_exit_check,
    grant_course_capability,
    invitation_digest,
    publish_course,
    remove_enrollment,
    review_enrollment,
    revoke_course_capability,
    revoke_course_staff,
    transfer_course_ownership,
    update_course,
    withdraw_application,
)
from .services import create_course as create_course_service


def _context(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        actor_ref=user.public_id,
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
        client_ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )


def _meta(request: HttpRequest) -> dict[str, str]:
    return {"trace_id": str(getattr(request, "trace_id", ""))}


def _body(request: HttpRequest, data: Any) -> dict[str, object]:
    return {"data": data, "meta": _meta(request)}


def _response(
    request: HttpRequest,
    data: Any,
    *,
    status: int = 200,
    etag: str | None = None,
) -> Response:
    response = Response(_body(request, data), status=status)
    response["Cache-Control"] = "private, no-store"
    if etag:
        response["ETag"] = etag
    return response


def _page_response(
    request: HttpRequest,
    data: list[dict[str, object]],
    *,
    spec: PageSpec,
    total: int,
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


def _page_spec(request: HttpRequest) -> PageSpec:
    return PageSpec.parse(request.GET.get("page", 1), request.GET.get("page_size", 20))


class ContextView(APIView):
    class Permission(BasePermission):
        def has_permission(self, request: HttpRequest, view: object) -> bool:
            if not getattr(request.user, "is_authenticated", False):
                return False
            if str(getattr(request, "portal", "")) == "USER":
                return IsUserPortal().has_permission(request, view)
            if str(getattr(request, "portal", "")) == "TEACHING":
                return IsTeachingPortal().has_permission(request, view)
            if str(getattr(request, "portal", "")) == "PLATFORM":
                return IsPlatformPortal().has_permission(request, view)
            return False

    permission_classes = [Permission]

    @extend_schema(
        operation_id="context_retrieve",
        responses={200: ContextResponseSerializer},
        tags=["context"],
    )
    def get(self, request: HttpRequest) -> Response:
        from .services import current_academic_term

        term = current_academic_term()
        courses: list[dict[str, object]] = []
        if request.portal == "TEACHING":
            for course in teacher_courses_for_term(request.user, "current"):
                staff = active_staff(course=course, actor=request.user)
                if staff is not None:
                    courses.append({
                        "id": course.public_id,
                        "code": course.code,
                        "title": course.title,
                        "status": course.status,
                        "staff_role": staff.role,
                    })
            role = "TEACHER"
        elif request.portal == "USER":
            for course in student_courses_for_term(request.user, "current"):
                enrollment = active_enrollment(course=course, student=request.user)
                if enrollment is not None:
                    courses.append({
                        "id": course.public_id,
                        "code": course.code,
                        "title": course.title,
                        "status": course.status,
                        "enrollment_role": "STUDENT",
                    })
            role = "STUDENT"
        else:
            role = "PLATFORM_ADMIN"
        return _response(
            request,
            {
                "user_role": role,
                "current_term": {
                    "id": term.public_id,
                    "code": term.code,
                    "name": term.name,
                    "status": term.status,
                },
                "courses": courses,
            },
        )


class PublicCourseListView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="courses_list",
        responses={200: CourseListResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = _page_spec(request)
        enrollment_open_value = request.GET.get("enrollment_open")
        enrollment_open = (
            None if enrollment_open_value is None else enrollment_open_value.casefold() == "true"
        )
        values, total = paged_courses(
            actor=request.user,
            portal="USER",
            spec=spec,
            query=request.GET.get("q", ""),
            status=request.GET.get("status", ""),
            enrollment_open=enrollment_open,
        )
        return _page_response(
            request,
            [course_data(item) for item in values],
            spec=spec,
            total=total,
        )


class PublicCourseDetailView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="courses_retrieve",
        responses={200: CourseResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="USER", course_id=course_id)
        if active_enrollment(course=course, student=request.user) is None:
            raise ActiveEnrollmentRequired(detail={"course_id": course.public_id})
        return _response(request, course_data(course), etag=etag_for_version(course.row_version))


class CourseInvitationResolveView(APIView):
    """Resolve an invitation before consuming it, so students can apply directly."""

    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="courses_invitation_resolve",
        responses={200: CourseResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest) -> Response:
        code = str(request.GET.get("code", "")).strip()
        if not code:
            raise InvitationInvalid()
        invitation = (
            Invitation.objects.select_related("course")
            .filter(code_digest=invitation_digest(code), status="ACTIVE")
            .first()
        )
        if invitation is None or invitation.expires_at <= timezone.now() or invitation.used_count >= invitation.max_uses:
            raise InvitationInvalid()
        course = invitation.course
        if course.status != Course.Status.PUBLISHED:
            raise InvitationInvalid()
        if course.enrollment_start and course.enrollment_start > timezone.now():
            raise InvitationInvalid()
        if course.enrollment_end and course.enrollment_end < timezone.now():
            raise InvitationInvalid()
        return _response(request, course_data(course))


class CourseEnrollmentApplyView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        request=EnrollmentApplySerializer,
        responses={201: EnrollmentResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = EnrollmentApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            enrollment = apply_for_course(
                course_id=course_id,
                student=request.user,
                application_message=serializer.validated_data.get("application_message", ""),
                invitation_code=serializer.validated_data.get("invitation_code", ""),
                context=_context(request),
            )
            body = _body(request, enrollment_data(enrollment))
            return StoredResponse(
                201,
                body,
                {"ETag": etag_for_version(enrollment.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class MyEnrollmentListView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="me_enrollments_list",
        responses={200: EnrollmentListResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = _page_spec(request)
        values, total = paged_enrollments(
            actor=request.user,
            portal="USER",
            spec=spec,
            status=request.GET.get("status", ""),
        )
        return _page_response(
            request,
            [enrollment_data(item) for item in values],
            spec=spec,
            total=total,
        )


class MyEnrollmentDetailView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="me_enrollments_retrieve",
        responses={200: EnrollmentResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, enrollment_id: str) -> Response:
        value = visible_enrollment(
            actor=request.user,
            portal="USER",
            enrollment_id=enrollment_id,
        )
        return _response(
            request,
            enrollment_data(value, include_events=True),
            etag=etag_for_version(value.row_version),
        )


class MyEnrollmentWithdrawView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        request=None,
        responses={200: EnrollmentResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, enrollment_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = withdraw_application(
                enrollment_id=enrollment_id,
                student=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, enrollment_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(request, payload={}, operation=operation)


class MyEnrollmentDropCheckView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        responses={200: CheckResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, enrollment_id: str) -> Response:
        value = visible_enrollment(
            actor=request.user,
            portal="USER",
            enrollment_id=enrollment_id,
        )
        return _response(request, check_data(enrollment_exit_check(enrollment=value)))


class MyEnrollmentDropView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        request=ReasonSerializer,
        responses={200: EnrollmentResponseSerializer},
        tags=["courses"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, enrollment_id: str) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = drop_enrollment(
                enrollment_id=enrollment_id,
                student=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, enrollment_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingCourseListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_courses_list",
        responses={200: CourseListResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = _page_spec(request)
        values, total = paged_courses(
            actor=request.user,
            portal="TEACHING",
            spec=spec,
            query=request.GET.get("q", ""),
            status=request.GET.get("status", ""),
        )
        return _page_response(
            request,
            [course_data(item) for item in values],
            spec=spec,
            total=total,
        )

    @extend_schema(
        request=CourseCreateSerializer,
        responses={201: CourseResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = CourseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            data = serializer.validated_data
            value = create_course_service(
                actor=request.user,
                code=data["code"],
                title=data["title"],
                summary=data.get("summary", ""),
                description=data.get("description", ""),
                visibility=data["visibility"],
                enrollment_mode=data["enrollment_mode"],
                capacity=data.get("capacity"),
                enrollment_start=data.get("enrollment_start"),
                enrollment_end=data.get("enrollment_end"),
                teaching_start=data.get("teaching_start"),
                teaching_end=data.get("teaching_end"),
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(request, course_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingCourseDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_courses_retrieve",
        responses={200: CourseResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        return _response(request, course_data(course), etag=etag_for_version(course.row_version))

    @extend_schema(
        request=CourseUpdateSerializer,
        responses={200: CourseResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str) -> Response:
        serializer = CourseUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        value = update_course(
            course_id=course_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=serializer.validated_data,
            context=_context(request),
        )
        return _response(
            request,
            course_data(value),
            etag=etag_for_version(value.row_version),
        )


class TeachingCourseStateView(APIView):
    permission_classes = [IsTeachingPortal]
    action = ""

    @extend_schema(
        request=None,
        responses={200: CourseResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            function = {
                "publish": publish_course,
                "close": close_course,
                "archive": archive_course,
            }[self.action]
            value = function(
                course_id=course_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, course_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(request, payload={}, operation=operation)


class TeachingCoursePublishView(TeachingCourseStateView):
    action = "publish"


class TeachingCourseCloseView(TeachingCourseStateView):
    action = "close"


class TeachingCourseArchiveView(TeachingCourseStateView):
    action = "archive"


class TeachingCourseArchiveCheckView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        responses={200: CheckResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_owner(course=course, actor=request.user)
        return _response(request, check_data(archive_check(course=course)))


class TeachingCourseTransferOwnerView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=OwnershipTransferSerializer,
        responses={200: CourseResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = OwnershipTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = transfer_course_ownership(
                course_id=course_id,
                new_owner_id=serializer.validated_data["new_owner_id"],
                actor=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, course_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingCourseStaffListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        responses={200: StaffListResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_owner(course=course, actor=request.user)
        values = (
            CourseStaff.objects.filter(course=course)
            .select_related("user")
            .prefetch_related("grants")
        )
        return _response(request, [staff_data(item) for item in values])

    @extend_schema(
        request=StaffCreateSerializer,
        responses={201: StaffResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = StaffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            value = appoint_course_assistant(
                course_id=course_id,
                user_id=serializer.validated_data["user_id"],
                actor=request.user,
                reason=serializer.validated_data.get("reason", ""),
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(request, staff_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingCourseStaffRevokeView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=ReasonSerializer,
        responses={200: StaffResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, staff_id: str) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = revoke_course_staff(
                course_id=course_id,
                staff_id=staff_id,
                actor=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, staff_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingCourseGrantListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        responses={200: GrantListResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, staff_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_owner(course=course, actor=request.user)
        values = CourseStaffGrant.objects.filter(
            course_staff__course=course,
            course_staff__public_id=staff_id,
        ).order_by("capability")
        return _response(request, [grant_data(item) for item in values])

    @extend_schema(
        request=GrantCreateSerializer,
        responses={201: GrantResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, staff_id: str) -> Response:
        serializer = GrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            value = grant_course_capability(
                course_id=course_id,
                staff_id=staff_id,
                capability=serializer.validated_data["capability"],
                expires_at=serializer.validated_data.get("expires_at"),
                actor=request.user,
                reason=serializer.validated_data.get("reason", ""),
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(request, grant_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingCourseGrantRevokeView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=ReasonSerializer,
        responses={200: GrantResponseSerializer},
        tags=["teaching-courses"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(
        self,
        request: HttpRequest,
        course_id: str,
        staff_id: str,
        grant_id: str,
    ) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = revoke_course_capability(
                course_id=course_id,
                staff_id=staff_id,
                grant_id=grant_id,
                actor=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, grant_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingEnrollmentListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_course_enrollments_list",
        responses={200: EnrollmentListResponseSerializer},
        tags=["teaching-enrollments"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        spec = _page_spec(request)
        values, total = paged_enrollments(
            actor=request.user,
            portal="TEACHING",
            course=course,
            spec=spec,
            status=request.GET.get("status", ""),
        )
        return _page_response(
            request,
            [enrollment_data(item) for item in values],
            spec=spec,
            total=total,
        )


class TeachingEnrollmentDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    def _get(self, request: HttpRequest, course_id: str, enrollment_id: str) -> Enrollment:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        return visible_enrollment(
            actor=request.user,
            portal="TEACHING",
            enrollment_id=enrollment_id,
            course=course,
        )

    @extend_schema(
        operation_id="teaching_course_enrollments_retrieve",
        responses={200: EnrollmentResponseSerializer},
        tags=["teaching-enrollments"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, enrollment_id: str) -> Response:
        value = self._get(request, course_id, enrollment_id)
        return _response(
            request,
            enrollment_data(value, include_events=True),
            etag=etag_for_version(value.row_version),
        )


class TeachingEnrollmentReviewView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=EnrollmentReviewSerializer,
        responses={200: EnrollmentResponseSerializer},
        tags=["teaching-enrollments"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, enrollment_id: str) -> Response:
        serializer = EnrollmentReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = review_enrollment(
                course_id=course_id,
                enrollment_id=enrollment_id,
                decision=serializer.validated_data["decision"],
                note=serializer.validated_data.get("note", ""),
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, enrollment_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class TeachingEnrollmentRemovalCheckView(TeachingEnrollmentDetailView):
    @extend_schema(
        responses={200: CheckResponseSerializer},
        tags=["teaching-enrollments"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, enrollment_id: str) -> Response:
        value = self._get(request, course_id, enrollment_id)
        return _response(request, check_data(enrollment_exit_check(enrollment=value)))


class TeachingEnrollmentRemoveView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=ReasonSerializer,
        responses={200: EnrollmentResponseSerializer},
        tags=["teaching-enrollments"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, enrollment_id: str) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            value = remove_enrollment(
                course_id=course_id,
                enrollment_id=enrollment_id,
                actor=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, enrollment_data(value)),
                {"ETag": etag_for_version(value.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class PlatformCourseListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_courses_list",
        responses={200: CourseListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = _page_spec(request)
        values, total = paged_courses(
            actor=request.user,
            portal="PLATFORM",
            spec=spec,
            query=request.GET.get("q", ""),
            status=request.GET.get("status", ""),
        )
        return _page_response(
            request,
            [course_data(item) for item in values],
            spec=spec,
            total=total,
        )


class PlatformCourseDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_courses_retrieve",
        responses={200: CourseResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="PLATFORM", course_id=course_id)
        return _response(request, course_data(course), etag=etag_for_version(course.row_version))


class PlatformCourseFreezeShellView(APIView):
    permission_classes = [IsPlatformPortal]
    action = "freeze"

    @extend_schema(
        request=ReasonSerializer,
        responses={501: None},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visible_course(actor=request.user, portal="PLATFORM", course_id=course_id)
        max_age = getattr(settings, "PLATFORM_RECENT_AUTH_SECONDS", 300)
        authenticated_at = int(request.session.get(SESSION_AUTH_TIME, 0))
        if authenticated_at <= 0 or int(time.time()) - authenticated_at > max_age:
            raise FeatureNotAvailable(detail={"reason": "RECENT_AUTH_REQUIRED"})

        def operation() -> StoredResponse:
            trace_id = str(getattr(request, "trace_id", ""))
            append_audit(
                actor_ref=request.user.public_id,
                actor_portal="PLATFORM",
                actor_context={},
                action=f"course.compliance.{self.action}",
                course_ref=course_id,
                target_type="course",
                target_ref=course_id,
                before=None,
                after={"reason": serializer.validated_data["reason"]},
                result="DENIED",
                error_code="FEATURE_NOT_AVAILABLE",
                client_ip_hash=hash_client_ip(
                    client_ip(request),
                    salt=settings.AUDIT_IP_HASH_SALT,
                ),
                user_agent_summary=request.headers.get("User-Agent", ""),
                trace_id=trace_id,
            )
            body = {
                "error": {
                    "code": "FEATURE_NOT_AVAILABLE",
                    "message": "该治理能力尚未开放",
                    "detail": {"action": self.action, "course_id": course_id},
                    "trace_id": trace_id,
                    "retryable": False,
                }
            }
            return StoredResponse(501, body, {"Content-Type": "application/json"})

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class PlatformCourseUnfreezeShellView(PlatformCourseFreezeShellView):
    action = "unfreeze"
