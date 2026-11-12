from django.urls import path

from .assessment_review_views import AssessmentReviewListView, AssessmentTeachingView
from .assessment_views import (
    AssessmentDraftView,
    AssessmentHistoryView,
    AssessmentReportDraftView,
    AssessmentRunDetailView,
    AssessmentRunView,
    AssessmentView,
    ChoiceSubmitView,
    ProgrammingSubmitView,
)
from .views import (
    ClosePublicationView,
    PlatformTaskAnomalyView,
    PublishPublicationView,
    TeachingExtensionDecisionView,
    TeachingExtensionRequestDetailView,
    TeachingExtensionRequestListView,
    TeachingProgressView,
    TeachingPublicationDetailView,
    TeachingPublicationListView,
    TeachingPublicationRetakeView,
    TeachingTaskListView,
    UserDashboardView,
    UserLearningHistoryView,
    UserTaskDetailView,
    UserTaskExtensionListView,
    UserTaskExtensionRequestView,
    UserTaskListView,
    UserTaskStartView,
    UserTaskStopView,
    UserTaskTransitionsView,
    WithdrawPublicationView,
)

urlpatterns = [
    path(
        "teaching/courses/<str:course_id>/assessment-reviews",
        AssessmentReviewListView.as_view(), name="assessment-review-list",
    ),
    path(
        "teaching/courses/<str:course_id>/tasks/<str:task_id>/assessment",
        AssessmentTeachingView.as_view(), name="assessment-teaching-review",
    ),
    path("tasks/<str:task_id>/assessment", AssessmentView.as_view(), name="assessment"),
    path(
        "tasks/<str:task_id>/assessment/submissions", AssessmentHistoryView.as_view(),
        name="assessment-submission-history",
    ),
    path(
        "tasks/<str:task_id>/questions/<str:question_id>/runs",
        AssessmentRunView.as_view(), name="assessment-run-create",
    ),
    path(
        "tasks/<str:task_id>/assessment/runs/<int:run_id>",
        AssessmentRunDetailView.as_view(), name="assessment-run-detail",
    ),
    path(
        "tasks/<str:task_id>/questions/<str:question_id>/draft",
        AssessmentDraftView.as_view(), name="assessment-choice-draft",
    ),
    path(
        "tasks/<str:task_id>/questions/<str:question_id>/code/<str:language>",
        AssessmentDraftView.as_view(), name="assessment-code-draft",
    ),
    path(
        "tasks/<str:task_id>/sections/choice/submissions",
        ChoiceSubmitView.as_view(), name="assessment-choice-submit",
    ),
    path(
        "tasks/<str:task_id>/sections/programming/submissions",
        ProgrammingSubmitView.as_view(), name="assessment-programming-submit",
    ),
    path(
        "tasks/<str:task_id>/assessment/report-draft",
        AssessmentReportDraftView.as_view(), name="assessment-report-draft",
    ),
    path(
        "teaching/courses/<str:course_id>/tasks",
        TeachingTaskListView.as_view(),
        name="teaching-course-tasks",
    ),
    path("me/dashboard", UserDashboardView.as_view(), name="me-dashboard"),
    path("me/learning-history", UserLearningHistoryView.as_view(), name="me-learning-history"),
    path("tasks", UserTaskListView.as_view(), name="tasks"),
    path("tasks/<str:task_id>", UserTaskDetailView.as_view(), name="task-detail"),
    path("tasks/<str:task_id>/start", UserTaskStartView.as_view(), name="task-start"),
    path(
        "tasks/<str:task_id>/transitions",
        UserTaskTransitionsView.as_view(),
        name="task-transitions",
    ),
    path(
        "tasks/<str:task_id>/extensions",
        UserTaskExtensionListView.as_view(),
        name="task-extensions",
    ),
    path(
        "tasks/<str:task_id>/extension-requests",
        UserTaskExtensionRequestView.as_view(),
        name="task-extension-request",
    ),
    path(
        "student/task-runtimes/<str:runtime_id>/stop",
        UserTaskStopView.as_view(),
        name="student-task-runtime-stop",
    ),
    path(
        "teaching/courses/<str:course_id>/experiments",
        TeachingPublicationListView.as_view(),
        name="teaching-experiments",
    ),
    path(
        "teaching/courses/<str:course_id>/experiments/<str:publication_id>",
        TeachingPublicationDetailView.as_view(),
        name="teaching-experiment-detail",
    ),
    path(
        "teaching/courses/<str:course_id>/experiments/<str:publication_id>/publish",
        PublishPublicationView.as_view(),
        name="teaching-experiment-publish",
    ),
    path(
        "teaching/courses/<str:course_id>/experiments/<str:publication_id>/retakes",
        TeachingPublicationRetakeView.as_view(),
        name="teaching-experiment-retakes",
    ),
    path(
        "teaching/courses/<str:course_id>/experiments/<str:publication_id>/close",
        ClosePublicationView.as_view(),
        name="teaching-experiment-close",
    ),
    path(
        "teaching/courses/<str:course_id>/experiments/<str:publication_id>/withdraw",
        WithdrawPublicationView.as_view(),
        name="teaching-experiment-withdraw",
    ),
    path(
        "teaching/courses/<str:course_id>/experiments/<str:publication_id>/tasks",
        TeachingTaskListView.as_view(),
        name="teaching-experiment-tasks",
    ),
    path(
        "teaching/courses/<str:course_id>/progress",
        TeachingProgressView.as_view(),
        name="teaching-experiment-progress",
    ),
    path(
        "teaching/courses/<str:course_id>/extension-requests",
        TeachingExtensionRequestListView.as_view(),
        name="teaching-extension-requests",
    ),
    path(
        "teaching/courses/<str:course_id>/extension-requests/<str:request_id>",
        TeachingExtensionRequestDetailView.as_view(),
        name="teaching-extension-request",
    ),
    path(
        "teaching/courses/<str:course_id>/extension-requests/<str:request_id>/decide",
        TeachingExtensionDecisionView.as_view(),
        name="teaching-extension-decide",
    ),
    path(
        "platform/tasks/anomalies",
        PlatformTaskAnomalyView.as_view(),
        name="platform-task-anomalies",
    ),
]
