from typing import Any

from django.db.models import Count, Q, Sum
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.models import AuditLog
from apps.courses.services import ActorContext

from .models import (
    CourseDaily,
    CourseQualitySnapshot,
    LearningRecommendation,
    ResourceCostDaily,
    StudentRiskSignal,
)
from .observability import operations_summary, query_runtime_logs
from .selectors import (
    course_costs,
    course_daily,
    course_quality,
    course_risk_signals,
    teaching_course,
    user_recommendations,
    user_risk_signals,
)
from .serializers import (
    AnalyticsResponseSerializer,
    RiskResolveSerializer,
    cost_data,
    daily_data,
    quality_data,
    recommendation_data,
    risk_data,
)
from .services import PROJECTION_VERSION, resolve_risk_signal

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


class AnalyticsAPIView(APIView):
    serializer_class = AnalyticsResponseSerializer


def _body(request: HttpRequest, data: Any) -> dict[str, Any]:
    return {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}


def _response(
    request: HttpRequest, data: Any, *, status: int = 200, etag: int | None = None
) -> Response:
    response = Response(_body(request, data), status=status)
    response["Cache-Control"] = "private, no-store"
    if etag is not None:
        response["ETag"] = etag_for_version(etag)
    return response


def _ctx(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        actor_ref=user.public_id, portal=str(request.portal), trace_id=str(request.trace_id)
    )


class UserAnalyticsRecommendationView(AnalyticsAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(tags=["notifications"], extensions={"x-portals": ["USER"]})
    def get(self, request: HttpRequest) -> Response:
        return _response(
            request,
            [recommendation_data(item) for item in user_recommendations(actor=request.user)],
        )


class UserAnalyticsRiskSignalView(AnalyticsAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(tags=["notifications"], extensions={"x-portals": ["USER"]})
    def get(self, request: HttpRequest) -> Response:
        return _response(
            request, [risk_data(item) for item in user_risk_signals(actor=request.user)]
        )


class TeachingAnalyticsOverviewView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-analytics"], extensions={"x-portals": ["TEACHING"]})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        daily = course_daily(course=course).first()
        return _response(
            request, daily_data(daily) if daily else {"course_id": course.public_id, "metrics": {}}
        )


class TeachingAnalyticsSeriesView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        tags=["teaching-analytics"],
        parameters=[
            OpenApiParameter(
                "days",
                location=OpenApiParameter.QUERY,
                type=int,
                description="返回最近 N 天的每日投影(默认 28,上限 90)",
            )
        ],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        try:
            days = max(1, min(90, int(request.query_params.get("days", "28"))))
        except ValueError:
            days = 28
        rows = CourseDaily.objects.filter(
            course=course, projection_version=PROJECTION_VERSION
        ).order_by("-period_start")[:days]
        series = [daily_data(item) for item in reversed(list(rows))]
        return _response(request, {"course_id": course.public_id, "series": series})


class TeachingAnalyticsRiskSignalView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-analytics"], extensions={"x-portals": ["TEACHING"]})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        return _response(request, [risk_data(item) for item in course_risk_signals(course=course)])


class TeachingAnalyticsRiskSignalDetailView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=RiskResolveSerializer,
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["teaching-analytics"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, signal_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        serializer = RiskResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signal = StudentRiskSignal.objects.filter(public_id=signal_id, course=course).first()
        if signal is None:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound()

        def operation() -> StoredResponse:
            updated = resolve_risk_signal(
                signal_id=signal_id,
                actor=request.user,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_ctx(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                200,
                _body(request, risk_data(updated)),
                {"ETag": etag_for_version(updated.row_version)},
            )

        result = execute_idempotent(
            principal=PrincipalScope(request.user.public_id, "SESSION", str(request.portal)),
            method=request.method,
            endpoint=request.path,
            key=getattr(request, "idempotency_key", request.headers.get("Idempotency-Key")),
            payload=serializer.validated_data,
            operation=operation,
        )
        response = Response(result.body, status=result.status_code, headers=dict(result.headers))
        if result.replayed:
            response["X-Idempotent-Replayed"] = "true"
        return response


class TeachingAnalyticsQualityView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-analytics"], extensions={"x-portals": ["TEACHING"]})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                quality_data(item)
                for item in course_quality(
                    course=teaching_course(actor=request.user, course_id=course_id)
                )
            ],
        )


class TeachingAnalyticsResourceCostView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-analytics"], extensions={"x-portals": ["TEACHING"]})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                cost_data(item)
                for item in course_costs(
                    course=teaching_course(actor=request.user, course_id=course_id)
                )
            ],
        )


class PlatformAnalyticsQualityView(AnalyticsAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-analytics"], extensions={"x-portals": ["PLATFORM"]})
    def get(self, request: HttpRequest) -> Response:
        rows = CourseQualitySnapshot.objects.values("projection_version").annotate(
            count=Count("id"), total_score=Sum("quality_score")
        )
        return _response(request, list(rows))


class PlatformAnalyticsResourceCostView(AnalyticsAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-analytics"], extensions={"x-portals": ["PLATFORM"]})
    def get(self, request: HttpRequest) -> Response:
        rows = (
            ResourceCostDaily.objects.values("period_start", "resource_type")
            .annotate(amount_minor=Sum("amount_minor"), units=Sum("units"))
            .order_by("-period_start")
        )
        return _response(request, list(rows))


class PlatformAnalyticsProjectionView(AnalyticsAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-analytics"], extensions={"x-portals": ["PLATFORM"]})
    def get(self, request: HttpRequest) -> Response:
        rows = []
        for model, kind in (
            (CourseDaily, "course_daily"),
            (StudentRiskSignal, "risk"),
            (CourseQualitySnapshot, "quality"),
            (LearningRecommendation, "recommendation"),
            (ResourceCostDaily, "resource_cost"),
        ):
            item = model.objects.order_by("-calculated_at").first()
            rows.append({
                "kind": kind,
                "projection_version": item.projection_version if item else None,
                "source_cursor": item.source_cursor if item else None,
                "calculated_at": item.calculated_at if item else None,
            })
        return _response(request, rows)


class PlatformOperationsView(AnalyticsAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-analytics"], extensions={"x-portals": ["PLATFORM"]})
    def get(self, request: HttpRequest) -> Response:
        return _response(
            request,
            operations_summary(trace_id=str(getattr(request, "trace_id", ""))),
        )


class PlatformRuntimeLogsView(AnalyticsAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-analytics"], extensions={"x-portals": ["PLATFORM"]})
    def get(self, request: HttpRequest) -> Response:
        try:
            limit = int(request.query_params.get("limit", "50"))
        except ValueError:
            limit = 50
        return _response(
            request,
            query_runtime_logs(
                limit=limit,
                trace_id=request.query_params.get("trace_id", ""),
                level=request.query_params.get("level", ""),
            ),
        )


class PlatformAuditLogsView(AnalyticsAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-analytics"], extensions={"x-portals": ["PLATFORM"]})
    def get(self, request: HttpRequest) -> Response:
        from apps.core.pagination import PageSpec

        spec = PageSpec.parse(
            request.query_params.get("page", 1), request.query_params.get("page_size", 50)
        )
        rows = AuditLog.objects.order_by("-created_at", "-id")
        if trace_id := request.query_params.get("trace_id", ""):
            rows = rows.filter(trace_id=trace_id)
        if search := request.query_params.get("search", ""):
            rows = rows.filter(
                Q(action__icontains=search)
                | Q(actor_ref__icontains=search)
                | Q(target_ref__icontains=search)
                | Q(trace_id__icontains=search)
            )
        total = rows.count()
        data = [{
            "id": str(item.pk), "occurred_at": item.created_at,
            "actor": item.actor_ref, "action": item.action,
            "target": f"{item.target_type}:{item.target_ref}",
            "result": item.result, "trace_id": item.trace_id,
        } for item in rows[spec.offset:spec.offset + spec.page_size]]
        response = _response(request, data)
        response.data["meta"].update(
            {"total": total, "page": spec.page, "page_size": spec.page_size}
        )
        return response
