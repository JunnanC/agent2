from django.urls import path

from .internal import authorize_workspace

urlpatterns = [
    path("workspace-authorize", authorize_workspace, name="internal-workspace-authorize"),
]
