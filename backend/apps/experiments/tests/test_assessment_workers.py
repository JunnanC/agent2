import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.core.concurrency import compare_and_swap
from apps.provisioning.stdio import StdioResult

from ..assessment_workers import _claim, _finish, execute_assessment_job
from ..models import (
    AssessmentRun,
    AssessmentSection,
    PublicationTask,
    QuestionGrade,
    QuestionSubmission,
    SectionSubmission,
)


class AssessmentWorkerTests(TestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)

    def _run(self) -> AssessmentRun:
        # Only database references are needed when the source reader is explicitly injected.
        from apps.core.models import ObjectAsset
        from apps.workspaces.models import WorkspaceSnapshot

        question = PublicationTask.objects.create(
            publication_chapter=self.question.publication_chapter, source_task_id="D" * 26,
            title="Code", task_type="PROGRAMMING", sort_order=2, max_score=10,
            question_spec={"limits": {"python": {"timeout_seconds": 3, "memory_mb": 256}}},
        )
        asset = ObjectAsset.objects.create(
            bucket="test", object_key="source", digest_sha256="a" * 64, size_bytes=1,
            owner_type="WORKSPACE_TASK", owner_ref=self.task.public_id, purpose="SOURCE_SNAPSHOT",
            scan_status="CLEAN",
        )
        snapshot = WorkspaceSnapshot.objects.create(
            task=self.task, question=question, asset=asset, version_no=1, client_seq=1,
            digest_sha256="a" * 64, size_bytes=1, language="python", saved_at=timezone.now(),
            trace_id="a" * 32,
        )
        return AssessmentRun.objects.create(
            task=self.task, question=question, snapshot=snapshot,
        )

    def test_crashed_worker_lease_recovers_and_completed_delivery_is_ignored(self) -> None:
        run = self._run()
        first = _claim(AssessmentRun, run.pk)
        compare_and_swap(
            AssessmentRun, pk=run.pk, expected_version=first.row_version,
            changes={"lease_until": timezone.now() - timezone.timedelta(seconds=1)},
        )
        replacement = _claim(AssessmentRun, run.pk)
        assert replacement.lease_token != first.lease_token
        assert replacement.attempt_count == 2
        _finish(first, status="COMPLETED", stdout="stale")
        _finish(replacement, status="COMPLETED", stdout="accepted")
        assert _claim(AssessmentRun, run.pk) is None
        run.refresh_from_db()
        assert run.stdout == "accepted"

    def test_formal_source_outage_keeps_score_pending_and_releases_resources(self) -> None:
        from unittest.mock import Mock

        run = self._run()
        section = AssessmentSection.objects.create(task=self.task, kind="PROGRAMMING")
        submission = SectionSubmission.objects.create(
            section=section, version_no=1, publication_digest="a" * 64,
            submitted_at=timezone.now(), trace_id="test",
        )
        answer = QuestionSubmission.objects.create(
            submission=submission, question=run.question,
            language="python", code_snapshot=run.snapshot,
        )
        grade = QuestionGrade.objects.create(answer=answer)
        client, executor, reservation = Mock(), Mock(), Mock()
        with (
            patch("apps.experiments.assessment_workers._admit", return_value=reservation),
            patch("apps.experiments.assessment_workers._executor", return_value=(client, executor)),
            patch(
                "apps.experiments.assessment_workers._read_source", side_effect=OSError("offline"),
            ),
            patch("apps.experiments.assessment_workers._release") as release,
            self.assertRaises(OSError),
        ):
            execute_assessment_job(pk=grade.pk, formal=True)
        grade.refresh_from_db()
        assert grade.status == "RETRY"
        assert grade.score is None
        assert grade.lease_token is None
        assert grade.private_result == {}
        executor.close.assert_called_once()
        client.close.assert_called_once()
        assert release.call_args.args[0] == reservation

    def test_broker_failure_keeps_pending_job_for_next_dispatch(self) -> None:
        from ..assessment_workers import dispatch_assessments

        run = self._run()
        with patch("apps.experiments.assessment_workers.run_assessment_job.apply_async") as enqueue:
            enqueue.side_effect = ConnectionError("broker unavailable")
            with self.assertRaises(ConnectionError):
                dispatch_assessments()
            run.refresh_from_db()
            assert run.status == "PENDING"
            enqueue.side_effect = None
            assert dispatch_assessments() == 1
            assert enqueue.call_args.kwargs["kwargs"] == {"pk": run.pk, "formal": False}

    def test_old_submission_finishing_cannot_change_current_grade_or_task(self) -> None:
        run = self._run()
        section = AssessmentSection.objects.create(task=self.task, kind="PROGRAMMING")
        grades = []
        for version in (1, 2):
            submission = SectionSubmission.objects.create(
                section=section, version_no=version, publication_digest="a" * 64,
                submitted_at=timezone.now(), trace_id="test",
            )
            answer = QuestionSubmission.objects.create(
                submission=submission, question=run.question,
                language="python", code_snapshot=run.snapshot,
            )
            grades.append(QuestionGrade.objects.create(answer=answer))
        compare_and_swap(
            AssessmentSection, pk=section.pk, expected_version=section.row_version,
            changes={"current_submission": submission, "status": "SUBMITTED"},
        )
        old = _claim(QuestionGrade, grades[0].pk)
        task_version = self.task.row_version
        _finish(old, status="COMPLETED", score=10)
        self.task.refresh_from_db()
        grades[1].refresh_from_db()
        section.refresh_from_db()
        assert self.task.row_version == task_version
        assert section.current_submission_id == submission.pk
        assert grades[1].score is None
        assert grades[1].status == "PENDING"

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
                ]}], [], [],
            ]
            assert cleanup_assessment_objects() == 1
            storage.return_value.delete_object.assert_called_once_with(
                bucket="edu-platform", object_key="assessment/orphan", version_id="orphan-version",
            )
