import hashlib
import io
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.core.models import ObjectAsset

from ..storage import WorkspaceStorageFailure, _read_object


class WorkspaceObjectReadTests(SimpleTestCase):
    @override_settings(WORKSPACE_SNAPSHOT_MAX_BYTES=16)
    def test_closes_object_stream_on_success_and_failure(self) -> None:
        class BrokenStream(io.BytesIO):
            def read(self, size: int | None = -1) -> bytes:
                raise OSError("storage connection failed")

        cases = [
            (io.BytesIO(b"code"), "", b"code"),
            (io.BytesIO(b"x" * 17), "WORKSPACE_FILE_TOO_LARGE", b"x" * 17),
            (BrokenStream(), "WORKSPACE_OBJECT_UNAVAILABLE", b""),
            (io.BytesIO(b"edited"), "WORKSPACE_OBJECT_INVALID", b"original"),
        ]
        for stream, error, expected in cases:
            with self.subTest(error=error):
                asset = cast(ObjectAsset, SimpleNamespace(
                    bucket="test", object_key="code", object_version="v1",
                    size_bytes=len(expected), digest_sha256=hashlib.sha256(expected).hexdigest(),
                ))
                with patch("apps.workspaces.storage.object_storage") as storage:
                    storage.return_value.open_object.return_value = SimpleNamespace(body=stream)
                    if error:
                        with self.assertRaises(WorkspaceStorageFailure) as raised:
                            _read_object(asset)
                        self.assertEqual(raised.exception.code, error)
                        self.assertEqual(
                            raised.exception.retryable, error == "WORKSPACE_OBJECT_UNAVAILABLE"
                        )
                    else:
                        self.assertEqual(_read_object(asset), expected)
                self.assertTrue(stream.closed)
