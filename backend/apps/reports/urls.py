from django.urls import path

from .views import (
    PlatformReportScanAnomaliesView,
    TeachingSubmissionPreviewView,
    UserReportAttachmentCompleteView,
    UserReportAttachmentCreateView,
    UserReportAttachmentStatusView,
    UserReportVersionsView,
)

urlpatterns = [
    path("tasks/<str:task_id>/attachments", UserReportAttachmentCreateView.as_view()),
    path(
        "tasks/<str:task_id>/attachments/<str:asset_id>/complete",
        UserReportAttachmentCompleteView.as_view(),
    ),
    path(
        "tasks/<str:task_id>/attachments/<str:asset_id>",
        UserReportAttachmentStatusView.as_view(),
    ),
    path("tasks/<str:task_id>/report-versions", UserReportVersionsView.as_view()),
    path(
        "teaching/courses/<str:course_id>/tasks/<str:task_id>/submission-preview",
        TeachingSubmissionPreviewView.as_view(),
    ),
    path("platform/reports/scan-anomalies", PlatformReportScanAnomaliesView.as_view()),
]
