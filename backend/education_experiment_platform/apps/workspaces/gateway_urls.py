from django.urls import path

from .gateway import WorkspaceGatewayView

urlpatterns = [
    path(
        "<str:session_id>/<path:action>", WorkspaceGatewayView.as_view(), name="workspace-gateway"
    ),
]
