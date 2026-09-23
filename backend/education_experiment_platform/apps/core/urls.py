from django.urls import path

from .files import FileDownloadGrantCreateView, FileDownloadGrantRevokeView

urlpatterns = [
    path("files/<str:asset_id>/download-grants", FileDownloadGrantCreateView.as_view()),
    path("files/download-grants/<str:grant_id>/revoke", FileDownloadGrantRevokeView.as_view()),
]
