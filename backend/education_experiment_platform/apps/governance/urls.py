from django.urls import path

from .views import (
    AllowlistDetailView,
    AllowlistListView,
    AllowlistRevokeView,
    ImageDecisionView,
    ImageDetailView,
    ImageListView,
    PlatformAlertListView,
    PlatformUsageView,
    PolicyListView,
    QuotaDetailView,
    QuotaListView,
    ResourceProfileDetailView,
    ResourceProfileListView,
    ResourceProfileRetireView,
    ResourceProfileTransitionView,
    RuntimeAdapterDetailView,
    RuntimeAdapterListView,
    ScalingPolicyListView,
    StudentResourceSummaryView,
    TeachingGovernanceSummaryView,
)

urlpatterns = [
    path("platform/runtime-adapters", RuntimeAdapterListView.as_view()),
    path("platform/runtime-adapters/<str:adapter_id>", RuntimeAdapterDetailView.as_view()),
    path("platform/images", ImageListView.as_view()),
    path("platform/images/<str:image_id>", ImageDetailView.as_view()),
    path("platform/images/<str:image_id>/decide", ImageDecisionView.as_view()),
    path("platform/resource-profiles", ResourceProfileListView.as_view()),
    path(
        "platform/resource-profiles/<str:profile_id>",
        ResourceProfileDetailView.as_view(),
    ),
    path(
        "platform/resource-profiles/<str:profile_id>/activate",
        ResourceProfileTransitionView.as_view(),
    ),
    path(
        "platform/resource-profiles/<str:profile_id>/retire",
        ResourceProfileRetireView.as_view(),
    ),
    path("platform/quotas", QuotaListView.as_view()),
    path("platform/quotas/<str:quota_id>", QuotaDetailView.as_view()),
    path("platform/security-policies", PolicyListView.as_view()),
    path("platform/resource-scaling-policies", ScalingPolicyListView.as_view()),
    path("platform/network-allowlists", AllowlistListView.as_view()),
    path("platform/network-allowlists/<str:entry_id>", AllowlistDetailView.as_view()),
    path(
        "platform/network-allowlists/<str:entry_id>/revoke",
        AllowlistRevokeView.as_view(),
    ),
    path("platform/governance/usage", PlatformUsageView.as_view()),
    path("platform/governance/alerts", PlatformAlertListView.as_view()),
    path(
        "teaching/courses/<str:course_id>/governance",
        TeachingGovernanceSummaryView.as_view(),
    ),
    path(
        "me/courses/<str:course_id>/resource-summary",
        StudentResourceSummaryView.as_view(),
    ),
]
