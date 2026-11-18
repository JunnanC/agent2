from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from apps.core.files import FileDownloadView


class FilePreviewTests(TestCase):
    def response(self, media_type, preview):
        request = APIRequestFactory().get("/files/token", {"preview": "1"} if preview else {})
        request = FileDownloadView().initialize_request(request)
        request.user = SimpleNamespace(public_id="student")
        request.portal = "USER"
        asset = SimpleNamespace(
            media_type=media_type,
            bucket="b",
            object_key="k",
            object_version="",
            original_name="report.pdf",
        )
        with (
            patch(
                "apps.core.files.get_download_target", return_value=(SimpleNamespace(pk=1), asset)
            ),
            patch("apps.core.files.consume_download_grant") as consume,
            patch("apps.core.files.object_storage") as storage,
        ):
            storage.return_value.open_object.return_value = SimpleNamespace(
                body=BytesIO(b"report"), content_length=6
            )
            response = FileDownloadView().get(request, "token")
            called = consume.called
        return response, called

    def test_pdf_preview_is_inline_and_download_is_attachment(self):
        for preview, disposition in ((True, "inline"), (False, "attachment")):
            response, consumed = self.response("application/pdf", preview)
            assert response["Content-Disposition"].startswith(disposition)
            assert response["Content-Security-Policy"].startswith("sandbox")
            assert response["Cache-Control"] == "private, no-store"
            assert consumed
            assert b"".join(response.streaming_content) == b"report"
            response.close()

    def test_active_content_cannot_preview_and_does_not_consume_grant(self):
        response, consumed = self.response("text/html", True)
        assert response.status_code == 415
        assert not consumed
