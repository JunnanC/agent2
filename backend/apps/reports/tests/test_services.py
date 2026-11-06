import hashlib
import json
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from apps.core.concurrency import compare_and_swap
from apps.core.downloads import (
    consume_download_grant,
    create_download_grant,
    get_download_target,
    revoke_download_grant,
)
from apps.core.errors import (
    DownloadGrantInvalid,
    ImmutableRecordError,
    ResourceNotFound,
    RowVersionConflict,
)
from apps.core.models import FileDownloadGrant, ObjectAsset, OutboxEvent
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import Quota, RuntimeAdapter
from apps.labtemplates.models import AutoCheckRule
from apps.provisioning.adapters import reset_fake_runtime
from apps.provisioning.services import execute_provisioning_job, start_provisioning
from apps.workspaces.models import WorkspaceExecutionRun, WorkspaceSnapshot
from apps.workspaces.permissions import require_workspace_session
from apps.workspaces.services import enter_task, issue_session

from ..errors import (
    ReportAttachmentNotReady,
    ReportExecutionConflict,
    ReportExecutionNotReady,
    ReportSnapshotConflict,
)
from ..models import (
    ReportAttachment,
    ReportDraft,
    ReportVersion,
    ReportVersionAttachment,
    SystemArtifact,
)
from ..serializers import report_version_data
from ..services import (
    complete_non_report_task,
    create_attachment_upload,
    report_draft_for_user,
    scan_report_attachment,
    submit_report,
    update_report_draft,
)


class ReportServiceTests(TestCase):
    password = "ValidPassword!234"

    def test_v2_submission_requires_current_complete_formal_pass(self) -> None:
        from apps.labtemplates.services import _normalize_execution_spec
        from apps.reports.services import _latest_execution_for_submission
        from apps.workspaces.services import _execution_rules

        snapshot = self._snapshot()
        tests = snapshot.asset
        spec = _normalize_execution_spec({
            "schema_version": 2, "language": "python", "entrypoint": "main.py",
            "timeout_seconds": 5, "memory_mb": 256, "cpu_millicores": 500,
            "comparator": "token", "tests_asset": tests.public_id, "network_mode": "DENY_ALL",
        })
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            execution_spec=spec, runtime_adapter_driver="DOCKER_LOCAL",
        )
        self.task.refresh_from_db()
        with self.assertRaises(ReportExecutionNotReady):
            _latest_execution_for_submission(task=self.task, snapshot=snapshot)
        run = self._execution(snapshot)
        WorkspaceExecutionRun.objects.filter(pk=run.pk).update(
            execution_rule_summary={"evaluation_mode": "SELF_TEST"},
        )
        with self.assertRaises(ReportExecutionNotReady):
            _latest_execution_for_submission(task=self.task, snapshot=snapshot)
        summary, _, digest = _execution_rules(self.task, language="python")
        WorkspaceExecutionRun.objects.filter(pk=run.pk).update(
            execution_rule_summary=summary, execution_rule_digest=digest,
        )
        # Use separate clean output asset; the workspace snapshot stays task-owned.
        output = ObjectAsset.objects.create(
            bucket="edu-platform", object_key="strict/report.json", object_version="1",
            digest_sha256="b" * 64, size_bytes=1, owner_type="WORKSPACE_EXECUTION",
            owner_ref=run.public_id, purpose="TEST_REPORT", scan_status="CLEAN",
        )
        WorkspaceExecutionRun.objects.filter(pk=run.pk).update(test_report_asset=output)
        payload = {"status": "PASSED", "cases": 2, "results": [{"status": "PASSED"}] * 2}

        def read(asset: ObjectAsset, **kwargs: object) -> str:
            return json.dumps({"cases": [{}, {}]} if asset.pk == tests.pk else payload)

        with patch("apps.workspaces.presentation.asset_text", side_effect=read):
            self.assertEqual(
                _latest_execution_for_submission(task=self.task, snapshot=snapshot).pk, run.pk,
            )
            for status in (
                "FAILED", "TIMEOUT", "RESOURCE_EXCEEDED", "REJECTED", "QUEUED", "RUNNING",
            ):
                with self.subTest(status=status):
                    WorkspaceExecutionRun.objects.filter(pk=run.pk).update(status=status)
                    with self.assertRaises(ReportExecutionNotReady):
                        _latest_execution_for_submission(task=self.task, snapshot=snapshot)
            WorkspaceExecutionRun.objects.filter(pk=run.pk).update(status="PASSED")
            payload["results"] = [{"status": "PASSED"}]
            payload["cases"] = 1
            with self.assertRaises(ReportExecutionNotReady):
                _latest_execution_for_submission(task=self.task, snapshot=snapshot)
            payload["results"] = [{"status": "PASSED"}] * 2
            payload["cases"] = 2
            for change in (
                {"absolute_tolerance": 0}, {"relative_tolerance": 0},
                {"tests_asset": "Z" * 26}, {"entrypoint": "other.py"},
                {"_runtime": {"material_assets": [{"object_version": "changed"}]}},
            ):
                with self.subTest(change=change):
                    self.task.execution_spec = {**spec, **change}
                    with self.assertRaises(ReportExecutionConflict):
                        _latest_execution_for_submission(task=self.task, snapshot=snapshot)
            self.task.execution_spec = spec
            snapshot.language = "c"
            with self.assertRaises(ReportExecutionConflict):
                _latest_execution_for_submission(task=self.task, snapshot=snapshot)
            snapshot.language = "python"
            for index in range(2):
                WorkspaceExecutionRun.objects.create(
                    task=self.task, session=self.session, snapshot=snapshot, status="PASSED",
                    execution_rule_summary={"evaluation_mode": "SELF_TEST"},
                    execution_rule_digest="c" * 64,
                    idempotency_key=f"strict-self-{index}", trace_id="s" * 32,
                )
            self.assertEqual(
                _latest_execution_for_submission(task=self.task, snapshot=snapshot).pk, run.pk,
            )
            ExperimentTask.objects.filter(pk=self.task.pk).update(runtime_adapter_driver="FAKE")
            self.task.refresh_from_db()
            with self.assertRaises(ReportExecutionNotReady):
                _latest_execution_for_submission(task=self.task, snapshot=snapshot)

            ExperimentTask.objects.filter(pk=self.task.pk).update(
                runtime_adapter_driver="DOCKER_LOCAL",
            )
            self.task.refresh_from_db()
            TaskPublication.objects.filter(pk=self.task.publication_id).update(report_required=False)
            payload["results"] = [{"status": "PASSED"}]
            payload["cases"] = 1
            with self.assertRaises(ReportExecutionNotReady):
                complete_non_report_task(
                    task_id=self.task.public_id, actor=self.task.student,
                    expected_task_version=self.task.row_version, context=self.context,
                )
            self.assertFalse(SystemArtifact.objects.filter(task=self.task).exists())
            payload["results"] = [{"status": "PASSED"}] * 2
            payload["cases"] = 2
            artifact, changed_task = complete_non_report_task(
                task_id=self.task.public_id, actor=self.task.student,
                expected_task_version=self.task.row_version, context=self.context,
            )
            self.assertEqual(changed_task.status, ExperimentTask.Status.UNDER_REVIEW)
            self.assertEqual(artifact.execution_run_id, run.pk)
            self.assertEqual(artifact.execution_evidence["rule_digest"], digest)
            self.assertEqual(artifact.execution_evidence["snapshot_digest"], snapshot.digest_sha256)
            with self.assertRaises(ImmutableRecordError):
                SystemArtifact.objects.filter(pk=artifact.pk).update(execution_evidence={})

    def test_worker_uses_frozen_numeric_zero_and_sanitizes_hidden_result(self) -> None:
        from apps.labtemplates.services import _normalize_execution_spec
        from apps.provisioning.ports import RuntimeExecutionResult
        from apps.workspaces.services import _execution_rules, execute_execution_run

        snapshot = self._snapshot()
        spec = _normalize_execution_spec({
            "schema_version": 2, "language": "python", "entrypoint": "main.py",
            "timeout_seconds": 5, "memory_mb": 256, "cpu_millicores": 500,
            "comparator": "numeric", "absolute_tolerance": 0, "relative_tolerance": 0,
            "tests_asset": snapshot.asset.public_id, "network_mode": "DENY_ALL",
        })
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            execution_spec=spec, runtime_adapter_driver="DOCKER_LOCAL",
        )
        self.task.refresh_from_db()
        summary, _, digest = _execution_rules(self.task, language="python")
        run = self._execution(snapshot, status="QUEUED")
        WorkspaceExecutionRun.objects.filter(pk=run.pk).update(
            execution_rule_summary=summary, execution_rule_digest=digest,
        )
        tests = {"comparator": "token", "absolute_tolerance": 99,
                 "relative_tolerance": 99, "cases": [
                     {"input": str(i), "expected": str(i)} for i in range(4)
                 ]}
        source_stream = BytesIO(b"print(input())")
        tests_stream = BytesIO(json.dumps(tests).encode())
        outputs = []
        with (
            patch("apps.workspaces.services.runtime_for_driver") as runtime,
            patch("apps.workspaces.services.object_storage") as storage,
            patch(
                "apps.workspaces.services._output_asset",
                side_effect=lambda **kw: outputs.append(kw),
            ),
        ):
            storage.return_value.open_object.side_effect = [
                SimpleNamespace(body=source_stream), SimpleNamespace(body=tests_stream),
            ]
            runtime.return_value.execute.return_value = RuntimeExecutionResult(
                test_report={"status": "PASSED", "cases": 4, "results": [
                    {"status": "PASSED", "actual": str(i), "stdout": "private-log"}
                    for i in range(4)
                ]},
            )
            completed = execute_execution_run(execution_run_id=run.public_id)
            self.assertEqual(completed.status, "PASSED", completed.error_code)
            delivered = json.loads(runtime.return_value.execute.call_args.kwargs["tests"])
        self.assertEqual(delivered["comparator"], "numeric")
        self.assertEqual(delivered["absolute_tolerance"], 0)
        self.assertEqual(delivered["relative_tolerance"], 0)
        self.assertTrue(source_stream.closed)
        self.assertTrue(tests_stream.closed)
        report = json.loads(next(
            item["content"] for item in outputs if item["kind"] == "TEST_REPORT"
        ))
        self.assertEqual(report["results"][3], {"hidden": True, "status": "PASSED"})

    def setUp(self) -> None:
        reset_fake_runtime()
        self.teacher, self.course, template_version, rubric_version = create_domain(
            suffix="reports"
        )
        RuntimeAdapter.objects.filter(pk=template_version.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        self.enrollment = create_enrollment(self.course, suffix="reports-student")
        self.publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=template_version,
            rubric_version=rubric_version,
            suffix="reports",
        )
        values = {
            "max_concurrent_instances": 10,
            "max_concurrent_starts": 10,
            "max_cpu_millicores": 20_000,
            "max_memory_mb": 40_000,
            "max_disk_gb": 200,
        }
        Quota.objects.create(scope_type=Quota.ScopeType.PLATFORM, scope_key="PLATFORM", **values)
        Quota.objects.create(
            scope_type=Quota.ScopeType.COURSE,
            scope_key=f"COURSE:{self.course.public_id}",
            course=self.course,
            **values,
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.USER,
            scope_key=f"USER:{self.enrollment.student.public_id}",
            user=self.enrollment.student,
            **values,
        )
        publication, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.teacher,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=ActorContext(self.teacher.public_id, "TEACHING", "reports".ljust(32, "0")),
        )
        self.task = publication.tasks.get(student=self.enrollment.student)
        _, job = start_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=ActorContext(self.task.student.public_id, "USER", "s" * 32),
        )
        execute_provisioning_job(job_id=job.public_id)
        self.task.refresh_from_db()
        self.context = ActorContext(self.task.student.public_id, "USER", "w" * 32)
        self.task, self.session, self.token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )

    def tearDown(self) -> None:
        reset_fake_runtime()

    def _snapshot(self, *, payload: bytes = b"snapshot_v1") -> WorkspaceSnapshot:
        digest = hashlib.sha256(payload).hexdigest()
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"workspaces/{self.task.public_id}/{digest}",
            object_version="object-v1",
            digest_sha256=digest,
            size_bytes=len(payload),
            media_type="text/plain",
            owner_type="WORKSPACE_TASK",
            owner_ref=self.task.public_id,
            purpose="WORKSPACE_SNAPSHOT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        return WorkspaceSnapshot.objects.create(
            task=self.task,
            session=self.session,
            asset=asset,
            version_no=WorkspaceSnapshot.objects.filter(task=self.task).count() + 1,
            client_seq=WorkspaceSnapshot.objects.filter(task=self.task).count() + 1,
            digest_sha256=digest,
            size_bytes=len(payload),
            media_type="text/plain",
            saved_at=timezone.now(),
            trace_id="x" * 32,
        )

    def _execution(
        self,
        snapshot: WorkspaceSnapshot,
        *,
        status: str = WorkspaceExecutionRun.Status.PASSED,
        asset_owner_ref: str | None = None,
    ) -> WorkspaceExecutionRun:
        run = WorkspaceExecutionRun.objects.create(
            task=self.task,
            session=self.session,
            snapshot=snapshot,
            status=status,
            execution_rule_summary={"language": "python", "entrypoint": "main.py"},
            execution_rule_digest="a" * 64,
            idempotency_key=f"report-test-{snapshot.public_id}-{status}",
            result_summary=f"{status} result",
            started_at=timezone.now(),
            finished_at=timezone.now(),
            duration_ms=4,
            trace_id="e" * 32,
        )
        if asset_owner_ref is not None:
            asset = ObjectAsset.objects.create(
                bucket="edu-platform",
                object_key=f"execution/{run.public_id}/stdout",
                object_version="execution-v1",
                digest_sha256="b" * 64,
                size_bytes=4,
                media_type="text/plain",
                original_name="stdout.txt",
                owner_type="WORKSPACE_EXECUTION",
                owner_ref=asset_owner_ref,
                purpose="EXECUTION_STDOUT",
                scan_status=ObjectAsset.ScanStatus.CLEAN,
            )
            run = compare_and_swap(
                WorkspaceExecutionRun,
                pk=run.pk,
                expected_version=run.row_version,
                changes={"stdout_asset": asset},
            )
        return run

    def _student_client(self) -> tuple[Client, str]:
        client = Client(enforce_csrf_checks=True)
        proxy_headers = {"HTTP_X_PROXY_CONTEXT": "ingress-v1", "REMOTE_ADDR": "127.0.0.1"}
        client.get("/api/v2/auth/csrf", HTTP_X_PORTAL="USER", **proxy_headers)
        csrf = str(client.cookies["csrftoken"].value)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            response = client.post(
                "/api/v2/auth/login",
                {"identifier": self.task.student.email, "password": self.password},
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="USER",
                **proxy_headers,
            )
        self.assertEqual(response.status_code, 200, response.content)
        return client, csrf

    def test_entering_report_task_initializes_draft_and_get_is_read_only(self) -> None:
        draft = ReportDraft.objects.get(task=self.task, student=self.task.student)
        row_version = draft.row_version
        read = report_draft_for_user(task_id=self.task.public_id, actor=self.task.student)
        self.assertEqual(read.pk, draft.pk)
        self.assertEqual(read.row_version, row_version)
        self.assertEqual(read.body_markdown, "")

    def test_direct_session_issue_initializes_missing_report_draft(self) -> None:
        with patch("apps.reports.services.initialize_report_draft") as initialize:
            issue_session(task=self.task, actor=self.task.student, context=self.context)
        initialize.assert_called_once()

    def test_workspace_session_remains_usable_after_report_draft_transition(self) -> None:
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Draft",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.session.refresh_from_db()
        self.session.task.refresh_from_db()
        self.assertEqual(self.session.task.status, ExperimentTask.Status.REPORT_DRAFT)
        self.assertEqual(
            require_workspace_session(
                session=self.session,
                token=self.token,
                task_id=self.task.public_id,
                capability="snapshot",
            ).pk,
            self.session.pk,
        )

    def test_draft_cas_rejects_stale_etag_without_overwriting(self) -> None:
        draft = ReportDraft.objects.get(task=self.task)
        updated = update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Draft 1",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.assertEqual(updated.row_version, draft.row_version + 1)
        with self.assertRaises(RowVersionConflict):
            update_report_draft(
                task_id=self.task.public_id,
                actor=self.task.student,
                body_markdown="# Lost update",
                expected_version=draft.row_version,
                context=self.context,
            )
        updated.refresh_from_db()
        self.assertEqual(updated.body_markdown, "# Draft 1")

    def test_draft_api_returns_412_for_stale_if_match(self) -> None:
        client, csrf = self._student_client()
        draft = ReportDraft.objects.get(task=self.task)
        url = f"/api/v2/tasks/{self.task.public_id}/report-draft"
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "USER",
            "HTTP_IDEMPOTENCY_KEY": "report-draft-write-1",
            "HTTP_IF_MATCH": f'"{draft.row_version}"',
            "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        saved = client.put(
            url,
            data='{"body_markdown":"# Saved"}',
            content_type="application/json",
            **headers,
        )
        self.assertEqual(saved.status_code, 200, saved.content)
        stale = client.put(
            url,
            data='{"body_markdown":"# Must not replace saved"}',
            content_type="application/json",
            **{**headers, "HTTP_IDEMPOTENCY_KEY": "report-draft-write-2"},
        )
        self.assertEqual(stale.status_code, 412, stale.content)
        self.assertEqual(ReportDraft.objects.get(task=self.task).body_markdown, "# Saved")

    def test_submit_api_replays_exactly_without_duplicate_report_version(self) -> None:
        self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Final report",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        client, csrf = self._student_client()
        url = f"/api/v2/tasks/{self.task.public_id}/submit-report"
        headers = {
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_PORTAL": "USER",
            "HTTP_IDEMPOTENCY_KEY": "report-submit-once",
            "HTTP_IF_MATCH": f'"{self.task.row_version}"',
            "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
        }
        first = client.post(url, data="{}", content_type="application/json", **headers)
        replay = client.post(url, data="{}", content_type="application/json", **headers)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(replay.status_code, 201, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(ReportVersion.objects.filter(task=self.task).count(), 1)

    def test_submit_freezes_version_and_transitions_task_atomically(self) -> None:
        snapshot = self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Final report",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        before = OutboxEvent.objects.count()
        version, changed_task = submit_report(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_task_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(version.workspace_snapshot_id, snapshot.pk)
        self.assertEqual(version.snapshot_digest, snapshot.digest_sha256)
        self.assertEqual(version.body_markdown, "# Final report")
        self.assertEqual(changed_task.status, ExperimentTask.Status.UNDER_REVIEW)
        self.assertEqual(ReportVersion.objects.filter(task=self.task).count(), 1)
        self.assertGreater(OutboxEvent.objects.count(), before)
        with self.assertRaises(ImmutableRecordError):
            version.save()
        with self.assertRaises(ImmutableRecordError):
            ReportVersion.objects.filter(pk=version.pk).update(body_markdown="mutated")

    def test_submit_blocks_unscanned_attachments_then_freezes_clean_digest(self) -> None:
        self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id, actor=self.task.student, body_markdown="Final report",
            expected_version=draft.row_version, context=self.context,
        )
        self.task.refresh_from_db()
        asset = ObjectAsset.objects.create(
            bucket="edu-platform", object_key=f"reports/{self.task.public_id}/attachment",
            object_version="pinned-v1", digest_sha256="a" * 64, size_bytes=4,
            media_type="text/plain", owner_type="REPORT_ATTACHMENT",
            owner_ref=self.task.public_id, purpose="REPORT_ATTACHMENT", scan_status="PENDING",
        )

        def submit() -> tuple[ReportVersion, ExperimentTask]:
            return submit_report(
                task_id=self.task.public_id, actor=self.task.student,
                expected_task_version=self.task.row_version, context=self.context,
            )

        with self.assertRaises(ReportAttachmentNotReady):
            submit()
        attachment = ReportAttachment.objects.create(
            draft=draft, asset=asset, uploaded_by=self.task.student, trace_id="a" * 32,
        )
        for state in ("PENDING", "INFECTED", "FAILED"):
            with self.subTest(scan_status=state):
                ObjectAsset.objects.filter(pk=asset.pk).update(scan_status=state)
                with self.assertRaises(ReportAttachmentNotReady):
                    submit()
                self.assertFalse(ReportVersion.objects.filter(task=self.task).exists())
        ObjectAsset.objects.filter(pk=asset.pk).update(scan_status="CLEAN", status="PURGED")
        with self.assertRaises(ReportAttachmentNotReady):
            submit()
        ObjectAsset.objects.filter(pk=asset.pk).update(status="ACTIVE")
        version, _ = submit()
        frozen = ReportVersionAttachment.objects.get(version=version, attachment=attachment)
        self.assertEqual(frozen.asset_digest, "a" * 64)
        with self.assertRaises(ImmutableRecordError):
            ReportVersionAttachment.objects.filter(pk=frozen.pk).update(asset_digest="b" * 64)

    def test_submit_copies_latest_execution_evidence_into_immutable_report(self) -> None:
        snapshot = self._snapshot()
        run = self._execution(snapshot, asset_owner_ref="placeholder")
        ObjectAsset.objects.filter(pk=run.stdout_asset_id).update(owner_ref=run.public_id)
        run.refresh_from_db()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# With execution evidence",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        version, _ = submit_report(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_task_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(version.execution_run_id, run.pk)
        self.assertEqual(version.execution_status, run.status)
        self.assertEqual(version.execution_result_summary, run.result_summary)
        self.assertEqual(version.execution_snapshot_id, snapshot.pk)
        self.assertEqual(version.execution_stdout_asset_id, run.stdout_asset_id)
        payload = report_version_data(version)
        evidence = cast(dict[str, object], payload["execution_evidence"])
        self.assertEqual(evidence["execution_run_id"], run.public_id)
        with self.assertRaises(ImmutableRecordError):
            ReportVersion.objects.filter(pk=version.pk).update(execution_result_summary="changed")

    def test_submit_rejects_missing_execution_for_non_fake_runtime(self) -> None:
        type(self.task).objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            runtime_adapter_config_ref="runtime/local-algorithm",
        )
        AutoCheckRule.objects.create(
            template_version=self.task.template_version,
            position=1,
            position_key="reports-rule",
            checker_type="PYTEST",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_seconds=30,
            resource_limit={},
            network_policy={"mode": "DENY_ALL"},
            display_policy={"show_score": True},
            failure_semantics={"on_failure": "FAIL_CHECK"},
            rule_digest="d" * 64,
        )
        self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Missing execution",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        with self.assertRaises(ReportExecutionNotReady):
            submit_report(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_task_version=self.task.row_version,
                context=self.context,
            )
        self.assertFalse(ReportVersion.objects.filter(task=self.task).exists())

    def test_submit_ignores_self_test_as_execution_evidence(self) -> None:
        type(self.task).objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            runtime_adapter_config_ref="runtime/local-algorithm",
        )
        AutoCheckRule.objects.create(
            template_version=self.task.template_version,
            position=1,
            position_key="reports-self-test-rule",
            checker_type="PYTEST",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_seconds=30,
            resource_limit={},
            network_policy={"mode": "DENY_ALL"},
            display_policy={"show_score": True},
            failure_semantics={"on_failure": "FAIL_CHECK"},
            rule_digest="s" * 64,
        )
        snapshot = self._snapshot()
        run = self._execution(snapshot)
        WorkspaceExecutionRun.objects.filter(pk=run.pk).update(
            execution_rule_summary={
                **run.execution_rule_summary,
                "evaluation_mode": "SELF_TEST",
            }
        )
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Self test only",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        with self.assertRaises(ReportExecutionNotReady):
            submit_report(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_task_version=self.task.row_version,
                context=self.context,
            )
        self.assertFalse(ReportVersion.objects.filter(task=self.task).exists())

    def test_submission_without_test_rules_skips_execution_requirement(self) -> None:
        """模板无测试用例时,提交沿用快照级兼容凭据,不要求执行运行。"""
        type(self.task).objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            runtime_adapter_config_ref="runtime/local-algorithm",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(execution_spec={})
        snapshot = self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# No rules attached",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        version, changed = submit_report(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_task_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(changed.status, ExperimentTask.Status.UNDER_REVIEW)
        self.assertEqual(version.execution_snapshot_id, snapshot.pk)
        self.assertEqual(version.execution_run.snapshot_id, snapshot.pk)
        self.assertEqual(version.execution_run.status, WorkspaceExecutionRun.Status.PASSED)
        self.assertFalse(
            WorkspaceExecutionRun.objects.filter(task=self.task)
            .exclude(pk=version.execution_run_id)
            .exists()
        )

    def test_submit_rejects_execution_asset_owned_by_another_run(self) -> None:
        snapshot = self._snapshot()
        run = self._execution(snapshot, asset_owner_ref="another-run")
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Cross task asset",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        with self.assertRaises(ReportExecutionConflict):
            submit_report(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_task_version=self.task.row_version,
                context=self.context,
            )
        self.assertEqual(run.status, WorkspaceExecutionRun.Status.PASSED)

    def test_submit_rejects_when_workspace_snapshot_changes_after_draft_save(self) -> None:
        first = self._snapshot(payload=b"saved workspace")
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Draft",
            expected_version=draft.row_version,
            context=self.context,
        )
        self._snapshot(payload=b"new workspace")
        self.task.refresh_from_db()
        with self.assertRaises(ReportSnapshotConflict):
            submit_report(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_task_version=self.task.row_version,
                context=self.context,
            )
        self.assertEqual(ReportVersion.objects.filter(task=self.task).count(), 0)
        latest = WorkspaceSnapshot.objects.filter(task=self.task).latest("version_no")
        self.assertNotEqual(first.digest_sha256, latest.digest_sha256)

    def test_submit_rejects_inactive_workspace_snapshot_asset(self) -> None:
        snapshot = self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Draft",
            expected_version=draft.row_version,
            context=self.context,
        )
        ObjectAsset.objects.filter(pk=snapshot.asset_id).update(status=ObjectAsset.Status.PURGED)
        self.task.refresh_from_db()
        with self.assertRaises(ReportSnapshotConflict):
            submit_report(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_task_version=self.task.row_version,
                context=self.context,
            )
        self.assertEqual(ReportVersion.objects.filter(task=self.task).count(), 0)

    def test_submit_rolls_back_report_facts_if_task_transition_fails(self) -> None:
        self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# Draft",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.task.refresh_from_db()
        before_events = OutboxEvent.objects.count()
        with (
            patch("apps.reports.services.transition_task", side_effect=RuntimeError("transition")),
            self.assertRaisesRegex(RuntimeError, "transition"),
        ):
            submit_report(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_task_version=self.task.row_version,
                context=self.context,
            )
        self.assertEqual(ReportVersion.objects.filter(task=self.task).count(), 0)
        self.assertEqual(ReportDraft.objects.get(task=self.task).status, ReportDraft.Status.DRAFT)
        self.assertEqual(OutboxEvent.objects.count(), before_events)

    def test_non_report_completion_records_only_server_selected_snapshot(self) -> None:
        TaskPublication.objects.filter(pk=self.publication.pk).update(report_required=False)
        self.task.refresh_from_db()
        snapshot = self._snapshot()
        artifact, changed_task = complete_non_report_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_task_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(artifact.asset_id, snapshot.asset_id)
        self.assertEqual(artifact.digest_sha256, snapshot.digest_sha256)
        self.assertEqual(changed_task.status, ExperimentTask.Status.UNDER_REVIEW)
        self.assertEqual(SystemArtifact.objects.filter(task=self.task).count(), 1)

    def test_download_grant_is_hashed_one_time_and_teacher_scope_requires_submission(self) -> None:
        snapshot = self._snapshot()
        draft = ReportDraft.objects.get(task=self.task)
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"reports/{self.task.public_id}/opaque-asset/opaque",
            object_version="object-v1",
            digest_sha256="a" * 64,
            size_bytes=4,
            media_type="text/plain",
            original_name="report.txt",
            owner_type="REPORT_ATTACHMENT",
            owner_ref=self.task.public_id,
            purpose="REPORT_ATTACHMENT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        attachment = ReportAttachment.objects.create(
            draft=draft,
            asset=asset,
            uploaded_by=self.task.student,
            trace_id="x" * 32,
        )
        with self.assertRaises(ResourceNotFound):
            create_download_grant(
                asset_id=asset.public_id,
                actor=self.teacher,
                portal="TEACHING",
                trace_id="t" * 32,
                token="teacher-before-submit",
            )
        student_grant, token = create_download_grant(
            asset_id=asset.public_id,
            actor=self.task.student,
            portal="USER",
            trace_id="u" * 32,
            token="user-download-once",
        )
        self.assertNotEqual(student_grant.token_hash, token)
        grant, target = get_download_target(token=token, actor=self.task.student, portal="USER")
        self.assertEqual(target.pk, asset.pk)
        consume_download_grant(
            grant_id=grant.pk,
            actor=self.task.student,
            portal="USER",
            trace_id="u" * 32,
        )
        with self.assertRaises(DownloadGrantInvalid):
            get_download_target(token=token, actor=self.task.student, portal="USER")
        self.assertIsNotNone(attachment.pk)
        self.assertIsNotNone(snapshot.pk)

    def test_download_grants_reject_revoked_and_expired_tokens(self) -> None:
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"reports/{self.task.public_id}/opaque-grant-key",
            object_version="grant-version",
            digest_sha256="c" * 64,
            size_bytes=4,
            media_type="text/plain",
            original_name="grant.txt",
            owner_type="REPORT_ATTACHMENT",
            owner_ref=self.task.public_id,
            purpose="REPORT_ATTACHMENT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        ReportAttachment.objects.create(
            draft=ReportDraft.objects.get(task=self.task),
            asset=asset,
            uploaded_by=self.task.student,
            trace_id="g" * 32,
        )
        revoked, revoked_token = create_download_grant(
            asset_id=asset.public_id,
            actor=self.task.student,
            portal="USER",
            trace_id="g" * 32,
            token="revoked-download-token",
        )
        revoke_download_grant(
            grant_id=revoked.public_id,
            actor=self.task.student,
            portal="USER",
            expected_version=revoked.row_version,
            trace_id="g" * 32,
        )
        with self.assertRaises(DownloadGrantInvalid):
            get_download_target(token=revoked_token, actor=self.task.student, portal="USER")

        expiring, expiring_token = create_download_grant(
            asset_id=asset.public_id,
            actor=self.task.student,
            portal="USER",
            trace_id="g" * 32,
            token="expired-download-token",
        )
        FileDownloadGrant.objects.filter(pk=expiring.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(DownloadGrantInvalid):
            get_download_target(token=expiring_token, actor=self.task.student, portal="USER")

    def test_file_download_route_uses_portal_from_authenticated_session(self) -> None:
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"reports/{self.task.public_id}/opaque-route-key",
            object_version="route-version",
            digest_sha256="b" * 64,
            size_bytes=7,
            media_type="text/plain",
            original_name="route.txt",
            owner_type="REPORT_ATTACHMENT",
            owner_ref=self.task.public_id,
            purpose="REPORT_ATTACHMENT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        ReportAttachment.objects.create(
            draft=ReportDraft.objects.get(task=self.task),
            asset=asset,
            uploaded_by=self.task.student,
            trace_id="r" * 32,
        )
        _grant, token = create_download_grant(
            asset_id=asset.public_id,
            actor=self.task.student,
            portal="USER",
            trace_id="r" * 32,
            token="root-route-download-token",
        )
        storage = SimpleNamespace(
            open_object=lambda **_kwargs: SimpleNamespace(
                body=BytesIO(b"content"),
                content_length=7,
                content_type="text/plain",
                version_id="route-version",
            )
        )
        client, _csrf = self._student_client()
        with patch("apps.core.files.object_storage", return_value=storage):
            response = client.get(f"/files/{token}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"content")
            replay = client.get(f"/files/{token}")
        self.assertEqual(replay.status_code, 404)

    def test_attachment_upload_uses_opaque_key_and_clean_scan_pins_version(self) -> None:
        content = b"report body"
        digest = hashlib.sha256(content).hexdigest()
        storage = SimpleNamespace(
            create_upload_post=lambda **_kwargs: {"url": "https://upload.invalid"},
            open_object=lambda **_kwargs: SimpleNamespace(
                body=BytesIO(content),
                content_length=len(content),
                content_type="text/plain",
                version_id="minio-version-1",
            ),
            delete_object=lambda **_kwargs: None,
        )
        with patch("apps.reports.services.object_storage", return_value=storage):
            asset, _upload = create_attachment_upload(
                task_id=self.task.public_id,
                actor=self.task.student,
                file_name="private-report.txt",
                media_type="text/plain",
                size_bytes=len(content),
                digest_sha256=digest,
                context=self.context,
            )
        self.assertNotIn("private-report.txt", asset.object_key)
        with (
            patch("apps.reports.services.object_storage", return_value=storage),
            patch(
                "apps.reports.services.ClamAVScanner",
                return_value=SimpleNamespace(
                    scan=lambda _chunks: SimpleNamespace(clean=True, signature="")
                ),
            ),
        ):
            scanned = scan_report_attachment(asset_id=asset.public_id, trace_id="s" * 32)
        self.assertEqual(scanned.scan_status, ObjectAsset.ScanStatus.CLEAN)
        self.assertEqual(scanned.object_version, "minio-version-1")
        self.assertTrue(ReportAttachment.objects.filter(asset=scanned).exists())

    def test_malware_scan_marks_infected_and_never_registers_attachment(self) -> None:
        content = b"infected report"
        digest = hashlib.sha256(content).hexdigest()
        storage = SimpleNamespace(
            create_upload_post=lambda **_kwargs: {"url": "https://upload.invalid"},
            open_object=lambda **_kwargs: SimpleNamespace(
                body=BytesIO(content),
                content_length=len(content),
                content_type="text/plain",
                version_id="infected-version",
            ),
            delete_object=lambda **_kwargs: None,
        )
        with patch("apps.reports.services.object_storage", return_value=storage):
            asset, _upload = create_attachment_upload(
                task_id=self.task.public_id,
                actor=self.task.student,
                file_name="evidence.txt",
                media_type="text/plain",
                size_bytes=len(content),
                digest_sha256=digest,
                context=self.context,
            )
        with (
            patch("apps.reports.services.object_storage", return_value=storage),
            patch(
                "apps.reports.services.ClamAVScanner",
                return_value=SimpleNamespace(
                    scan=lambda _chunks: SimpleNamespace(clean=False, signature="Eicar")
                ),
            ),
        ):
            scanned = scan_report_attachment(asset_id=asset.public_id, trace_id="i" * 32)
        self.assertEqual(scanned.scan_status, ObjectAsset.ScanStatus.INFECTED)
        self.assertEqual(scanned.object_version, "infected-version")
        self.assertFalse(ReportAttachment.objects.filter(asset=scanned).exists())
