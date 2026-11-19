from django.urls import path

from .assessment_views import (
    AssessmentPartsView,
    PublicationReportTemplateView,
    StudentReportView,
    TeachingReportListView,
    TeachingReportView,
)
from .views import (
    PlatformReportScanAnomaliesView,
    UserReportAttachmentCompleteView,
    UserReportAttachmentCreateView,
    UserReportAttachmentStatusView,
)

urlpatterns = [
    path("tasks/<str:task_id>/report", StudentReportView.as_view(), name="student-report"),
    path(
        "teaching/courses/<str:course_id>/experiments/<str:publication_id>/report-template",
        PublicationReportTemplateView.as_view(), name="publication-report-template",
    ),
    path(
        "teaching/courses/<str:course_id>/experiment-reports",
        TeachingReportListView.as_view(), name="experiment-reports",
    ),
    path(
        "teaching/courses/<str:course_id>/tasks/<str:task_id>/report",
        TeachingReportView.as_view(), name="teaching-report",
    ),
    path(
        "teaching/courses/<str:course_id>/tasks/<str:task_id>/assessment/parts",
        AssessmentPartsView.as_view(), name="assessment-parts",
    ),
    path("tasks/<str:task_id>/attachments", UserReportAttachmentCreateView.as_view()),
    path(
        "tasks/<str:task_id>/attachments/<str:asset_id>/complete",
        UserReportAttachmentCompleteView.as_view(),
    ),
    path(
        "tasks/<str:task_id>/attachments/<str:asset_id>",
        UserReportAttachmentStatusView.as_view(),
    ),
    path("platform/reports/scan-anomalies", PlatformReportScanAnomaliesView.as_view()),
]
