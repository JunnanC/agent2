from django.urls import path

from .views import (
    PlatformCompensationView,
    TeachingArchiveDetailView,
    TeachingArchiveExportView,
    TeachingArchiveListView,
    UserArchiveView,
)

urlpatterns = [
    path("tasks/<str:task_id>/archive", UserArchiveView.as_view(), name="task-archive"),
    path(
        "teaching/courses/<str:course_id>/archives",
        TeachingArchiveListView.as_view(),
        name="teaching-archives",
    ),
    path(
        "teaching/courses/<str:course_id>/archives/<str:archive_id>",
        TeachingArchiveDetailView.as_view(),
        name="teaching-archive-detail",
    ),
    path(
        "teaching/courses/<str:course_id>/archives/<str:archive_id>/exports",
        TeachingArchiveExportView.as_view(),
        name="teaching-archive-export",
    ),
    path(
        "platform/compensations",
        PlatformCompensationView.as_view(),
        name="platform-compensations",
    ),
]
