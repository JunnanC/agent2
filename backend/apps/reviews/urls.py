from django.urls import path

from .views import (
    PlatformReviewMonitorView,
    RubricListView,
    RubricVersionDetailView,
    RubricVersionListView,
    RubricVersionPublishView,
    TeachingAIScoreBatchAcceptView,
    TeachingAIScoreBatchDetailView,
    TeachingAIScoreBatchListView,
    TeachingAIScoreSuggestionAcceptView,
    TeachingAnnotationRevisionView,
    TeachingAnnotationRevokeView,
    TeachingCriterionScoresView,
    TeachingReviewAnnotationsView,
    TeachingReviewDecideView,
    TeachingReviewDetailView,
    TeachingReviewListView,
    TeachingSimilarityMatchesView,
    TeachingSimilarityRunDetailView,
    TeachingSimilarityRunListView,
    UserReviewResultView,
)

urlpatterns = [
    path("teaching/courses/<str:course_id>/rubrics", RubricListView.as_view()),
    path(
        "teaching/courses/<str:course_id>/rubrics/<str:rubric_id>/versions",
        RubricVersionListView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/rubric-versions/<str:version_id>",
        RubricVersionDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/rubric-versions/<str:version_id>/publish",
        RubricVersionPublishView.as_view(),
    ),
    path("teaching/courses/<str:course_id>/reviews", TeachingReviewListView.as_view()),
    path(
        "teaching/courses/<str:course_id>/ai-score-batches",
        TeachingAIScoreBatchListView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/ai-score-batches/<str:batch_id>",
        TeachingAIScoreBatchDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/ai-score-batches/<str:batch_id>/accept",
        TeachingAIScoreBatchAcceptView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/reviews/<str:review_id>/ai-score-suggestions/"
        "<str:suggestion_id>/accept",
        TeachingAIScoreSuggestionAcceptView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/reviews/<str:review_id>",
        TeachingReviewDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/reviews/<str:review_id>/criterion-scores",
        TeachingCriterionScoresView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/reviews/<str:review_id>/annotations",
        TeachingReviewAnnotationsView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/reviews/<str:review_id>/annotations/<str:annotation_id>/revisions",
        TeachingAnnotationRevisionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/reviews/<str:review_id>/annotations/<str:annotation_id>/revoke",
        TeachingAnnotationRevokeView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/reviews/<str:review_id>/decide",
        TeachingReviewDecideView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/similarity-runs",
        TeachingSimilarityRunListView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/similarity-runs/<str:run_id>",
        TeachingSimilarityRunDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/similarity-runs/<str:run_id>/matches",
        TeachingSimilarityMatchesView.as_view(),
    ),
    path("tasks/<str:task_id>/review-result", UserReviewResultView.as_view()),
    path("platform/reviews/summary", PlatformReviewMonitorView.as_view()),
]
