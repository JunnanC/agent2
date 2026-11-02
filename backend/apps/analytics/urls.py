from django.urls import path

from .views import (
    PlatformAnalyticsProjectionView,
    PlatformAnalyticsQualityView,
    PlatformAnalyticsResourceCostView,
    PlatformOperationsView,
    PlatformRuntimeLogsView,
    TeachingAnalyticsOverviewView,
    TeachingAnalyticsQualityView,
    TeachingAnalyticsResourceCostView,
    TeachingAnalyticsRiskSignalDetailView,
    TeachingAnalyticsRiskSignalView,
    TeachingAnalyticsSeriesView,
    UserAnalyticsRecommendationView,
    UserAnalyticsRiskSignalView,
)

urlpatterns = [
    path("analytics/recommendations", UserAnalyticsRecommendationView.as_view()),
    path("analytics/risk-signals", UserAnalyticsRiskSignalView.as_view()),
    path(
        "teaching/courses/<str:course_id>/analytics/overview",
        TeachingAnalyticsOverviewView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/analytics/series",
        TeachingAnalyticsSeriesView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/analytics/risk-signals",
        TeachingAnalyticsRiskSignalView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/analytics/risk-signals/<str:signal_id>/resolve",
        TeachingAnalyticsRiskSignalDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/analytics/quality", TeachingAnalyticsQualityView.as_view()
    ),
    path(
        "teaching/courses/<str:course_id>/analytics/resource-costs",
        TeachingAnalyticsResourceCostView.as_view(),
    ),
    path("platform/analytics/quality", PlatformAnalyticsQualityView.as_view()),
    path("platform/analytics/resource-costs", PlatformAnalyticsResourceCostView.as_view()),
    path("platform/analytics/projection-jobs", PlatformAnalyticsProjectionView.as_view()),
    path("platform/operations/overview", PlatformOperationsView.as_view()),
    path("platform/operations/logs", PlatformRuntimeLogsView.as_view()),
]
