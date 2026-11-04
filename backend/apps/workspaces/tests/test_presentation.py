import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.provisioning.evaluator import public_report
from apps.workspaces.presentation import asset_text, public_examples


class StudentPresentationTests(SimpleTestCase):
    def test_asset_read_is_bounded_verified_and_closes_the_stream(self) -> None:
        value = b"# Manual\n"
        asset = SimpleNamespace(
            status="ACTIVE", scan_status="CLEAN", size_bytes=len(value),
            digest_sha256=hashlib.sha256(value).hexdigest(), bucket="private",
            object_key="private/manual", object_version="frozen-version",
        )
        with patch("apps.workspaces.presentation.S3ObjectStorage") as storage:
            stream = io.BytesIO(value)
            storage.return_value.open_object.return_value = SimpleNamespace(body=stream)
            self.assertEqual(asset_text(asset), value.decode())
            self.assertTrue(stream.closed)
            storage.assert_called_once_with(timeout_seconds=3)
            storage.return_value.open_object.assert_called_once_with(
                bucket="private", object_key="private/manual", version_id="frozen-version"
            )
            asset.size_bytes = 300000
            self.assertIsNone(asset_text(asset))
            self.assertEqual(storage.return_value.open_object.call_count, 1)

    def test_examples_and_defensive_result_filter_hide_all_private_fields(self) -> None:
        cases = [{"input": f"in-{i}", "expected": f"answer-{i}"} for i in range(5)]
        count, examples = public_examples(json.dumps({"cases": cases}))
        self.assertEqual(count, 5)
        self.assertEqual(len(examples), 3)
        self.assertNotIn("answer-3", json.dumps(examples))
        report = public_report({"results": [
            {**case, "status": "FAILED", "stdout": f"output-{i}", "stderr": "log"}
            for i, case in enumerate(cases)
        ]})
        self.assertEqual(report["results"][3], {"status": "FAILED", "hidden": True})
        self.assertEqual(report["results"][0]["expected"], "answer-0")
