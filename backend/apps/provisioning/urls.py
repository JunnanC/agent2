from django.urls import path

from .views import (
    UserTaskProvisioningCancelView,
    UserTaskProvisioningJobView,
    UserTaskRetryView,
    UserTaskStartView,
)

urlpatterns = [
    path("tasks/<str:task_id>/start", UserTaskStartView.as_view(), name="provisioning-task-start"),
    path("tasks/<str:task_id>/retry", UserTaskRetryView.as_view(), name="provisioning-task-retry"),
    path(
        "tasks/<str:task_id>/provisioning-job",
        UserTaskProvisioningJobView.as_view(),
        name="provisioning-job",
    ),
    path(
        "tasks/<str:task_id>/provisioning-job/cancel",
        UserTaskProvisioningCancelView.as_view(),
        name="provisioning-job-cancel",
    ),
]
