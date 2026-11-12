from django.urls import path

from .views import (
    PlatformReportScanAnomaliesView,
    UserReportAttachmentCompleteView,
    UserReportAttachmentCreateView,
    UserReportAttachmentStatusView,
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
    path("platform/reports/scan-anomalies", PlatformReportScanAnomaliesView.as_view()),
]
