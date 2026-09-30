from django.urls import path

from .views import (
    PlatformAgentModelRouteDetailView,
    PlatformAgentModelRouteView,
    PlatformAgentToolPolicyDetailView,
    PlatformAgentToolPolicyView,
    PlatformAgentUsageView,
    PlatformEvalCaseView,
    PlatformEvalRunListCreateView,
    PlatformEvalSuiteView,
    PlatformEvalView,
    TeachingAgentAnalyticsView,
    TeachingAgentOptionsView,
    TeachingEvalCaseView,
    TeachingEvalSuiteView,
    TeachingEvalView,
    TeachingFeedbackView,
    TeachingIngestionDetailView,
    TeachingKnowledgeBaseView,
    TeachingProfileActionView,
    TeachingProfileDetailView,
    TeachingProfileListCreateView,
    TeachingPromptVersionView,
    TeachingPromptView,
    TeachingSourceAssetCompleteView,
    TeachingSourceAssetDetailView,
    TeachingSourceAssetUploadView,
    TeachingSourceVersionView,
    TeachingSourceView,
    UserAgentFeedbackView,
    UserAgentMessagesView,
    UserAgentProfileView,
    UserAgentSessionDetailView,
    UserAgentSessionListCreateView,
    UserAgentTaskSessionCreateView,
    UserAgentToolDecisionView,
    UserAgentToolRequestView,
)

urlpatterns = [
    path("courses/<str:course_id>/agent-profile", UserAgentProfileView.as_view()),
    path("courses/<str:course_id>/agent-sessions", UserAgentSessionListCreateView.as_view()),
    path("tasks/<str:task_id>/agent-sessions", UserAgentTaskSessionCreateView.as_view()),
    path("agent-sessions/<str:session_id>", UserAgentSessionDetailView.as_view()),
    path("agent-sessions/<str:session_id>/messages", UserAgentMessagesView.as_view()),
    path("agent-tool-calls/<str:call_id>/decide", UserAgentToolDecisionView.as_view()),
    path("agent-sessions/<str:session_id>/tool-calls", UserAgentToolRequestView.as_view()),
    path("agent-messages/<str:message_id>/feedback", UserAgentFeedbackView.as_view()),
    path(
        "teaching/courses/<str:course_id>/agent-profiles", TeachingProfileListCreateView.as_view()
    ),
    path(
        "teaching/courses/<str:course_id>/agent-options", TeachingAgentOptionsView.as_view()
    ),
    path(
        "teaching/courses/<str:course_id>/agent-profiles/<str:profile_id>",
        TeachingProfileDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-profiles/<str:profile_id>/<str:action>",
        TeachingProfileActionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-knowledge-bases",
        TeachingKnowledgeBaseView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-knowledge-bases/<str:knowledge_base_id>/sources",
        TeachingSourceView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-sources/<str:source_id>/versions",
        TeachingSourceVersionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-sources/<str:source_id>/uploads",
        TeachingSourceAssetUploadView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-sources/<str:source_id>/assets/"
        "<str:asset_id>/complete",
        TeachingSourceAssetCompleteView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-source-assets/<str:asset_id>",
        TeachingSourceAssetDetailView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-ingestion-runs/<str:run_id>",
        TeachingIngestionDetailView.as_view(),
    ),
    path("teaching/courses/<str:course_id>/agent-prompt-templates", TeachingPromptView.as_view()),
    path(
        "teaching/courses/<str:course_id>/agent-prompt-templates/<str:template_id>/versions",
        TeachingPromptVersionView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-eval-runs/<str:run_id>", TeachingEvalView.as_view()
    ),
    path(
        "teaching/courses/<str:course_id>/agent-eval-suites",
        TeachingEvalSuiteView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-eval-suites/<str:suite_id>/cases",
        TeachingEvalCaseView.as_view(),
    ),
    path(
        "teaching/courses/<str:course_id>/agent-analytics",
        TeachingAgentAnalyticsView.as_view(),
    ),
    path("teaching/courses/<str:course_id>/agent-feedback", TeachingFeedbackView.as_view()),
    path(
        "teaching/courses/<str:course_id>/agent-feedback/<str:feedback_id>/triage",
        TeachingFeedbackView.as_view(),
    ),
    path("platform/agent/tool-policies", PlatformAgentToolPolicyView.as_view()),
    path(
        "platform/agent/tool-policies/<str:policy_id>",
        PlatformAgentToolPolicyDetailView.as_view(),
    ),
    path("platform/agent/model-routes", PlatformAgentModelRouteView.as_view()),
    path(
        "platform/agent/model-routes/<str:route_id>",
        PlatformAgentModelRouteDetailView.as_view(),
    ),
    path("platform/agent/eval-suites", PlatformEvalSuiteView.as_view()),
    path(
        "platform/agent/eval-suites/<str:suite_id>/cases", PlatformEvalCaseView.as_view()
    ),
    path("platform/agent/eval-runs", PlatformEvalRunListCreateView.as_view()),
    path("platform/agent/eval-runs/<str:run_id>", PlatformEvalView.as_view()),
    path("platform/agent/usage-costs", PlatformAgentUsageView.as_view()),
]
