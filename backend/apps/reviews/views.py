from collections.abc import Callable
from typing import Any

from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.pagination import PageSpec
from apps.courses.services import ActorContext

from .models import AIScoreBatch
from .selectors import (
    review_for_course,
    reviews_for_course,
    reviews_for_user_result,
    rubric_for_course,
    rubrics_for_course,
    similarity_matches_for_course,
    similarity_run_for_course,
    teaching_course,
    version_for_course,
)
from .serializers import (
    AIScoreBatchDataResponseSerializer,
    AIScoreBatchDetailResponseSerializer,
    AIScoreBatchResponseSerializer,
    AIScoreBatchWriteSerializer,
    AIScoreSuggestionResponseSerializer,
    AnnotationListResponseSerializer,
    AnnotationResponseSerializer,
    AnnotationRevisionWriteSerializer,
    AnnotationWriteSerializer,
    CriterionScoresResponseSerializer,
    CriterionScoresWriteSerializer,
    ReviewDecisionResponseSerializer,
    ReviewDecisionWriteSerializer,
    ReviewDetailResponseSerializer,
    ReviewListResponseSerializer,
    ReviewMonitorResponseSerializer,
    ReviewResultResponseSerializer,
    RubricListResponseSerializer,
    RubricResponseSerializer,
    RubricVersionCreateSerializer,
    RubricVersionListResponseSerializer,
    RubricVersionResponseSerializer,
    RubricVersionWriteSerializer,
    RubricWriteSerializer,
    SimilarityMatchListResponseSerializer,
    SimilarityRunResponseSerializer,
    SimilarityStartSerializer,
    ai_score_batch_data,
    ai_score_suggestion_data,
    annotation_data,
    criterion_scores_data,
    decision_data,
    review_detail_data,
    review_list_data,
    review_result_data,
    rubric_data,
    similarity_match_data,
    similarity_run_data,
    version_data,
)
from .services import (
    accept_ai_score_batch,
    accept_ai_score_suggestion,
    add_review_annotation,
    clone_rubric_version,
    create_rubric,
    create_rubric_version,
    decide_review,
    publish_rubric_version,
    review_monitor_summary,
    revise_review_annotation,
    score_review_criteria,
    start_ai_score_batch,
    start_similarity_run,
    update_rubric_version,
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


class RubricListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubrics_list",
        responses={200: RubricListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                rubric_data(item)
                for item in rubrics_for_course(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        operation_id="teaching_rubrics_create",
        request=RubricWriteSerializer,
        responses={201: RubricResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = RubricWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            values = serializer.validated_data
            item = create_rubric(
                course_id=course_id,
                actor=request.user,
                context=_context(request),
                name=values["name"],
                description=values.get("description", ""),
            )
            return StoredResponse(
                201,
                _body(request, rubric_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class RubricVersionListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubric_versions_list",
        responses={200: RubricVersionListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, rubric_id: str) -> Response:
        rubric = rubric_for_course(actor=request.user, course_id=course_id, rubric_id=rubric_id)
        versions = (
            rubric.versions.select_related("rubric")
            .prefetch_related("criteria")
            .order_by("-version_no")
        )
        return _response(request, [version_data(item) for item in versions])

    @extend_schema(
        operation_id="teaching_rubric_versions_create",
        request=RubricVersionCreateSerializer,
        responses={201: RubricVersionResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, rubric_id: str) -> Response:
        serializer = RubricVersionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            values = serializer.validated_data
            source_version_id = values.get("source_version_id")
            if source_version_id:
                item = clone_rubric_version(
                    course_id=course_id,
                    rubric_id=rubric_id,
                    source_version_id=source_version_id,
                    actor=request.user,
                    context=_context(request),
                )
            else:
                item = create_rubric_version(
                    course_id=course_id,
                    rubric_id=rubric_id,
                    actor=request.user,
                    title=values["title"],
                    description=values.get("description", ""),
                    total_score=values["total_score"],
                    criteria=values["criteria"],
                    context=_context(request),
                )
            item = version_for_course(
                actor=request.user, course_id=course_id, version_id=item.public_id
            )
            return StoredResponse(
                201,
                _body(request, version_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class RubricVersionDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubric_versions_retrieve",
        responses={200: RubricVersionResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        item = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(request, version_data(item), etag=item.row_version)

    @extend_schema(
        operation_id="teaching_rubric_versions_update",
        request=RubricVersionWriteSerializer,
        responses={200: RubricVersionResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = RubricVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        item = update_rubric_version(
            course_id=course_id,
            version_id=version_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            title=values["title"],
            description=values.get("description", ""),
            total_score=values["total_score"],
            criteria=values["criteria"],
            context=_context(request),
        )
        item = version_for_course(
            actor=request.user, course_id=course_id, version_id=item.public_id
        )
        return _response(request, version_data(item), etag=item.row_version)


class RubricVersionPublishView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubric_versions_publish",
        request=None,
        responses={200: RubricVersionResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = publish_rubric_version(
                course_id=course_id,
                version_id=version_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            item = version_for_course(
                actor=request.user, course_id=course_id, version_id=item.public_id
            )
            return StoredResponse(
                200,
                _body(request, version_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class TeachingReviewListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_reviews_list",
        responses={200: ReviewListResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        spec = PageSpec.parse(request.GET.get("page", 1), request.GET.get("page_size", 20))
        queryset = reviews_for_course(
            actor=request.user,
            course_id=course_id,
            status=request.GET.get("status", ""),
            publication_id=request.GET.get("publication_id", ""),
        )
        total = queryset.count()
        values = list(queryset[spec.offset : spec.offset + spec.page_size])
        response = Response(
            {
                "data": [review_list_data(item) for item in values],
                "meta": {
                    "page": spec.page,
                    "page_size": spec.page_size,
                    "total": total,
                    "trace_id": str(getattr(request, "trace_id", "")),
                },
            }
        )
        response["Cache-Control"] = "private, no-store"
        return response


class TeachingAIScoreBatchListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=AIScoreBatchWriteSerializer,
        responses={202: AIScoreBatchResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = AIScoreBatchWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            batch = start_ai_score_batch(
                course_id=course_id,
                publication_id=serializer.validated_data["publication_id"],
                actor=request.user,
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(request, ai_score_batch_data(batch)),
                {"ETag": etag_for_version(batch.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)

    @extend_schema(
        responses={200: AIScoreBatchResponseSerializer},
        parameters=[OpenApiParameter("publication_id", str, OpenApiParameter.QUERY)],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        spec = PageSpec.parse(request.GET.get("page", 1), request.GET.get("page_size", 20))
        queryset = AIScoreBatch.objects.filter(course=course).select_related(
            "course", "publication", "created_by"
        ).order_by("-created_at", "-id")
        if request.GET.get("publication_id"):
            queryset = queryset.filter(publication__public_id=request.GET["publication_id"])
        total = queryset.count()
        values = list(queryset[spec.offset : spec.offset + spec.page_size])
        return _response(
            request,
            {
                "batches": [ai_score_batch_data(item) for item in values],
                "page": spec.page,
                "page_size": spec.page_size,
                "total": total,
            },
        )


class TeachingAIScoreBatchDetailView(APIView):
    permission_classes = [IsTeachingPortal]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        operation_id="teaching_ai_score_batch_retrieve",
        request=None,
        responses={200: AIScoreBatchDetailResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, batch_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        try:
            batch = AIScoreBatch.objects.select_related("course", "publication", "created_by").get(
                public_id=batch_id, course=course
            )
        except AIScoreBatch.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        spec = PageSpec.parse(request.GET.get("page", 1), request.GET.get("page_size", 20))
        queryset = batch.suggestions.select_related("review__task__student").order_by("id")
        total = queryset.count()
        values = list(queryset[spec.offset : spec.offset + spec.page_size])
        return _response(
            request,
            {
                "batch": ai_score_batch_data(batch),
                "suggestions": [ai_score_suggestion_data(item) for item in values],
                "page": spec.page,
                "page_size": spec.page_size,
                "total": total,
            },
            etag=batch.row_version,
        )

    @extend_schema(
        operation_id="teaching_ai_score_batch_accept",
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        request=None,
        responses={200: AIScoreBatchDataResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, batch_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            batch = accept_ai_score_batch(
                course_id=course_id,
                batch_id=batch_id,
                actor=request.user,
                expected_batch_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, ai_score_batch_data(batch)),
                {"ETag": etag_for_version(batch.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class TeachingAIScoreBatchAcceptView(TeachingAIScoreBatchDetailView):
    http_method_names = ["post", "options"]


class TeachingAIScoreSuggestionAcceptView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_ai_score_suggestion_accept",
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        request=None,
        responses={200: AIScoreSuggestionResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(
        self,
        request: HttpRequest,
        course_id: str,
        review_id: str,
        suggestion_id: str,
    ) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            suggestion = accept_ai_score_suggestion(
                course_id=course_id,
                review_id=review_id,
                suggestion_id=suggestion_id,
                actor=request.user,
                expected_review_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, ai_score_suggestion_data(suggestion)),
                {"ETag": etag_for_version(suggestion.review.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class TeachingReviewDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_reviews_retrieve",
        parameters=[OpenApiParameter("include_source", str, OpenApiParameter.QUERY)],
        responses={200: ReviewDetailResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, review_id: str) -> Response:
        item = review_for_course(actor=request.user, course_id=course_id, review_id=review_id)
        return _response(
            request,
            review_detail_data(item, include_source=request.GET.get("include_source") == "1"),
            etag=item.row_version,
        )


class TeachingCriterionScoresView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_review_scores_list",
        responses={200: CriterionScoresResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, review_id: str) -> Response:
        item = review_for_course(actor=request.user, course_id=course_id, review_id=review_id)
        return _response(request, criterion_scores_data(item), etag=item.row_version)

    @extend_schema(
        operation_id="teaching_review_scores_update",
        request=CriterionScoresWriteSerializer,
        responses={200: CriterionScoresResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def put(self, request: HttpRequest, course_id: str, review_id: str) -> Response:
        serializer = CriterionScoresWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = score_review_criteria(
                course_id=course_id,
                review_id=review_id,
                actor=request.user,
                expected_version=expected,
                scores=serializer.validated_data["scores"],
                context=_context(request),
            )
            item = review_for_course(
                actor=request.user, course_id=course_id, review_id=item.public_id
            )
            return StoredResponse(
                200,
                _body(request, criterion_scores_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingReviewAnnotationsView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_review_annotations_list",
        responses={200: AnnotationListResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, review_id: str) -> Response:
        item = review_for_course(actor=request.user, course_id=course_id, review_id=review_id)
        return _response(request, [annotation_data(value) for value in item.annotations.all()])

    @extend_schema(
        operation_id="teaching_review_annotations_create",
        request=AnnotationWriteSerializer,
        responses={201: AnnotationResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, review_id: str) -> Response:
        serializer = AnnotationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            annotation, changed_review = add_review_annotation(
                course_id=course_id,
                review_id=review_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
                **serializer.validated_data,
            )
            annotation = annotation.__class__.objects.select_related(
                "review", "author", "report_version", "asset"
            ).prefetch_related("revisions__actor").get(pk=annotation.pk)
            return StoredResponse(
                201,
                _body(request, annotation_data(annotation)),
                {
                    "ETag": etag_for_version(annotation.row_version),
                    "X-Review-ETag": etag_for_version(changed_review.row_version),
                },
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingAnnotationRevisionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_review_annotation_revise",
        request=AnnotationRevisionWriteSerializer,
        responses={200: AnnotationResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(
        self, request: HttpRequest, course_id: str, review_id: str, annotation_id: str
    ) -> Response:
        serializer = AnnotationRevisionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = revise_review_annotation(
                course_id=course_id,
                review_id=review_id,
                annotation_id=annotation_id,
                actor=request.user,
                expected_version=expected,
                body=serializer.validated_data["body"],
                revoke=False,
                context=_context(request),
            )
            item = item.__class__.objects.select_related(
                "review", "author", "report_version", "asset"
            ).prefetch_related("revisions__actor").get(pk=item.pk)
            return StoredResponse(
                200,
                _body(request, annotation_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingAnnotationRevokeView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_review_annotation_revoke",
        request=None,
        responses={200: AnnotationResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(
        self, request: HttpRequest, course_id: str, review_id: str, annotation_id: str
    ) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = revise_review_annotation(
                course_id=course_id,
                review_id=review_id,
                annotation_id=annotation_id,
                actor=request.user,
                expected_version=expected,
                body="",
                revoke=True,
                context=_context(request),
            )
            item = item.__class__.objects.select_related(
                "review", "author", "report_version", "asset"
            ).prefetch_related("revisions__actor").get(pk=item.pk)
            return StoredResponse(
                200,
                _body(request, annotation_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class TeachingReviewDecideView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_reviews_decide",
        request=ReviewDecisionWriteSerializer,
        responses={200: ReviewDecisionResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, review_id: str) -> Response:
        serializer = ReviewDecisionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            decision, changed_review, task = decide_review(
                course_id=course_id,
                review_id=review_id,
                actor=request.user,
                expected_version=expected,
                decision=serializer.validated_data["decision"],
                requested_score=serializer.validated_data.get("score"),
                feedback=serializer.validated_data.get("feedback", ""),
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(
                    request,
                    {
                        **decision_data(decision),
                        "review_row_version": changed_review.row_version,
                        "task_status": task.status,
                        "task_row_version": task.row_version,
                    },
                ),
                {"ETag": etag_for_version(changed_review.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingSimilarityRunListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_similarity_runs_create",
        request=SimilarityStartSerializer,
        responses={202: SimilarityRunResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = SimilarityStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            run = start_similarity_run(
                course_id=course_id,
                review_id=serializer.validated_data["review_id"],
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(202, _body(request, similarity_run_data(run)), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingSimilarityRunDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_similarity_runs_retrieve",
        responses={200: SimilarityRunResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, run_id: str) -> Response:
        item = similarity_run_for_course(actor=request.user, course_id=course_id, run_id=run_id)
        return _response(request, similarity_run_data(item), etag=item.row_version)


class TeachingSimilarityMatchesView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_similarity_matches_list",
        responses={200: SimilarityMatchListResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, run_id: str) -> Response:
        values = similarity_matches_for_course(
            actor=request.user, course_id=course_id, run_id=run_id
        )
        return _response(request, [similarity_match_data(item) for item in values])


class UserReviewResultView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_review_result_retrieve",
        responses={200: ReviewResultResponseSerializer},
        tags=["tasks"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        values = list(reviews_for_user_result(actor=request.user, task_id=task_id))
        return _response(request, review_result_data(values))


class PlatformReviewMonitorView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_reviews_monitor",
        responses={200: ReviewMonitorResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _response(request, review_monitor_summary())
