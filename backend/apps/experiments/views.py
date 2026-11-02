from collections.abc import Callable
from typing import Any

from django.db import models
from django.http import HttpRequest
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.archives.models import ArchiveJob
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.models import CompensationTask
from apps.core.pagination import PageSpec
from apps.courses.services import ActorContext

from .models import ExperimentTask, TaskPublication
from .selectors import (
    extension_request_for_teaching,
    paged_extension_requests,
    paged_teaching_tasks,
    paged_user_tasks,
    publication_for_course,
    publication_response_prefetches,
    publications_for_course,
    task_for_user,
    visible_extension_requests_for_user,
)
from .serializers import (
    DashboardDataSerializer,
    ExtensionDataSerializer,
    GenericResponseSerializer,
    PublicationDataSerializer,
    PublicationPatchSerializer,
    PublicationPublishSerializer,
    PublicationWriteSerializer,
    TaskDataSerializer,
    TaskExtensionDecisionSerializer,
    TaskExtensionWriteSerializer,
    TransitionDataSerializer,
    extension_data,
    publication_data,
    task_data,
    transition_data,
)
from .services import (
    allowed_actions,
    close_publication,
    create_publication,
    decide_extension,
    prerequisite_blockers_for_publication,
    publish_publication,
    request_extension,
    start_task_runtime,
    stop_task_runtime,
    teaching_progress,
    update_publication,
    withdraw_publication,
)

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _context(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        actor_ref=user.public_id,
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
        client_ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )


def _body(request: HttpRequest, data: Any) -> dict[str, object]:
    return {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}


def _response(
    request: HttpRequest, data: Any, *, status: int = 200, etag: int | None = None
) -> Response:
    response = Response(_body(request, data), status=status)
    response["Cache-Control"] = "private, no-store"
    if etag is not None:
        response["ETag"] = etag_for_version(etag)
    return response


def _page_response(
    request: HttpRequest, values: list[dict[str, object]], spec: PageSpec, total: int
) -> Response:
    response = Response({
        "data": values,
        "meta": {
            "page": spec.page,
            "page_size": spec.page_size,
            "total": total,
            "trace_id": str(getattr(request, "trace_id", "")),
        },
    })
    response["Cache-Control"] = "private, no-store"
    return response


def _page_spec(request: HttpRequest) -> PageSpec:
    return PageSpec.parse(
        request.query_params.get("page", 1), request.query_params.get("page_size", 20)
    )


def _idempotent(
    request: HttpRequest, *, payload: Any, operation: Callable[[], StoredResponse]
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


def _refresh_publication(publication_id: str) -> TaskPublication:
    return (
        TaskPublication.objects.select_related(
            "course",
            "template_version__template",
            "rubric_version__rubric",
            "runtime_adapter",
            "image",
            "resource_profile",
        )
        .prefetch_related(*publication_response_prefetches())
        .get(public_id=publication_id)
    )


class TeachingPublicationListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiments_list",
        responses=PublicationDataSerializer(many=True),
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                publication_data(item)
                for item in publications_for_course(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        operation_id="teaching_experiments_create",
        request=PublicationWriteSerializer,
        responses={201: PublicationDataSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = PublicationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_publication(
                course_id=course_id,
                actor=request.user,
                data=serializer.validated_data,
                context=_context(request),
            )
            item = _refresh_publication(item.public_id)
            return StoredResponse(
                201,
                _body(request, publication_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingPublicationDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiments_retrieve",
        responses=PublicationDataSerializer,
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        item = publication_for_course(
            actor=request.user, course_id=course_id, publication_id=publication_id
        )
        return _response(request, publication_data(item), etag=item.row_version)

    @extend_schema(
        operation_id="teaching_experiments_update",
        request=PublicationPatchSerializer,
        responses=PublicationDataSerializer,
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        serializer = PublicationPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_publication(
            course_id=course_id,
            publication_id=publication_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            data=serializer.validated_data,
            context=_context(request),
        )
        item = _refresh_publication(item.public_id)
        return _response(request, publication_data(item), etag=item.row_version)


class TeachingPublicationActionView(APIView):
    permission_classes = [IsTeachingPortal]
    action = ""

    def post(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))
        selected_ids: list[str] = []
        if self.action == "publish":
            serializer = PublicationPublishSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            selected_ids = list(serializer.validated_data.get("selected_enrollment_ids", []))

        def operation() -> StoredResponse:
            context = _context(request)
            if self.action == "publish":
                item, status = publish_publication(
                    course_id=course_id,
                    publication_id=publication_id,
                    actor=request.user,
                    expected_version=expected,
                    selected_ids=list(selected_ids),
                    context=context,
                )
            elif self.action == "close":
                item = close_publication(
                    course_id=course_id,
                    publication_id=publication_id,
                    actor=request.user,
                    expected_version=expected,
                    context=context,
                )
                status = 200
            else:
                item = withdraw_publication(
                    course_id=course_id,
                    publication_id=publication_id,
                    actor=request.user,
                    expected_version=expected,
                    context=context,
                )
                status = 200
            item = _refresh_publication(item.public_id)
            return StoredResponse(
                status,
                _body(request, publication_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(
            request,
            payload={"action": self.action, "selected_enrollment_ids": selected_ids},
            operation=operation,
        )


@extend_schema_view(
    post=extend_schema(
        operation_id="teaching_experiments_publish",
        request=PublicationPublishSerializer,
        responses={201: PublicationDataSerializer, 202: PublicationDataSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
)
class PublishPublicationView(TeachingPublicationActionView):
    action = "publish"


@extend_schema_view(
    post=extend_schema(
        operation_id="teaching_experiments_close",
        request=None,
        responses={200: PublicationDataSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
)
class ClosePublicationView(TeachingPublicationActionView):
    action = "close"


@extend_schema_view(
    post=extend_schema(
        operation_id="teaching_experiments_withdraw",
        request=None,
        responses={200: PublicationDataSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
)
class WithdrawPublicationView(TeachingPublicationActionView):
    action = "withdraw"


class TeachingTaskListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_tasks_list",
        responses=TaskDataSerializer(many=True),
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        spec = _page_spec(request)
        tasks, total = paged_teaching_tasks(
            actor=request.user,
            course_id=course_id,
            publication_id=publication_id,
            spec=spec,
            status=request.query_params.get("status", ""),
            query=request.query_params.get("q", ""),
        )
        return _page_response(
            request, [task_data(item, actions=allowed_actions(item)) for item in tasks], spec, total
        )


class TeachingProgressView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_progress",
        responses=GenericResponseSerializer,
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(request, teaching_progress(course_id=course_id, actor=request.user))


class TeachingExtensionRequestListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_extensions_list",
        responses=ExtensionDataSerializer(many=True),
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        spec = _page_spec(request)
        requests, total = paged_extension_requests(
            actor=request.user,
            course_id=course_id,
            spec=spec,
            status=request.query_params.get("status", ""),
            publication_id=request.query_params.get("publication_id", ""),
            student_id=request.query_params.get("student_id", ""),
        )
        for item in requests:
            item.decisions.all()
        return _page_response(request, [extension_data(item) for item in requests], spec, total)


class TeachingExtensionRequestDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_extension_retrieve",
        responses=ExtensionDataSerializer,
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, request_id: str) -> Response:
        item = extension_request_for_teaching(
            actor=request.user, course_id=course_id, request_id=request_id
        )
        return _response(request, extension_data(item), etag=item.row_version)


class TeachingExtensionDecisionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_extension_decide",
        request=TaskExtensionDecisionSerializer,
        responses=ExtensionDataSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, request_id: str) -> Response:
        serializer = TaskExtensionDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = decide_extension(
                course_id=course_id,
                request_id=request_id,
                actor=request.user,
                decision=serializer.validated_data["decision"],
                reason=serializer.validated_data.get("reason", ""),
                expected_version=expected,
                context=_context(request),
            )
            item = extension_request_for_teaching(
                actor=request.user, course_id=course_id, request_id=item.public_id
            )
            return StoredResponse(
                200,
                _body(request, extension_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class UserDashboardView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="me_dashboard",
        responses=DashboardDataSerializer,
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest) -> Response:
        from apps.workspaces.selectors import weekly_study_minutes_for_student

        spec = PageSpec(page=1, page_size=5)
        tasks, _ = paged_user_tasks(actor=request.user, spec=spec)
        counts: dict[str, int] = {}
        for item in ExperimentTask.objects.filter(student=request.user).values_list(
            "status", flat=True
        ):
            counts[item] = counts.get(item, 0) + 1
        return _response(
            request,
            {
                "counts": counts,
                "weekly_study": weekly_study_minutes_for_student(student=request.user),
                "next_tasks": [
                    task_data(
                        item,
                        blockers=prerequisite_blockers_for_publication(
                            publication=item.publication, student=request.user
                        ),
                        actions=allowed_actions(item, actor=request.user),
                    )
                    for item in tasks
                ],
            },
        )


class UserTaskListView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_list",
        responses=TaskDataSerializer(many=True),
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest) -> Response:
        spec = _page_spec(request)
        tasks, total = paged_user_tasks(
            actor=request.user,
            spec=spec,
            course_id=request.query_params.get("course", ""),
            status=request.query_params.get("status", ""),
            runtime_type=request.query_params.get("runtime_type", ""),
            query=request.query_params.get("q", ""),
        )
        return _page_response(
            request,
            [
                task_data(
                    item,
                    blockers=prerequisite_blockers_for_publication(
                        publication=item.publication, student=request.user
                    ),
                    actions=allowed_actions(item, actor=request.user),
                )
                for item in tasks
            ],
            spec,
            total,
        )


class UserTaskDetailView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_retrieve",
        responses=TaskDataSerializer,
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        item = task_for_user(actor=request.user, task_id=task_id)
        return _response(
            request,
            task_data(
                item,
                blockers=prerequisite_blockers_for_publication(
                    publication=item.publication, student=request.user
                ),
                actions=allowed_actions(item, actor=request.user),
            ),
            etag=item.row_version,
        )


class UserTaskTransitionsView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_transitions_list",
        responses=TransitionDataSerializer(many=True),
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        item = task_for_user(actor=request.user, task_id=task_id)
        return _response(
            request,
            [transition_data(row) for row in item.transitions.all().order_by("created_at", "id")],
        )


class UserTaskStartView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_start",
        request=None,
        responses={202: TaskDataSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item, _job = start_task_runtime(
                task_id=task_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
                payload=request.data if isinstance(request.data, dict) else {},
            )
            item = task_for_user(actor=request.user, task_id=item.public_id)
            return StoredResponse(
                202,
                _body(request, task_data(item, actions=allowed_actions(item, actor=request.user))),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class UserTaskStopView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="student_task_runtime_stop",
        request=None,
        responses=GenericResponseSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, runtime_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            instance = stop_task_runtime(
                runtime_id=runtime_id,
                actor=request.user,
                context=_context(request),
                expected_version=expected,
            )
            return StoredResponse(
                202 if instance.status == "DESTROYING" else 200,
                _body(
                    request,
                    {
                        "runtime_id": instance.public_id,
                        "task_id": instance.task.public_id,
                        "status": instance.status,
                    },
                ),
                {"ETag": etag_for_version(instance.task.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class UserTaskExtensionListView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_extensions_list",
        responses=ExtensionDataSerializer(many=True),
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        task_for_user(actor=request.user, task_id=task_id)
        return _response(
            request,
            [
                extension_data(item)
                for item in visible_extension_requests_for_user(actor=request.user, task_id=task_id)
            ],
        )


class UserTaskExtensionRequestView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_extension_requests_create",
        request=TaskExtensionWriteSerializer,
        responses={201: ExtensionDataSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = TaskExtensionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = request_extension(
                task_id=task_id,
                actor=request.user,
                data=serializer.validated_data,
                context=_context(request),
            )
            item = (
                item.__class__.objects.select_related("task", "requested_by")
                .prefetch_related("decisions")
                .get(pk=item.pk)
            )
            return StoredResponse(
                201,
                _body(request, extension_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformTaskAnomalyView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_experiment_task_anomalies",
        responses=GenericResponseSerializer,
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        failures = (
            ExperimentTask.objects.filter(status=ExperimentTask.Status.FAILED)
            .select_related("course", "publication", "student")
            .order_by("-updated_at")[:100]
        )
        publishing = (
            TaskPublication.objects.filter(status=TaskPublication.Status.PUBLISH_FAILED)
            .select_related("course")
            .order_by("-updated_at")[:100]
        )
        compensations = CompensationTask.objects.filter(
            status__in=(
                CompensationTask.Status.PENDING,
                CompensationTask.Status.IN_FLIGHT,
                CompensationTask.Status.RETRY,
                CompensationTask.Status.DEAD,
            ),
            subject_type__in=("TASK_PUBLICATION", "EXPERIMENT_TASK"),
        ).order_by("status", "next_attempt_at", "id")[:100]
        state_anomalies = ExperimentTask.objects.filter(
            status__in=(
                ExperimentTask.Status.COMPLETED,
                ExperimentTask.Status.CANCELLED,
                ExperimentTask.Status.EXPIRED,
            ),
            terminal_target__isnull=False,
        ).exclude(status=models.F("terminal_target"))[:100]
        archive_failures = (
            ArchiveJob.objects.filter(status=ArchiveJob.Status.FAILED)
            .select_related("task", "course", "failure_record", "compensation_task")
            .order_by("safe_recycle_at", "id")[:100]
        )
        reconciliation: list[dict[str, object]] = []
        publications = (
            TaskPublication.objects.filter(
                status__in=(
                    TaskPublication.Status.PUBLISHED,
                    TaskPublication.Status.CLOSED,
                    TaskPublication.Status.WITHDRAWN,
                )
            )
            .select_related("course", "template_version__template", "rubric_version__rubric")
            .prefetch_related("audience")
            .annotate(task_count=models.Count("tasks"))
        )
        for publication in publications:
            expected = publication_data(publication)["audience_count"]
            if expected != publication.task_count:
                reconciliation.append({
                    "publication_id": publication.public_id,
                    "course_id": publication.course.public_id,
                    "expected_task_count": expected,
                    "actual_task_count": publication.task_count,
                    "status": publication.status,
                })
            if len(reconciliation) >= 100:
                break
        return _response(
            request,
            {
                "failed_tasks": [
                    task_data(item, actions=allowed_actions(item)) for item in failures
                ],
                "failed_publications": [publication_data(item) for item in publishing],
                "compensation_backlog": [
                    {
                        "public_id": item.public_id,
                        "task_type": item.task_type,
                        "subject_type": item.subject_type,
                        "subject_ref": item.subject_ref,
                        "status": item.status,
                        "attempt_count": item.attempt_count,
                        "max_attempts": item.max_attempts,
                        "next_attempt_at": item.next_attempt_at,
                        "trace_id": item.trace_id,
                    }
                    for item in compensations
                ],
                "state_anomalies": [task_data(item) for item in state_anomalies],
                "archive_failures": [
                    {
                        "archive_id": item.public_id,
                        "task_id": item.task.public_id,
                        "course_id": item.course.public_id,
                        "terminal_target": item.terminal_target,
                        "safe_recycle_at": item.safe_recycle_at,
                        "safe_recycle_due": item.safe_recycle_at <= timezone.now(),
                        "error_code": (
                            item.failure_record.error_code if item.failure_record else ""
                        ),
                        "compensation_status": (
                            item.compensation_task.status if item.compensation_task else ""
                        ),
                        "trace_id": item.trace_id,
                    }
                    for item in archive_failures
                ],
                "reconciliation_anomalies": reconciliation,
            },
        )
