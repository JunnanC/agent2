import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from apps.archives.models import ArchiveManifest
from apps.archives.services import execute_archive_job, request_task_archive, worker_context
from apps.archives.tests.storage import MemoryStorage
from apps.core.assets import register_asset
from apps.core.errors import ResourceNotFound
from apps.core.tests.storage import InMemoryObjectStorage
from apps.reports.models import ReportAttachment
from apps.reports.services import (
    authorize_report_asset_download,
    create_attachment_upload,
    request_attachment_scan,
    scan_report_attachment,
)
from apps.workspaces.code_snapshots import authorize_code_download, create_code_snapshot

from ..assessment import read_draft, report_draft, submit_choices
from ..models import CodeDraft, PublicationTask


class RetirementIntegrityTests(TestCase):
    def setUp(self) -> None:
        from .test_assessment import AssessmentTests

        AssessmentTests.setUp(self)
        self.program = PublicationTask.objects.create(
            publication_chapter=self.question.publication_chapter,
            source_task_id="D" * 26,
            title="Code",
            task_type="PROGRAMMING",
            sort_order=2,
            max_score=10,
            question_spec={
                "allowed_languages": ["python"],
                "starter_files": {"python": {"main.py": "print(1)"}},
            },
        )

    def test_optional_report_attachment_scans_without_old_workspace_evidence(self) -> None:
        from .helpers import context

        type(self.publication).objects.filter(pk=self.publication.pk).update(report_required=False)
        report_draft(actor=self.student, task_id=self.task.public_id)
        from apps.labtemplates.tests.test_assets import FakeStorage

        payload = b"report text"
        storage = FakeStorage(payload)
        with patch("apps.reports.services.object_storage", return_value=storage):
            asset, _ = create_attachment_upload(
                task_id=self.task.public_id,
                actor=self.student,
                file_name="report.txt",
                media_type="text/plain",
                size_bytes=len(payload),
                digest_sha256=hashlib.sha256(payload).hexdigest(),
                context=context(self.student),
            )
            with patch("apps.reports.tasks.scan_report_asset.apply_async"):
                asset = request_attachment_scan(
                    task_id=self.task.public_id,
                    asset_id=asset.public_id,
                    actor=self.student,
                    expected_version=asset.row_version,
                    context=context(self.student),
                )
            with patch("apps.reports.services.ClamAVScanner") as scanner:
                scanner.return_value.scan.return_value = SimpleNamespace(clean=True)
                scanned = scan_report_attachment(asset_id=asset.public_id, trace_id="retirement")
        assert scanned.scan_status == "CLEAN"
        assert ReportAttachment.objects.filter(asset=scanned).exists()
        assert (
            authorize_report_asset_download(scanned, self.student, "USER") == self.course.public_id
        )
        with self.assertRaises(ResourceNotFound):
            authorize_report_asset_download(scanned, self.owner, "TEACHING")

    def test_source_download_is_owned_and_hidden_test_assets_are_rejected(self) -> None:
        read_draft(
            actor=self.student,
            task_id=self.task.public_id,
            question_id=self.program.public_id,
            language="python",
        )
        draft = CodeDraft.objects.get(question=self.program)
        with (
            patch(
                "apps.workspaces.code_snapshots.object_storage",
                return_value=InMemoryObjectStorage(),
            ),
            patch("apps.workspaces.code_snapshots.ClamAVScanner") as scanner,
        ):
            scanner.return_value.scan.return_value = SimpleNamespace(clean=True)
            snapshot = create_code_snapshot(task=self.task, question=self.program, draft=draft)
        assert (
            authorize_code_download(snapshot.asset, self.student, "USER") == self.course.public_id
        )
        with self.assertRaises(ResourceNotFound):
            authorize_code_download(snapshot.asset, self.owner, "TEACHING")
        private = register_asset(
            bucket="test",
            object_key="private",
            object_version="v1",
            digest_sha256="a" * 64,
            size_bytes=1,
            owner_type="TEMPLATE_VERSION",
            owner_ref=self.publication.template_version.public_id,
            purpose="TESTS",
        )
        with self.assertRaises(ResourceNotFound):
            authorize_code_download(private, self.student, "USER")

    def test_verified_archive_is_idempotent_without_any_runtime_session(self) -> None:
        draft = read_draft(
            actor=self.student, task_id=self.task.public_id, question_id=self.question.public_id
        )
        submit_choices(
            actor=self.student,
            task_id=self.task.public_id,
            versions={self.question.public_id: draft["row_version"]},
            trace_id="test",
        )
        with (
            patch("apps.archives.tasks.run_archive_job.apply_async"),
            patch("apps.archives.services.object_storage", return_value=MemoryStorage()),
        ):
            job = request_task_archive(
                task_id=self.task.public_id,
                terminal_target="COMPLETED",
                trigger="CLOSED",
                context=worker_context(trace_id="retirement"),
            )
            result = execute_archive_job(job_id=job.public_id, raise_on_failure=True)
            assert result.status == "PASSED"
            execute_archive_job(job_id=job.public_id, raise_on_failure=True)
        self.task.refresh_from_db()
        assert self.task.status == "COMPLETED"
        assert ArchiveManifest.objects.filter(job=job).count() == 1
        assert not hasattr(self.task, "workspace_sessions")

    def test_failed_archive_can_retry_without_silently_finalizing_the_task(self) -> None:
        storage = MemoryStorage(corrupt_reads=True)
        with (
            patch("apps.archives.tasks.run_archive_job.apply_async"),
            patch("apps.archives.services.object_storage", return_value=storage),
        ):
            job = request_task_archive(
                task_id=self.task.public_id,
                terminal_target="COMPLETED",
                trigger="CLOSED",
                context=worker_context(trace_id="retirement"),
            )
            failed = execute_archive_job(job_id=job.public_id)
            assert failed.status == "FAILED"
            self.task.refresh_from_db()
            assert self.task.status != "COMPLETED"
            assert not ArchiveManifest.objects.filter(job=job).exists()
            storage.corrupt_reads = False
            assert (
                execute_archive_job(job_id=job.public_id, raise_on_failure=True).status == "PASSED"
            )
        self.task.refresh_from_db()
        assert self.task.status == "COMPLETED"
