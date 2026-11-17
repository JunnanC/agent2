from collections.abc import Callable
from typing import Any

from django.db.models import Count, Q, Sum
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.models import ObjectAsset
from apps.courses.services import ActorContext

from .assets import complete_source_asset_upload, create_source_asset_upload
from .models import (
    AgentMessage,
    AgentSession,
    AgentSource,
    AgentSourceVersion,
    AgentToolCall,
    EvalSuite,
    ModelRoute,
    ToolPolicy,
)
from .selectors import (
    eval_run_for_course,
    feedback_for_course,
    ingestion_for_course,
    messages_for_user,
    platform_eval_run,
    profile_for_course,
    profiles_for_course,
    prompt_templates_for_course,
    prompt_versions_for_course,
    session_for_user,
    teaching_course,
    teaching_knowledge_bases,
    user_course,
)
from .serializers import (
    AgentEnvelopeSerializer,
    EvalCaseWriteSerializer,
    EvalSuiteWriteSerializer,
    FeedbackWriteSerializer,
    KnowledgeBaseWriteSerializer,
    MessageWriteSerializer,
    ModelRoutePatchSerializer,
    ModelRouteWriteSerializer,
    PlatformEvalRunWriteSerializer,
    ProfilePatchSerializer,
    ProfileWriteSerializer,
    PromptWriteSerializer,
    SessionWriteSerializer,
    SourceAssetUploadSerializer,
    SourceVersionWriteSerializer,
    SourceWriteSerializer,
    ToolDecisionSerializer,
    ToolPolicyPatchSerializer,
    ToolPolicyWriteSerializer,
    ToolWriteSerializer,
    TriageSerializer,
    eval_case_data,
    eval_run_data,
    eval_suite_data,
    feedback_data,
    ingestion_data,
    knowledge_base_data,
    message_data,
    model_route_data,
    profile_data,
    prompt_data,
    prompt_version_data,
    session_data,
    source_data,
    source_version_data,
    tool_call_data,
    tool_policy_data,
)
from .services import (
    activate_profile,
    create_agent_session,
    create_course_agent_profile,
    create_eval_case,
    create_eval_run,
    create_eval_suite,
    create_knowledge_base,
    create_model_route,
    create_tool_policy,
    decide_tool_call,
    enqueue_agent_message,
    evaluate_profile,
    ingest_knowledge_source,
    publish_prompt_version,
    request_tool,
    retire_profile,
    submit_agent_feedback,
    triage_feedback,
    update_course_agent_profile,
    update_model_route,
    update_tool_policy,
)

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


class AgentAPIView(APIView):
    serializer_class = AgentEnvelopeSerializer


def _context(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        actor_ref=user.public_id,
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
        client_ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )


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


class UserAgentProfileView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_profile", tags=["agents"], extensions={"x-portals": ["USER"]}
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course, enrollment = user_course(actor=request.user, course_id=course_id)
        from .selectors import active_profile_for_course

        profile = active_profile_for_course(course=course)
        return _response(
            request,
            {
                "course_id": course.public_id,
                "enrollment_id": enrollment.public_id,
                "profile": profile_data(profile),
                "capabilities": {
                    "modes": profile.modes,
                    "tool_risk": profile.tool_policy and profile.tool_policy.risk,
                },
            },
        )


class UserAgentSessionListCreateView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_course_session_create",
        request=SessionWriteSerializer,
        tags=["agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = SessionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_agent_session(
                actor=request.user,
                course_id=course_id,
                mode=serializer.validated_data["mode"],
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(request, session_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class UserAgentTaskSessionCreateView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_task_session_create",
        request=SessionWriteSerializer,
        tags=["agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = SessionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        from apps.experiments.models import ExperimentTask

        task = (
            ExperimentTask.objects.filter(public_id=task_id, student=request.user)
            .select_related("course")
            .first()
        )
        if task is None:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound()

        def operation() -> StoredResponse:
            item = create_agent_session(
                actor=request.user,
                course_id=task.course.public_id,
                task_id=task_id,
                mode=serializer.validated_data["mode"],
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(request, session_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(
            request, payload={**serializer.validated_data, "task_id": task_id}, operation=operation
        )


class UserAgentSessionDetailView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_session_retrieve",
        tags=["agents"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, session_id: str) -> Response:
        item = session_for_user(actor=request.user, session_id=session_id)
        return _response(request, session_data(item), etag=item.row_version)


class UserAgentMessagesView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_messages_list", tags=["agents"], extensions={"x-portals": ["USER"]}
    )
    def get(self, request: HttpRequest, session_id: str) -> Response:
        return _response(
            request,
            [
                message_data(item)
                for item in messages_for_user(actor=request.user, session_id=session_id)
            ],
        )

    @extend_schema(
        operation_id="user_agent_message_create",
        request=MessageWriteSerializer,
        tags=["agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, session_id: str) -> Response:
        serializer = MessageWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = enqueue_agent_message(
                actor=request.user,
                session_id=session_id,
                body=serializer.validated_data["body"],
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(request, message_data(item)),
                {"Location": f"/api/v2/agent-sessions/{session_id}/messages"},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class UserAgentToolDecisionView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_tool_decide",
        request=ToolDecisionSerializer,
        tags=["agents"],
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, call_id: str) -> Response:
        serializer = ToolDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = decide_tool_call(
                actor=request.user,
                call_id=call_id,
                decision=serializer.validated_data["decision"],
                reason=serializer.validated_data.get("reason", ""),
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(
                    request,
                    {
                        "public_id": item.public_id,
                        "status": item.status,
                        "row_version": item.row_version,
                    },
                ),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class UserAgentToolRequestView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_tool_request",
        request=ToolWriteSerializer,
        tags=["agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, session_id: str) -> Response:
        serializer = ToolWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = request_tool(
                actor=request.user,
                session_id=session_id,
                tool_name=serializer.validated_data["tool_name"],
                arguments=serializer.validated_data.get("arguments", {}),
                context=_context(request),
            )
            return StoredResponse(202, _body(request, tool_call_data(item)), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class UserAgentFeedbackView(AgentAPIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_agent_feedback_create",
        request=FeedbackWriteSerializer,
        tags=["agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, message_id: str) -> Response:
        serializer = FeedbackWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message = (
            AgentMessage.objects.filter(public_id=message_id, session__student=request.user)
            .select_related("session")
            .first()
        )
        if message is None:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound()

        def operation() -> StoredResponse:
            item = submit_agent_feedback(
                actor=request.user,
                session_id=message.session.public_id,
                message_id=message_id,
                rating=serializer.validated_data["rating"],
                issue_type=serializer.validated_data.get("issue_type", ""),
                note=serializer.validated_data.get("note", ""),
                context=_context(request),
            )
            return StoredResponse(
                201, _body(request, {"public_id": item.public_id, "status": "OPEN"}), {}
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingProfileListCreateView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_agent_profiles_list",
        tags=["teaching-agents"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                profile_data(item)
                for item in profiles_for_course(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        operation_id="teaching_agent_profile_create",
        request=ProfileWriteSerializer,
        tags=["teaching-agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = ProfileWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_course_agent_profile(
                course_id=course_id,
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, profile_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingAgentOptionsView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-agents"])
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        routes = ModelRoute.objects.filter(status=ModelRoute.Status.ACTIVE).order_by(
            "key", "-version_no"
        )
        policies = ToolPolicy.objects.filter(status=ToolPolicy.Status.ACTIVE).filter(
            Q(course=course) | Q(course__isnull=True)
        )
        return _response(
            request,
            {
                "model_routes": [
                    {
                        "public_id": item.public_id,
                        "key": item.key,
                        "version_no": item.version_no,
                        "provider": item.provider,
                        "model_name": item.model_name,
                        "max_tokens": item.max_tokens,
                    }
                    for item in routes
                ],
                "tool_policies": [
                    {
                        "public_id": item.public_id,
                        "tool_name": item.tool_name,
                        "risk": item.risk,
                        "version_no": item.version_no,
                    }
                    for item in policies.order_by("tool_name", "-version_no")
                ],
            },
        )


class TeachingProfileDetailView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_agent_profile_retrieve",
        tags=["teaching-agents"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, profile_id: str) -> Response:
        item = profile_for_course(actor=request.user, course_id=course_id, profile_id=profile_id)
        return _response(request, profile_data(item), etag=item.row_version)

    @extend_schema(
        operation_id="teaching_agent_profile_update",
        request=ProfilePatchSerializer,
        tags=["teaching-agents"],
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, profile_id: str) -> Response:
        serializer = ProfilePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_course_agent_profile(
            course_id=course_id,
            profile_id=profile_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            values=serializer.validated_data,
            context=_context(request),
        )
        return _response(request, profile_data(item), etag=item.row_version)


class TeachingProfileActionView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_agent_profile_action",
        tags=["teaching-agents"],
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, profile_id: str, action: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            if action == "evaluate":
                item, runs = evaluate_profile(
                    course_id=course_id,
                    profile_id=profile_id,
                    actor=request.user,
                    expected_version=expected,
                    context=_context(request),
                )
                return StoredResponse(
                    202,
                    _body(
                        request,
                        {
                            "profile": profile_data(item),
                            "eval_runs": [eval_run_data(run) for run in runs],
                        },
                    ),
                    {
                        "Location": (
                            f"/api/v2/teaching/courses/{course_id}/agent-eval-runs/"
                            f"{runs[0].public_id}"
                        )
                    },
                )
            if action == "activate":
                item = activate_profile(
                    course_id=course_id,
                    profile_id=profile_id,
                    actor=request.user,
                    expected_version=expected,
                    context=_context(request),
                )
            elif action == "retire":
                item = retire_profile(
                    course_id=course_id,
                    profile_id=profile_id,
                    actor=request.user,
                    expected_version=expected,
                    context=_context(request),
                )
            else:
                from apps.core.errors import ResourceNotFound

                raise ResourceNotFound()
            return StoredResponse(
                200,
                _body(request, profile_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload={"action": action}, operation=operation)


class TeachingKnowledgeBaseView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_agent_knowledge_bases_list",
        tags=["teaching-agents"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                knowledge_base_data(item)
                for item in teaching_knowledge_bases(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        operation_id="teaching_agent_knowledge_base_create",
        request=KnowledgeBaseWriteSerializer,
        tags=["teaching-agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = KnowledgeBaseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_knowledge_base(
                course_id=course_id,
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, knowledge_base_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingSourceView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_agent_source_list",
        tags=["teaching-agents"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, knowledge_base_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        if not course.agent_knowledge_bases.filter(public_id=knowledge_base_id).exists():
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound()
        return _response(
            request,
            [
                source_data(item)
                for item in AgentSource.objects.filter(
                    course__public_id=course_id, knowledge_base__public_id=knowledge_base_id
                ).order_by("title")
            ],
        )

    @extend_schema(
        operation_id="teaching_agent_source_create",
        request=SourceWriteSerializer,
        tags=["teaching-agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, knowledge_base_id: str) -> Response:
        serializer = SourceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = __import__("apps.agents.services", fromlist=["create_source"]).create_source(
                course_id=course_id,
                knowledge_base_id=knowledge_base_id,
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201, _body(request, source_data(item)), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingSourceVersionView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_agent_source_version_create",
        request=SourceVersionWriteSerializer,
        tags=["teaching-agents"],
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, source_id: str) -> Response:
        serializer = SourceVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            version, run = ingest_knowledge_source(
                course_id=course_id,
                source_id=source_id,
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                202,
                _body(
                    request,
                    {
                        "source_version": source_version_data(version),
                        "ingestion_run": ingestion_data(run),
                    },
                ),
                {
                    "Location": (
                        f"/api/v2/teaching/courses/{course_id}/agent-ingestion-runs/{run.public_id}"
                    )
                },
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingSourceAssetUploadView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=SourceAssetUploadSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["teaching-agents"],
    )
    def post(self, request: HttpRequest, course_id: str, source_id: str) -> Response:
        serializer = SourceAssetUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            asset, upload = create_source_asset_upload(
                course_id=course_id,
                source_id=source_id,
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(
                    request,
                    {
                        "asset": {
                            "public_id": asset.public_id,
                            "scan_status": asset.scan_status,
                            "row_version": asset.row_version,
                        },
                        "upload": upload,
                    },
                ),
                {"ETag": etag_for_version(asset.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingSourceAssetCompleteView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=None,
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["teaching-agents"],
    )
    def post(
        self, request: HttpRequest, course_id: str, source_id: str, asset_id: str
    ) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            asset = complete_source_asset_upload(
                course_id=course_id,
                source_id=source_id,
                asset_id=asset_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(
                    request,
                    {
                        "public_id": asset.public_id,
                        "scan_status": asset.scan_status,
                        "row_version": asset.row_version,
                    },
                ),
                {
                    "Location": (
                        f"/api/v2/teaching/courses/{course_id}/agent-source-assets/"
                        f"{asset.public_id}"
                    )
                },
            )

        return _idempotent(request, payload={"asset_id": asset_id}, operation=operation)


class TeachingSourceAssetDetailView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-agents"])
    def get(self, request: HttpRequest, course_id: str, asset_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        try:
            asset = ObjectAsset.objects.get(
                public_id=asset_id,
                owner_type__in=("AGENT_SOURCE", "AGENT_SOURCE_VERSION"),
            )
            AgentSource.objects.get(
                course=course,
                public_id=(
                    asset.owner_ref
                    if asset.owner_type == "AGENT_SOURCE"
                    else AgentSourceVersion.objects.values_list("source__public_id", flat=True).get(
                        public_id=asset.owner_ref
                    )
                ),
            )
        except (
            ObjectAsset.DoesNotExist,
            AgentSource.DoesNotExist,
            AgentSourceVersion.DoesNotExist,
        ) as exc:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound() from exc
        return _response(
            request,
            {
                "public_id": asset.public_id,
                "scan_status": asset.scan_status,
                "failure_code": asset.failure_code,
                "row_version": asset.row_version,
            },
            etag=asset.row_version,
        )


class TeachingIngestionDetailView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    def get(self, request: HttpRequest, course_id: str, run_id: str) -> Response:
        return _response(
            request,
            ingestion_data(
                ingestion_for_course(actor=request.user, course_id=course_id, run_id=run_id)
            ),
        )


class TeachingPromptView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                prompt_data(item)
                for item in prompt_templates_for_course(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        request=PromptWriteSerializer, parameters=[IDEMPOTENCY_KEY], tags=["teaching-agents"]
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = PromptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = publish_prompt_version(
                course_id=course_id,
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, prompt_version_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingPromptVersionView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    def get(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        return _response(
            request,
            [
                prompt_version_data(item)
                for item in prompt_versions_for_course(
                    actor=request.user, course_id=course_id, template_id=template_id
                )
            ],
        )


class TeachingEvalView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    def get(self, request: HttpRequest, course_id: str, run_id: str) -> Response:
        return _response(
            request,
            eval_run_data(
                eval_run_for_course(actor=request.user, course_id=course_id, run_id=run_id)
            ),
        )


class TeachingEvalSuiteView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-agents"])
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        suites = EvalSuite.objects.filter(course=course).order_by("name", "id")[:200]
        return _response(request, [eval_suite_data(item) for item in suites])

    @extend_schema(
        request=EvalSuiteWriteSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["teaching-agents"],
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = EvalSuiteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_eval_suite(
                actor=request.user,
                course_id=course_id,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, eval_suite_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingEvalCaseView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-agents"])
    def get(self, request: HttpRequest, course_id: str, suite_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        try:
            suite = EvalSuite.objects.get(public_id=suite_id, course=course)
        except EvalSuite.DoesNotExist as exc:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound() from exc
        return _response(
            request,
            [eval_case_data(item) for item in suite.cases.order_by("created_at", "id")],
        )

    @extend_schema(
        request=EvalCaseWriteSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["teaching-agents"],
    )
    def post(self, request: HttpRequest, course_id: str, suite_id: str) -> Response:
        serializer = EvalCaseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_eval_case(
                actor=request.user,
                course_id=course_id,
                suite_id=suite_id,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(201, _body(request, eval_case_data(item)), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingAgentAnalyticsView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(tags=["teaching-agents"])
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        modes = list(
            AgentSession.objects.filter(course=course)
            .values("mode")
            .annotate(count=Count("id"))
            .order_by("mode")
        )
        answers = list(
            AgentMessage.objects.filter(
                session__course=course, role=AgentMessage.Role.ASSISTANT
            )
            .values("citation_status")
            .annotate(count=Count("id"), tokens=Sum("token_count"), cost_minor=Sum("cost_minor"))
            .order_by("citation_status")
        )
        feedback = list(
            feedback_for_course(actor=request.user, course_id=course_id)
            .values("rating")
            .annotate(count=Count("id"))
            .order_by("rating")
        )
        return _response(request, {"modes": modes, "answers": answers, "feedback": feedback})


class TeachingFeedbackView(AgentAPIView):
    permission_classes = [IsTeachingPortal]

    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                feedback_data(item)
                for item in feedback_for_course(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        request=TriageSerializer, parameters=[IDEMPOTENCY_KEY, IF_MATCH], tags=["teaching-agents"]
    )
    def post(self, request: HttpRequest, course_id: str, feedback_id: str) -> Response:
        serializer = TriageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = triage_feedback(
            course_id=course_id,
            feedback_id=feedback_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            context=_context(request),
            **serializer.validated_data,
        )
        return _response(
            request,
            {
                "public_id": item.public_id,
                "feedback_id": item.feedback.public_id,
                "status": item.status,
                "note": item.note,
                "row_version": item.row_version,
            },
            etag=item.row_version,
        )


class PlatformAgentToolPolicyView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    def get(self, request: HttpRequest) -> Response:
        return _response(
            request,
            [
                tool_policy_data(item)
                for item in ToolPolicy.objects.filter(course__isnull=True).order_by(
                    "tool_name", "-version_no"
                )[:200]
            ],
        )

    @extend_schema(
        request=ToolPolicyWriteSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-agents"],
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = ToolPolicyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_tool_policy(
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, tool_policy_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformAgentToolPolicyDetailView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=ToolPolicyPatchSerializer,
        parameters=[IF_MATCH],
        tags=["platform-agents"],
    )
    def patch(self, request: HttpRequest, policy_id: str) -> Response:
        serializer = ToolPolicyPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_tool_policy(
            policy_id=policy_id,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            values=serializer.validated_data,
            context=_context(request),
        )
        return _response(request, tool_policy_data(item), etag=item.row_version)


class PlatformAgentModelRouteView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-agents"])
    def get(self, request: HttpRequest) -> Response:
        return _response(
            request,
            [
                model_route_data(item)
                for item in ModelRoute.objects.order_by("key", "-version_no")[:200]
            ],
        )

    @extend_schema(
        request=ModelRouteWriteSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-agents"],
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = ModelRouteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_model_route(
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, model_route_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformAgentModelRouteDetailView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=ModelRoutePatchSerializer,
        parameters=[IF_MATCH],
        tags=["platform-agents"],
    )
    def patch(self, request: HttpRequest, route_id: str) -> Response:
        serializer = ModelRoutePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_model_route(
            route_id=route_id,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            values=serializer.validated_data,
            context=_context(request),
        )
        return _response(request, model_route_data(item), etag=item.row_version)


class PlatformEvalSuiteView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-agents"])
    def get(self, request: HttpRequest) -> Response:
        suites = EvalSuite.objects.filter(platform_managed=True, course__isnull=True).order_by(
            "name", "id"
        )[:200]
        return _response(request, [eval_suite_data(item) for item in suites])

    @extend_schema(
        request=EvalSuiteWriteSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-agents"],
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = EvalSuiteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_eval_suite(
                actor=request.user, context=_context(request), **serializer.validated_data
            )
            return StoredResponse(
                201,
                _body(request, eval_suite_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformEvalCaseView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-agents"])
    def get(self, request: HttpRequest, suite_id: str) -> Response:
        try:
            suite = EvalSuite.objects.get(
                public_id=suite_id, platform_managed=True, course__isnull=True
            )
        except EvalSuite.DoesNotExist as exc:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound() from exc
        return _response(
            request,
            [eval_case_data(item) for item in suite.cases.order_by("created_at", "id")],
        )

    @extend_schema(
        request=EvalCaseWriteSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-agents"],
    )
    def post(self, request: HttpRequest, suite_id: str) -> Response:
        serializer = EvalCaseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_eval_case(
                actor=request.user,
                suite_id=suite_id,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(201, _body(request, eval_case_data(item)), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformEvalRunListCreateView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        request=PlatformEvalRunWriteSerializer,
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-agents"],
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = PlatformEvalRunWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_eval_run(
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                202,
                _body(request, eval_run_data(item)),
                {"Location": f"/api/v2/platform/agent/eval-runs/{item.public_id}"},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class PlatformAgentUsageView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(tags=["platform-agents"])
    def get(self, request: HttpRequest) -> Response:
        usage = list(
            AgentMessage.objects.filter(role=AgentMessage.Role.ASSISTANT)
            .values("session__model_route", "citation_status")
            .annotate(count=Count("id"), tokens=Sum("token_count"), cost_minor=Sum("cost_minor"))
            .order_by("session__model_route", "citation_status")
        )
        tools = list(
            AgentToolCall.objects.values("risk", "state__status")
            .annotate(count=Count("id"))
            .order_by("risk", "state__status")
        )
        return _response(request, {"usage": usage, "tools": tools})


class PlatformEvalView(AgentAPIView):
    permission_classes = [IsPlatformPortal]

    def get(self, request: HttpRequest, run_id: str) -> Response:
        return _response(request, eval_run_data(platform_eval_run(run_id=run_id)))
