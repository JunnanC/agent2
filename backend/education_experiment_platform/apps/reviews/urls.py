from django.urls import path

from .views import (
    RubricListView,
    RubricVersionDetailView,
    RubricVersionListView,
    RubricVersionPublishView,
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
]
