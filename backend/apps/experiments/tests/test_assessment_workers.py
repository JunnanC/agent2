import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.core.concurrency import compare_and_swap
from apps.provisioning.stdio import StdioResult

from ..assessment_workers import _claim, _finish, execute_assessment_job
from ..models import AssessmentRun


class AssessmentWorkerTests(TestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)

    def _run(self) -> AssessmentRun:
        # Only database references are needed when the source reader is explicitly injected.
        from apps.core.models import ObjectAsset
        from apps.workspaces.models import WorkspaceSnapshot

        asset = ObjectAsset.objects.create(
            bucket="test", object_key="source", digest_sha256="a" * 64, size_bytes=1,
            owner_type="WORKSPACE_TASK", owner_ref=self.task.public_id, purpose="SOURCE_SNAPSHOT",
            scan_status="CLEAN",
        )
        snapshot = WorkspaceSnapshot.objects.create(
            task=self.task, question=self.question, asset=asset, version_no=1, client_seq=1,
            digest_sha256="a" * 64, size_bytes=1, language="python", saved_at=timezone.now(),
            trace_id="a" * 32,
        )
        self.question.question_spec["limits"] = {
            "python": {"timeout_seconds": 3, "memory_mb": 256},
        }
        # Do not mutate published rows: the worker test injects its related question below.
        return AssessmentRun.objects.create(
            task=self.task, question=self.question, snapshot=snapshot,
        )

    def test_late_worker_cannot_overwrite_new_lease(self) -> None:
        run = self._run()
        claimed = _claim(AssessmentRun, run.pk)
        assert _claim(AssessmentRun, run.pk) is None
        compare_and_swap(
            AssessmentRun, pk=run.pk, expected_version=claimed.row_version,
            changes={"lease_token": uuid.uuid4()},
        )
        _finish(claimed, status="COMPLETED", stdout="stale result")
        run.refresh_from_db()
        assert run.stdout == ""
        assert run.status == "RUNNING"

    def test_engine_failure_stays_retry_and_does_not_create_zero_score(self) -> None:
        run = self._run()
        with (
            patch("apps.experiments.assessment_workers._claim", return_value=run),
            patch(
                "apps.experiments.assessment_workers._admit", side_effect=RuntimeError("offline"),
            ),
            patch("apps.experiments.assessment_workers._finish") as finish,
        ):
            with self.assertRaises(RuntimeError):
                execute_assessment_job(pk=run.pk, formal=False)
            finish.assert_called_once_with(run, status="RETRY")

    def test_custom_run_does_not_read_hidden_tests(self) -> None:
        run = self._run()
        executor = SimpleNamespace(
            execute=lambda **kwargs: (None, [StdioResult("PASSED", "8\n")]), close=lambda: None,
        )
        client = SimpleNamespace(close=lambda: None)
        with (
            patch("apps.experiments.assessment_workers._claim", return_value=run),
            patch("apps.experiments.assessment_workers._admit", return_value=object()),
            patch("apps.experiments.assessment_workers._release"),
            patch("apps.experiments.assessment_workers._executor", return_value=(client, executor)),
            patch("apps.experiments.assessment_workers._read_source", return_value={"main.py": ""}),
            patch("apps.experiments.assessment_workers.read_private_tests") as hidden,
            patch("apps.experiments.assessment_workers._finish") as finish,
        ):
            execute_assessment_job(pk=run.pk, formal=False)
            hidden.assert_not_called()
            assert finish.call_args.kwargs["stdout"] == "8\n"

    def test_unsupported_runtime_never_falls_back_to_fake(self) -> None:
        from ..assessment_workers import _executor

        with self.assertRaises(RuntimeError):
            _executor(SimpleNamespace(runtime_adapter_driver="DOCKER_SWARM"), "test")
        with self.assertRaises(RuntimeError):
            _executor(SimpleNamespace(runtime_adapter_driver="FAKE"), "test")

    def test_object_sweep_only_removes_old_unreferenced_versions(self) -> None:
        from apps.core.models import ObjectAsset

        from ..assessment_workers import cleanup_assessment_objects

        now = timezone.now()
        old = now - timezone.timedelta(hours=2)
        ObjectAsset.objects.create(
            bucket="edu-platform", object_key="assessment/keep", object_version="kept-version",
            size_bytes=1, digest_sha256="a" * 64, owner_type="WORKSPACE_TASK",
            owner_ref=self.task.public_id, purpose="SOURCE_SNAPSHOT",
        )
        with patch("apps.experiments.assessment_workers.object_storage") as storage:
            storage.return_value.client.get_paginator.return_value.paginate.side_effect = [
                [{"Versions": [
                    {"Key": "assessment/keep", "VersionId": "kept-version", "LastModified": old},
                    {"Key": "assessment/orphan", "VersionId": "orphan-version",
                     "LastModified": old},
                    {"Key": "assessment/fresh", "VersionId": "fresh-version", "LastModified": now},
                ]}], [],
            ]
            assert cleanup_assessment_objects() == 1
            storage.return_value.delete_object.assert_called_once_with(
                bucket="edu-platform", object_key="assessment/orphan", version_id="orphan-version",
            )
