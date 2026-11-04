import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.core.errors import StateConflict
from apps.core.models import ObjectAsset
from apps.courses.models import Enrollment
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.experiments.services import allowed_actions, publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import Quota, ResourceProfile, RuntimeAdapter
from apps.provisioning.adapters import reset_fake_runtime
from apps.provisioning.models import ProvisioningInstance
from apps.provisioning.services import execute_provisioning_job, start_provisioning

from ..errors import (
    WorkspaceCaptureUnsupported,
    WorkspaceOperationDenied,
    WorkspaceSessionInvalid,
    WorkspaceSessionRevoked,
    WorkspaceStorageJobActive,
)
from ..models import (
    WorkspaceAutosaveLog,
    WorkspaceExecutionRun,
    WorkspaceSession,
    WorkspaceSnapshot,
    WorkspaceStorageJob,
)
from ..permissions import require_workspace_session
from ..serializers import execution_run_data
from ..services import (
    _execution_rules,
    _output_asset,
    _runtime_spec_for_execution,
    create_storage_job,
    enter_task,
    execute_execution_run,
    record_operation,
    renew_session,
    request_execution_run,
    revoke_session,
    task_has_active_test_rules,
    transition_storage_job,
)
from ..storage import (
    WorkspaceStorageFailure,
    _claim,
    _Content,
    _project_archive,
    _project_files,
    _runtime,
    _starter_main,
    create_finalize_job,
    execute_storage_job,
)
from ..workbench import workbench_data


class WorkspaceSessionServiceTests(TestCase):
    def setUp(self) -> None:
        text = patch("apps.workspaces.workbench.asset_text", return_value=None)
        text.start()
        self.addCleanup(text.stop)
        reset_fake_runtime()
        self.teacher, self.course, template_version, rubric_version = create_domain(
            suffix="workspaces"
        )
        RuntimeAdapter.objects.filter(pk=template_version.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        self.student_enrollment = create_enrollment(self.course, suffix="workspaces-student")
        self.publication = create_draft_publication(
            owner=self.teacher,
            course=self.course,
            template_version=template_version,
            rubric_version=rubric_version,
            suffix="workspaces",
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
            scope_key=f"USER:{self.student_enrollment.student.public_id}",
            user=self.student_enrollment.student,
            **values,
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.teacher,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=ActorContext(self.teacher.public_id, "TEACHING", "workspaces".ljust(32, "0")),
        )
        self.task = published.tasks.get(student=self.student_enrollment.student)
        _, job = start_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=ActorContext(self.task.student.public_id, "USER", "s" * 32),
        )
        execute_provisioning_job(job_id=job.public_id)
        self.task.refresh_from_db()
        self.context = ActorContext(self.task.student.public_id, "USER", "w" * 32)

    def tearDown(self) -> None:
        reset_fake_runtime()

    def test_frozen_tests_asset_enables_execution_without_public_rules(self) -> None:
        self.task.execution_spec = {"tests_asset": "private-tests-asset"}
        ExperimentTask.objects.filter(pk=self.task.pk).update(execution_spec=self.task.execution_spec)
        self.assertFalse(self.task.template_version.auto_check_rules.exists())
        self.assertTrue(task_has_active_test_rules(self.task))
        data = workbench_data(actor=self.task.student, task_id=self.task.public_id)
        self.assertTrue(data["tests"]["runnable"])
        self.assertEqual(data["tests"]["summary"], [])
        self.assertNotIn("private-tests-asset", json.dumps(data, default=str))

    def test_workbench_exposes_only_three_examples_and_authorized_reset(self) -> None:
        cases = [{"input": f"input-{index}", "expected": f"answer-{index}"} for index in range(5)]
        asset = ObjectAsset.objects.create(
            bucket="test", object_key="private-tests", digest_sha256="a" * 64,
            size_bytes=1, media_type="application/json", purpose="TESTS",
            owner_type="TEMPLATE_VERSION", owner_ref=self.task.template_version.public_id,
            scan_status="CLEAN",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            execution_spec={"tests_asset": asset.public_id}, status="IN_PROGRESS",
        )
        with patch(
            "apps.workspaces.workbench.asset_text", return_value=json.dumps({"cases": cases})
        ):
            data = workbench_data(actor=self.task.student, task_id=self.task.public_id)
        self.assertEqual(data["tests"]["count"], 5)
        self.assertEqual(len(data["tests"]["summary"]), 3)
        self.assertEqual(data["tests"]["summary"][2]["expected"], "answer-2")
        self.assertNotIn("answer-3", json.dumps(data, default=str))
        self.assertIn("RESET_WORKSPACE", data["task"]["allowed_operations"])
        type(self.task.template_version).objects.filter(pk=self.task.template_version_id).update(
            workspace_capabilities={"webide": False}
        )
        data = workbench_data(actor=self.task.student, task_id=self.task.public_id)
        self.assertNotIn("RESET_WORKSPACE", data["task"]["allowed_operations"])

    def test_execution_evidence_uses_the_permitted_storage_prefix_and_exposes_failures(
        self,
    ) -> None:
        run = WorkspaceExecutionRun(public_id="execution-evidence")
        with patch("apps.workspaces.services.object_storage") as storage:
            storage.return_value.put_stream.return_value = SimpleNamespace(version_id="v1")
            asset = _output_asset(run=run, kind="TEST_REPORT", content=b'{"status":"PASSED"}')
            key = storage.return_value.put_stream.call_args.kwargs["object_key"]
            self.assertTrue(key.startswith("workspaces/"), key)
            assert asset is not None
            asset.refresh_from_db()
            self.assertEqual(asset.scan_status, ObjectAsset.ScanStatus.CLEAN)
            storage.return_value.put_stream.side_effect = OSError("storage unavailable")
            with self.assertRaisesRegex(RuntimeError, "EXECUTION_OUTPUT_STORAGE_FAILED"):
                _output_asset(run=run, kind="STDOUT", content=b"HELLO")

    def test_execution_spec_uses_frozen_legacy_resource_profile(self) -> None:
        snapshot = dict(self.task.resource_profile_snapshot)
        snapshot.update({
            "cpu_millicores": 1200,
            "memory_mb": 2048,
            "disk_gb": 7,
            "network_mode": "DENY_ALL",
        })
        for field in (
            "cpu_request_millicores",
            "cpu_limit_millicores",
            "memory_request_mb",
            "memory_limit_mb",
        ):
            snapshot.pop(field, None)
        ExperimentTask.objects.filter(pk=self.task.pk).update(resource_profile_snapshot=snapshot)
        ResourceProfile.objects.filter(pk=self.task.resource_profile_id).update(
            public_id="profile-mutated-after",
            cpu_millicores=8000,
            memory_mb=16384,
            cpu_request_millicores=4000,
            cpu_limit_millicores=8000,
            memory_request_mb=8192,
            memory_limit_mb=16384,
            disk_gb=80,
            network_mode="ALLOWLIST",
        )
        task = ExperimentTask.objects.get(pk=self.task.pk)

        spec = _runtime_spec_for_execution(task, trace_id=self.context.trace_id)

        self.assertEqual(spec.resource_profile_id, snapshot["public_id"])
        self.assertEqual(spec.cpu_millicores, 1200)
        self.assertEqual(spec.memory_mb, 2048)
        self.assertEqual(spec.disk_gb, 7)
        self.assertEqual(spec.network_policy["mode"], "DENY_ALL")

    def test_scoped_cleanup_does_not_delete_resources_during_active_execution(self) -> None:
        _, session, _ = enter_task(
            task_id=self.task.public_id, actor=self.task.student,
            expected_version=self.task.row_version, context=self.context,
        )
        run = WorkspaceExecutionRun.objects.create(
            task=self.task, session=session, status="RUNNING",
            execution_rule_digest="a" * 64, idempotency_key="cleanup-active-run",
            trace_id=self.context.trace_id,
        )
        clock = iter((0, 61))
        command_module = "apps.workspaces.management.commands.cleanup_workspace_e2e"
        with (
            patch(command_module + ".time", SimpleNamespace(monotonic=lambda: next(clock))),
            patch(command_module + ".destroy_task_instance") as destroy,
            self.assertRaisesMessage(CommandError, "Execution is still active"),
        ):
            call_command("cleanup_workspace_e2e", "--task-id", self.task.public_id)
        destroy.assert_not_called()
        run.refresh_from_db()
        self.assertEqual(run.status, "RUNNING")

    def test_selected_language_reaches_the_frozen_execution_plan(self) -> None:
        from apps.labtemplates.services import _normalize_execution_spec
        from apps.labtemplates.toolchains import resolve_language_policy

        spec = _normalize_execution_spec({
            "schema_version": 2, "language": None, "entrypoint": None,
            "timeout_seconds": 5, "memory_mb": 256, "cpu_millicores": 500,
            "comparator": "token", "tests_asset": "A" * 26, "network_mode": "DENY_ALL",
        })
        policy = spec["toolchain"]
        spec["_runtime"] = {"material_assets": [], "workspace_capabilities": {"webide": True}}
        self.task.execution_spec = spec
        for language, entrypoint in (
            ("python", "main.py"), ("c", "main.c"), ("cpp", "main.cpp"),
            ("java", "Main.java"), ("go", "main.go"),
        ):
            with self.subTest(language=language):
                summary, actual, digest = _execution_rules(self.task, language=language)
                self.assertEqual(actual, ["python", entrypoint])
                self.assertEqual(summary["language"], language)
                self.assertEqual(summary["toolchain"]["toolchain_version"],
                                 policy["default_versions"][language])
                executable = {"python": "python", "java": "java"}.get(
                    language, "/tmp/.cache/program"
                )
                self.assertEqual(summary["execution_plan"]["run"][0], executable)
                self.assertEqual(len(digest), 64)
        self.assertEqual(self.task.execution_spec, spec)
        with self.assertRaises(WorkspaceOperationDenied):
            _execution_rules(self.task, language="rust")
        fixed_policy = resolve_language_policy(
            language="c", toolchain_version="12.2.0", language_standard=None,
        )
        self.task.execution_spec = {
            **spec, "language": "c", "entrypoint": "main.c", "toolchain": fixed_policy,
            "toolchain_version": "12.2.0", "language_standard": "c17",
        }
        summary, command, _ = _execution_rules(self.task, language="c")
        self.assertEqual(command, ["python", "main.c"])
        self.assertEqual(summary["execution_plan"]["compile"][0], "gcc")

        ExperimentTask.objects.filter(pk=self.task.pk).update(execution_spec=spec)
        WorkspaceSession.objects.filter(task=self.task).update(language="c")
        self.task.refresh_from_db()
        _, session, token = enter_task(
            task_id=self.task.public_id, actor=self.task.student,
            expected_version=self.task.row_version, context=self.context,
        )
        for mode in ("RUN_CHECK", "SELF_TEST"):
            run = request_execution_run(
                session=session, token=token, actor=self.task.student, arguments={},
                request_key=f"selected-{mode}", mode=mode, context=self.context,
            )
            self.assertEqual(run.execution_rule_summary["language"], "c")
            self.assertEqual(run.execution_rule_summary["command"], ["python", "main.c"])

    def test_ready_task_exposes_enter_and_issue_is_scoped(self) -> None:
        self.assertEqual(
            allowed_actions(self.task, actor=self.task.student),
            ["ENTER", "REQUEST_EXTENSION"],
        )
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(session.status, WorkspaceSession.Status.ACTIVE)
        self.assertNotEqual(session.token_hash, token)
        self.assertNotIn(token, session.token_hash)
        require_workspace_session(session=session, token=token, task_id=self.task.public_id)

    def test_runtime_provisioning_creates_a_reusable_workspace_session(self) -> None:
        session = WorkspaceSession.objects.get(task=self.task)

        self.assertEqual(session.status, WorkspaceSession.Status.ACTIVE)
        self.assertEqual(session.instance_id, self.task.provisioning_instance.pk)
        self.assertEqual(session.capabilities["terminal"], True)

    def test_enter_refreshes_stale_session_capabilities(self) -> None:
        """能力是派投影:发布后声明变化(教师补 terminal)时,重入应刷新旧会话快照。"""

        session = WorkspaceSession.objects.get(task=self.task)
        self.assertEqual(session.capabilities["terminal"], True)
        WorkspaceSession.objects.filter(pk=session.pk).update(
            capabilities={**session.capabilities, "terminal": False}
        )

        _task, refreshed, _token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )

        self.assertEqual(refreshed.public_id, session.public_id)
        self.assertTrue(refreshed.capabilities["terminal"])

    def test_storage_job_contract_rejects_fake_runtime_without_creating_a_row(self) -> None:
        _task, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        with self.assertRaises(WorkspaceCaptureUnsupported):
            create_storage_job(
                task_id=self.task.public_id,
                actor=self.task.student,
                token=token,
                expected_version=session.row_version,
                kind=WorkspaceStorageJob.Kind.CAPTURE,
                client_seq=1,
                base_version=0,
                snapshot_id=None,
                idempotency_key="storage-contract-fake",
                request_payload={"kind": "CAPTURE", "client_seq": 1, "base_version": 0},
                context=self.context,
            )
        self.assertFalse(WorkspaceStorageJob.objects.exists())

    def test_storage_job_claim_blocks_duplicates_and_recovers_stale_worker(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.task.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-docker",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL
        )
        self.task.refresh_from_db()
        with patch("apps.workspaces.storage.create_initialization_job"):
            _, session, token = enter_task(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_version=self.task.row_version,
                context=self.context,
            )
        _, job = create_storage_job(
            task_id=self.task.public_id,
            actor=self.task.student,
            token=token,
            expected_version=session.row_version,
            kind=WorkspaceStorageJob.Kind.CAPTURE,
            client_seq=1,
            base_version=0,
            snapshot_id=None,
            idempotency_key="capture-claim-test",
            request_payload={"kind": "CAPTURE", "client_seq": 1, "base_version": 0},
            context=self.context,
        )

        first, acquired = _claim(job.public_id, self.context.trace_id)
        duplicate, duplicate_acquired = _claim(job.public_id, self.context.trace_id)
        assert first is not None
        assert duplicate is not None
        self.assertTrue(acquired)
        self.assertFalse(duplicate_acquired)
        self.assertEqual(first.row_version, duplicate.row_version)

        WorkspaceStorageJob.objects.filter(pk=job.pk).update(
            started_at=timezone.now() - timedelta(minutes=16)
        )
        recovered, recovered_acquired = _claim(job.public_id, self.context.trace_id)
        competing, competing_acquired = _claim(job.public_id, self.context.trace_id)
        assert recovered is not None
        self.assertTrue(recovered_acquired)
        self.assertGreater(recovered.row_version, first.row_version)
        self.assertFalse(competing_acquired)

    def test_finalize_runtime_accepts_destroying_instance_and_skips_legacy_task(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.task.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-docker",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL
        )
        self.task.refresh_from_db()
        with patch("apps.workspaces.storage.create_initialization_job"):
            _, session, _token = enter_task(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_version=self.task.row_version,
                context=self.context,
            )

        self.assertIsNone(create_finalize_job(session=session, context=self.context))
        instance = ProvisioningInstance.objects.get(pk=session.instance_id)
        ProvisioningInstance.objects.filter(pk=instance.pk).update(
            status=ProvisioningInstance.Status.DESTROYING
        )
        job = WorkspaceStorageJob.objects.create(
            kind=WorkspaceStorageJob.Kind.FINALIZE,
            task=self.task,
            session=session,
            instance=instance,
            status=WorkspaceStorageJob.Status.RUNNING,
            idempotency_key="finalize-destroying-test",
            request_digest="a" * 64,
            trace_id=self.context.trace_id,
            started_at=timezone.now(),
        )
        adapter = object()
        with patch("apps.workspaces.storage.runtime_for_driver", return_value=adapter):
            self.assertEqual(_runtime(job, allow_destroying=True), (adapter, instance.external_id))
            with self.assertRaises(RuntimeError):
                _runtime(job)

    def test_storage_job_capture_is_queued_exclusive_and_terminal(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.task.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-docker",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL
        )
        self.task.refresh_from_db()
        with patch("apps.workspaces.storage.create_initialization_job"):
            _, session, token = enter_task(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_version=self.task.row_version,
                context=self.context,
            )

        changed_session, job = create_storage_job(
            task_id=self.task.public_id,
            actor=self.task.student,
            token=token,
            expected_version=session.row_version,
            kind=WorkspaceStorageJob.Kind.CAPTURE,
            client_seq=1,
            base_version=0,
            snapshot_id=None,
            idempotency_key="storage-capture-1",
            request_payload={"kind": "CAPTURE", "client_seq": 1, "base_version": 0},
            context=self.context,
        )
        self.assertEqual(job.status, WorkspaceStorageJob.Status.QUEUED)
        self.assertEqual(changed_session.row_version, session.row_version + 1)

        with self.assertRaises(WorkspaceStorageJobActive):
            create_storage_job(
                task_id=self.task.public_id,
                actor=self.task.student,
                token=token,
                expected_version=changed_session.row_version,
                kind=WorkspaceStorageJob.Kind.CAPTURE,
                client_seq=2,
                base_version=0,
                snapshot_id=None,
                idempotency_key="storage-capture-2",
                request_payload={
                    "kind": "CAPTURE",
                    "client_seq": 2,
                    "base_version": 0,
                },
                context=self.context,
            )

        running = transition_storage_job(
            job_id=job.public_id,
            expected_version=job.row_version,
            to_status=WorkspaceStorageJob.Status.RUNNING,
            context=self.context,
        )
        failed = transition_storage_job(
            job_id=job.public_id,
            expected_version=running.row_version,
            to_status=WorkspaceStorageJob.Status.FAILED,
            context=self.context,
        )
        self.assertIsNotNone(failed.completed_at)
        with self.assertRaises(StateConflict):
            transition_storage_job(
                job_id=job.public_id,
                expected_version=failed.row_version,
                to_status=WorkspaceStorageJob.Status.RUNNING,
                context=self.context,
            )

    def test_storage_job_api_creates_replays_and_returns_sanitized_job(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.task.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-docker",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL
        )
        self.task.refresh_from_db()
        with patch("apps.workspaces.storage.create_initialization_job"):
            _, session, token = enter_task(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_version=self.task.row_version,
                context=self.context,
            )
        client = Client(enforce_csrf_checks=True)
        client.get(
            "/api/v2/auth/csrf",
            HTTP_X_PORTAL="USER",
            HTTP_X_PROXY_CONTEXT="ingress-v1",
            REMOTE_ADDR="127.0.0.1",
        )
        csrf = str(client.cookies["csrftoken"].value)
        with (
            patch("apps.accounts.views.check_login_rate_limit", return_value="rate-key"),
            patch("apps.accounts.views.clear_login_rate_limit"),
        ):
            login = client.post(
                "/api/v2/auth/login",
                {
                    "identifier": self.task.student.email,
                    "password": "ValidPassword!234",
                },
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf,
                HTTP_X_PORTAL="USER",
                HTTP_X_PROXY_CONTEXT="ingress-v1",
                REMOTE_ADDR="127.0.0.1",
            )
        self.assertEqual(login.status_code, 200, login.content)
        headers = {
            "HTTP_X_PORTAL": "USER",
            "HTTP_X_PROXY_CONTEXT": "ingress-v1",
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_X_CSRFTOKEN": csrf,
            "HTTP_X_WORKSPACE_TOKEN": token,
            "HTTP_IF_MATCH": f'"{session.row_version}"',
            "HTTP_IDEMPOTENCY_KEY": "storage-api-capture-1",
        }
        path = f"/api/v2/tasks/{self.task.public_id}/workspace-storage-jobs"
        payload = {"kind": "CAPTURE", "client_seq": 1, "base_version": 0}

        response = client.post(path, payload, content_type="application/json", **headers)
        self.assertEqual(response.status_code, 202, response.content)
        job = response.json()["data"]
        self.assertEqual(job["status"], WorkspaceStorageJob.Status.QUEUED)
        self.assertEqual(response["Location"], f"/api/v2/workspace-storage-jobs/{job['public_id']}")
        self.assertEqual(response["ETag"], f'"{session.row_version + 1}"')

        replay = client.post(path, payload, content_type="application/json", **headers)
        self.assertEqual(replay.status_code, 202, replay.content)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(replay.json()["data"]["public_id"], job["public_id"])
        self.assertEqual(WorkspaceStorageJob.objects.count(), 1)

        detail = client.get(
            response["Location"],
            HTTP_X_PORTAL="USER",
            HTTP_X_PROXY_CONTEXT="ingress-v1",
            REMOTE_ADDR="127.0.0.1",
        )
        self.assertEqual(detail.status_code, 200, detail.content)
        serialized = detail.content.decode()
        for hidden_field in (
            "external_id",
            "container_id",
            "volume_name",
            "object_key",
            "upstream_token",
        ):
            self.assertNotIn(hidden_field, serialized)

    def test_capture_worker_commits_snapshot_and_session_version(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.task.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-docker",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL
        )
        self.task.refresh_from_db()
        with patch("apps.workspaces.storage.create_initialization_job"):
            _, session, token = enter_task(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_version=self.task.row_version,
                context=self.context,
            )
        _, job = create_storage_job(
            task_id=self.task.public_id,
            actor=self.task.student,
            token=token,
            expected_version=session.row_version,
            kind=WorkspaceStorageJob.Kind.CAPTURE,
            client_seq=1,
            base_version=0,
            snapshot_id=None,
            idempotency_key="capture-worker-1",
            request_payload={"kind": "CAPTURE", "client_seq": 1, "base_version": 0},
            context=self.context,
        )
        content_bytes = b"print('captured')\n"
        digest = hashlib.sha256(content_bytes).hexdigest()
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"workspaces/{self.task.public_id}/capture-worker/main.py",
            object_version="worker-version-1",
            digest_sha256=digest,
            size_bytes=len(content_bytes),
            media_type="text/x-python",
            owner_type="WORKSPACE_TASK",
            owner_ref=self.task.public_id,
            purpose="WORKSPACE_SNAPSHOT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        with (
            patch("apps.workspaces.storage._runtime", return_value=(object(), "managed-runtime")),
            patch(
                "apps.workspaces.storage._capture",
                return_value=_Content(content_bytes, digest, "text/x-python"),
            ),
            patch("apps.workspaces.storage._put_asset", return_value=asset),
        ):
            execute_storage_job(storage_job_id=job.public_id, trace_id=self.context.trace_id)

        job.refresh_from_db()
        session.refresh_from_db()
        snapshot = WorkspaceSnapshot.objects.get(pk=job.result_snapshot_id)
        self.assertEqual(job.status, WorkspaceStorageJob.Status.PASSED)
        self.assertEqual(snapshot.digest_sha256, digest)
        self.assertEqual(snapshot.client_seq, 1)
        self.assertEqual(session.current_version, 1)
        self.assertEqual(session.latest_snapshot_id, snapshot.pk)

        # Saving unchanged buffers before submission must keep the formal run's
        # snapshot identity, while consuming every confirmed client sequence.
        from apps.reports.errors import ReportExecutionConflict
        from apps.reports.services import _latest_execution_for_submission

        formal = WorkspaceExecutionRun.objects.create(
            task=self.task, session=session, snapshot=snapshot, status="PASSED",
            execution_rule_summary={"evaluation_mode": "FORMAL"},
            execution_rule_digest="f" * 64, idempotency_key="capture-formal",
            trace_id=self.context.trace_id,
        )
        for seq in (2, 3):
            job = WorkspaceStorageJob.objects.create(
                kind="CAPTURE", task=self.task, session=session, instance=session.instance,
                client_seq=seq, base_version=1, idempotency_key=f"capture-repeat-{seq}",
                request_digest="b" * 64, trace_id=self.context.trace_id,
            )
            with (
                patch("apps.workspaces.storage._runtime", return_value=(object(), "runtime")),
                patch("apps.workspaces.storage._capture", return_value=_Content(
                    content_bytes, digest, "text/x-python",
                )),
                patch("apps.workspaces.storage._put_asset") as upload,
            ):
                execute_storage_job(storage_job_id=job.public_id)
            job.refresh_from_db()
            session.refresh_from_db()
            self.assertEqual(job.status, "PASSED")
            self.assertEqual(job.result_snapshot_id, snapshot.pk)
            self.assertEqual(session.current_version, 1)
            upload.assert_not_called()
        self.assertEqual(WorkspaceSnapshot.objects.filter(task=self.task).count(), 1)
        self.assertEqual(WorkspaceAutosaveLog.objects.filter(task=self.task).count(), 3)
        # V2 restore/reset/re-entry of the same language and bytes retains formal
        # eligibility even when capture registered another clean object.
        ExperimentTask.objects.filter(pk=self.task.pk).update(execution_spec={"schema_version": 2})
        from apps.workspaces.storage import _commit_snapshot

        duplicate_asset = ObjectAsset.objects.create(
            bucket=asset.bucket, object_key=f"{asset.object_key}-same-bytes",
            digest_sha256=digest, size_bytes=len(content_bytes),
            media_type="text/x-python", owner_type=asset.owner_type,
            owner_ref=asset.owner_ref, purpose=asset.purpose, scan_status="CLEAN",
        )
        for seq, kind in enumerate(("RESTORE", "RESET", "INITIALIZE"), start=4):
            same = WorkspaceStorageJob.objects.create(
                kind=kind, task=self.task, session=session, instance=session.instance,
                source_snapshot=snapshot if kind == "RESTORE" else None,
                status="RUNNING", idempotency_key=f"unchanged-{kind}",
                request_digest="b" * 64, trace_id=self.context.trace_id,
            )
            actual = _commit_snapshot(
                job_id=same.public_id, claim_version=same.row_version, asset=duplicate_asset,
                content=_Content(content_bytes, digest, "text/x-python"),
                client_seq=seq, base_version=1,
            )
            self.assertEqual(actual.pk, snapshot.pk)
        session.refresh_from_db()
        ExperimentTask.objects.filter(pk=self.task.pk).update(execution_spec={})
        self.assertEqual(
            _latest_execution_for_submission(task=self.task, snapshot=session.latest_snapshot).pk,
            formal.pk,
        )

        # Re-entering a legacy task must restore the saved file and advance the
        # task-wide sequence, rather than overwrite it with the starter at zero.
        revoke_session(
            session=session, token=token, actor=self.task.student,
            expected_version=session.row_version, context=self.context,
        )
        self.task.refresh_from_db()
        with patch("apps.workspaces.storage.create_initialization_job"):
            _, reopened, _ = enter_task(
                task_id=self.task.public_id, actor=self.task.student,
                expected_version=self.task.row_version, context=self.context,
            )
        self.assertEqual(reopened.current_version, 1)
        initialize = WorkspaceStorageJob.objects.create(
            kind="INITIALIZE", task=self.task, session=reopened, instance=reopened.instance,
            idempotency_key="legacy-reenter", request_digest="b" * 64,
            trace_id=self.context.trace_id,
        )
        adapter = SimpleNamespace(restore_workspace=lambda **kwargs: None)
        with (
            patch("apps.workspaces.storage._runtime", return_value=(adapter, "runtime")),
            patch("apps.workspaces.storage._read_object", return_value=content_bytes),
            patch("apps.workspaces.storage._capture", return_value=_Content(content_bytes, digest)),
            patch("apps.workspaces.storage._put_asset", return_value=asset),
            patch("apps.workspaces.storage._scan"),
        ):
            execute_storage_job(storage_job_id=initialize.public_id)
        initialize.refresh_from_db()
        reopened.refresh_from_db()
        self.assertEqual(initialize.status, "PASSED")
        self.assertEqual(reopened.current_version, 2)
        self.assertEqual(reopened.latest_snapshot.digest_sha256, digest)
        self.assertEqual(reopened.latest_snapshot.client_seq, 7)

        changed_bytes = b"print('changed')\n"
        changed_digest = hashlib.sha256(changed_bytes).hexdigest()
        changed_asset = ObjectAsset.objects.create(
            bucket="test", object_key="changed.py", digest_sha256=changed_digest,
            size_bytes=len(changed_bytes), media_type="text/x-python",
            owner_type="WORKSPACE_TASK", owner_ref=self.task.public_id,
            purpose="WORKSPACE_SNAPSHOT", scan_status="CLEAN",
        )
        changed_job = WorkspaceStorageJob.objects.create(
            kind="CAPTURE", task=self.task, session=reopened, instance=reopened.instance,
            client_seq=8, base_version=2, idempotency_key="capture-changed",
            request_digest="c" * 64, trace_id=self.context.trace_id,
        )
        with (
            patch("apps.workspaces.storage._runtime", return_value=(object(), "runtime")),
            patch("apps.workspaces.storage._capture", return_value=_Content(
                changed_bytes, changed_digest, "text/x-python",
            )),
            patch("apps.workspaces.storage._put_asset", return_value=changed_asset),
        ):
            execute_storage_job(storage_job_id=changed_job.public_id)
        changed_job.refresh_from_db()
        reopened.refresh_from_db()
        self.assertEqual(changed_job.status, "PASSED")
        self.assertEqual(reopened.current_version, 3)
        self.assertEqual(reopened.latest_snapshot.digest_sha256, changed_digest)
        with self.assertRaises(ReportExecutionConflict):
            _latest_execution_for_submission(task=self.task, snapshot=reopened.latest_snapshot)

    def test_starter_archive_extracts_only_main_and_rejects_traversal(self) -> None:
        import io
        import zipfile

        self.assertEqual(
            _starter_main(b"print('single file')\n", "text/x-python"),
            b"print('single file')\n",
        )
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("src/", "")
            archive.writestr("main.py", "print('starter')\n")
            archive.writestr("README.txt", "ignored")
        self.assertEqual(
            _starter_main(archive_bytes.getvalue(), "application/zip"),
            b"print('starter')\n",
        )

        unsafe_bytes = io.BytesIO()
        with zipfile.ZipFile(unsafe_bytes, "w") as archive:
            archive.writestr("../main.py", "unsafe")
        from ..storage import WorkspaceStorageFailure

        with self.assertRaises(WorkspaceStorageFailure):
            _starter_main(unsafe_bytes.getvalue(), "application/zip")

    def test_language_projects_survive_switch_and_reset_uses_original_files(self) -> None:
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver="DOCKER_LOCAL",
            execution_spec={"schema_version": 2, "language": None, "toolchain": {
                "mode": "STUDENT_SELECT", "allowed_languages": ["python", "c"],
            }},
        )
        self.task.refresh_from_db()
        with patch("apps.workspaces.storage.create_initialization_job"):
            _, session, _token = enter_task(
                task_id=self.task.public_id, actor=self.task.student,
                expected_version=self.task.row_version, context=self.context,
            )
        state = {"content": _project_archive({})}
        objects = {}

        def put_asset(*, job, content):
            asset = ObjectAsset.objects.create(
                bucket="test", object_key=f"{job.public_id}/{content.digest}",
                digest_sha256=content.digest, size_bytes=content.size,
                media_type=content.media_type, owner_type="WORKSPACE_TASK",
                owner_ref=self.task.public_id, purpose="WORKSPACE_SNAPSHOT", scan_status="CLEAN",
            )
            objects[asset.pk] = content.value
            return asset

        def restore(**kwargs):
            state["content"] = kwargs["content"]

        def raise_failure(job_id, exc, trace_id, claim_version):
            raise exc

        adapter = SimpleNamespace(restore_workspace=restore)

        def run(kind, language=""):
            session.refresh_from_db()
            job = WorkspaceStorageJob.objects.create(
                kind=kind, target_language=language, task=self.task, session=session,
                instance=session.instance, idempotency_key=f"project-{len(objects)}-{kind}",
                request_digest="a" * 64, trace_id=self.context.trace_id,
            )
            execute_storage_job(storage_job_id=job.public_id)
            job.refresh_from_db()
            self.assertEqual(job.status, "PASSED", getattr(job.failure_record, "error_code", ""))
            session.refresh_from_db()

        with (
            patch("apps.workspaces.storage._runtime", return_value=(adapter, "runtime")),
            patch("apps.workspaces.storage._capture", side_effect=lambda *a, **k: _Content(
                state["content"], hashlib.sha256(state["content"]).hexdigest(), "application/gzip",
            )),
            patch("apps.workspaces.storage._put_asset", side_effect=put_asset),
            patch("apps.workspaces.storage._read_object", side_effect=lambda a: objects[a.pk]),
            patch("apps.workspaces.storage._scan"),
            patch("apps.workspaces.storage._record_failure", side_effect=raise_failure),
        ):
            run("INITIALIZE")
            initial_python = _project_files(state["content"])
            state["content"] = _project_archive({"main.py": b"print('python saved')"})
            run("SWITCH", "c")
            self.assertEqual(session.language, "c")
            state["content"] = _project_archive({"main.c": b"int main(void) { return 7; }"})
            run("SWITCH", "python")
            self.assertEqual(
                _project_files(state["content"]), {"main.py": b"print('python saved')"}
            )
            run("RESET")
            self.assertEqual(_project_files(state["content"]), initial_python)
            run("SWITCH", "c")
            self.assertIn(b"return 7", _project_files(state["content"])["main.c"])
        self.assertEqual(WorkspaceSnapshot.objects.filter(task=self.task, initial=True).count(), 2)
        for snapshot in WorkspaceSnapshot.objects.filter(task=self.task):
            self.assertEqual(snapshot.digest_sha256, snapshot.asset.digest_sha256)

    def test_project_snapshot_manifest_is_deterministic_and_rejects_unsafe_paths(self) -> None:
        import io
        import tarfile

        files = {"src/Main.java": b"class Main {}\n", "README.md": b"starter\n"}
        first = _project_archive(files)
        self.assertEqual(first, _project_archive(files))
        self.assertEqual(_project_files(first), files)

        unsafe = io.BytesIO()
        with tarfile.open(fileobj=unsafe, mode="w") as archive:
            info = tarfile.TarInfo("../secret.java")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(WorkspaceStorageFailure):
            _project_files(unsafe.getvalue())

    def test_initial_project_keeps_json_data_adds_entrypoint_and_excludes_hidden_source(self):
        from ..storage import _initial_project

        asset = ObjectAsset.objects.create(
            bucket="test", object_key="public-data", digest_sha256="a" * 64,
            size_bytes=7, media_type="application/json", original_name="data.json",
            owner_type="TEMPLATE_VERSION", owner_ref=self.task.template_version.public_id,
            purpose="PUBLIC_DATA", scan_status="CLEAN",
        )
        self.task.execution_spec = {
            "schema_version": 2,
            "_runtime": {"material_assets": [
                {"asset_id": asset.public_id, "role": "PUBLIC_DATA", "digest": asset.digest_sha256},
                {"asset_id": "hidden-id", "role": "HIDDEN_SOURCE", "digest": "b" * 64},
            ]},
        }
        with patch("apps.workspaces.storage._read_object", return_value=b'{"x":1}') as read:
            content = _initial_project(SimpleNamespace(task=self.task), "python")
        self.assertEqual(read.call_count, 1)
        files = _project_files(content.value)
        self.assertEqual(files["data.json"], b'{"x":1}')
        self.assertIn("main.py", files)
        self.assertEqual(len(files), 2)

        self.task.execution_spec["_runtime"]["material_assets"][0]["object_version"] = "changed"
        with self.assertRaises(WorkspaceStorageFailure):
            _initial_project(SimpleNamespace(task=self.task), "python")

    def test_non_report_submission_requires_a_clean_workspace_snapshot(self) -> None:
        TaskPublication.objects.filter(pk=self.publication.pk).update(report_required=False)
        _, session, _token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        blocked = workbench_data(actor=self.task.student, task_id=self.task.public_id)
        self.assertFalse(blocked["submission"]["can_submit"])
        self.assertEqual(
            blocked["submission"]["blocked_reason"]["code"],
            "WORKSPACE_SNAPSHOT_REQUIRED",
        )

        digest = "a" * 64
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"workspaces/{self.task.public_id}/{digest}",
            object_version="snapshot-version-1",
            digest_sha256=digest,
            size_bytes=8,
            media_type="text/plain",
            owner_type="WORKSPACE_TASK",
            owner_ref=self.task.public_id,
            purpose="WORKSPACE_SNAPSHOT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        WorkspaceSnapshot.objects.create(
            task=self.task,
            session=session,
            asset=asset,
            version_no=1,
            client_seq=1,
            digest_sha256=digest,
            size_bytes=8,
            media_type="text/plain",
            saved_at=timezone.now(),
            trace_id="snapshot".ljust(32, "0"),
        )

        ready = workbench_data(actor=self.task.student, task_id=self.task.public_id)
        self.assertTrue(ready["submission"]["can_submit"])
        self.assertIsNone(ready["submission"]["blocked_reason"])

    def test_report_submission_without_test_rules_does_not_require_a_run(self) -> None:
        """检查点型实验(模板无测试用例)不应被 TEST_NOT_FINISHED 卡住。"""
        from apps.reports.models import ReportDraft
        from apps.reports.services import update_report_draft

        RuntimeAdapter.objects.filter(pk=self.task.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-docker",
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            execution_spec={},
        )
        self.task.refresh_from_db()
        _, session, _token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        digest = hashlib.sha256(b"checkpoint-workspace").hexdigest()
        asset = ObjectAsset.objects.create(
            bucket="edu-platform",
            object_key=f"workspaces/{self.task.public_id}/{digest}",
            object_version="snapshot-version-1",
            digest_sha256=digest,
            size_bytes=8,
            media_type="text/plain",
            owner_type="WORKSPACE_TASK",
            owner_ref=self.task.public_id,
            purpose="WORKSPACE_SNAPSHOT",
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )
        WorkspaceSnapshot.objects.create(
            task=self.task,
            session=session,
            asset=asset,
            version_no=1,
            client_seq=1,
            digest_sha256=digest,
            size_bytes=8,
            media_type="text/plain",
            saved_at=timezone.now(),
            trace_id="snapshot".ljust(32, "0"),
        )
        draft = ReportDraft.objects.get(task=self.task)
        update_report_draft(
            task_id=self.task.public_id,
            actor=self.task.student,
            body_markdown="# checkpoint only",
            expected_version=draft.row_version,
            context=self.context,
        )
        self.assertFalse(task_has_active_test_rules(self.task))

        ready = workbench_data(actor=self.task.student, task_id=self.task.public_id)
        self.assertTrue(ready["submission"]["can_submit"])
        self.assertIsNone(ready["submission"]["blocked_reason"])

        # 声明了测试用例后,无运行结果重新被阻塞
        from apps.labtemplates.models import AutoCheckRule

        AutoCheckRule.objects.create(
            template_version=self.task.template_version,
            position=1,
            position_key="workspaces-rule",
            checker_type="PYTEST",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            timeout_seconds=30,
            resource_limit={},
            network_policy={"mode": "DENY_ALL"},
            display_policy={"show_score": True},
            failure_semantics={"on_failure": "FAIL_CHECK"},
            rule_digest="a" * 64,
        )
        blocked = workbench_data(actor=self.task.student, task_id=self.task.public_id)
        self.assertFalse(blocked["submission"]["can_submit"])
        self.assertEqual(
            blocked["submission"]["blocked_reason"]["code"],
            "TEST_NOT_FINISHED",
        )

    def test_renew_rotates_token_and_old_token_is_invalid(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        renewed, new_token = renew_session(
            session=session, token=token, actor=self.task.student, context=self.context
        )
        self.assertNotEqual(token, new_token)
        with self.assertRaises(WorkspaceSessionInvalid):
            require_workspace_session(session=renewed, token=token, task_id=self.task.public_id)
        require_workspace_session(session=renewed, token=new_token, task_id=self.task.public_id)

    def test_revoke_is_idempotent_at_row_level_and_invalidates_ticket(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        revoked = revoke_session(
            session=session,
            token=token,
            actor=self.task.student,
            expected_version=session.row_version,
            context=self.context,
        )
        self.assertEqual(revoked.status, WorkspaceSession.Status.REVOKED)
        with self.assertRaises(WorkspaceSessionRevoked):
            require_workspace_session(session=revoked, token=token, task_id=self.task.public_id)

    def test_ticket_is_invalidated_when_its_live_scope_is_revoked(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )

        for model, pk, changes in (
            (
                Enrollment,
                self.student_enrollment.pk,
                {"status": Enrollment.Status.DROPPED, "ended_at": timezone.now()},
            ),
            (
                User,
                self.task.student_id,
                {"account_status": User.AccountStatus.DISABLED, "is_active": False},
            ),
            (
                TaskPublication,
                self.publication.pk,
                {"status": TaskPublication.Status.WITHDRAWN},
            ),
        ):
            original = {name: getattr(model.objects.get(pk=pk), name) for name in changes}
            model.objects.filter(pk=pk).update(**changes)
            session = WorkspaceSession.objects.select_related(
                "student", "task__enrollment", "task__publication", "instance"
            ).get(pk=session.pk)
            with self.assertRaises(WorkspaceSessionRevoked):
                require_workspace_session(
                    session=session,
                    token=token,
                    task_id=self.task.public_id,
                )
            model.objects.filter(pk=pk).update(**original)

    @override_settings(WORKSPACE_INTERNAL_KEY="internal-secret")
    def test_gateway_records_only_whitelisted_operation_and_returns_unified_errors(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            f"/workspace/{session.public_id}/operations",
            data=json.dumps({"operation": "RUN_CHECK", "arguments": {"secret": "redact-me"}}),
            content_type="application/json",
            HTTP_X_PORTAL="USER",
            HTTP_X_WORKSPACE_INTERNAL_KEY="internal-secret",
            HTTP_X_WORKSPACE_TOKEN=token,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["event_type"], "operation.run_check")
        self.assertNotIn("redact-me", response.content.decode())

        denied = client.post(
            f"/workspace/{session.public_id}/operations",
            data=json.dumps({"operation": "SHELL"}),
            content_type="application/json",
            HTTP_X_PORTAL="USER",
            HTTP_X_WORKSPACE_INTERNAL_KEY="internal-secret",
            HTTP_X_WORKSPACE_TOKEN=token,
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "WORKSPACE_OPERATION_DENIED")

        internal_denied = client.post(
            f"/workspace/{session.public_id}/operations",
            data=json.dumps({"operation": "RUN_CHECK"}),
            content_type="application/json",
            HTTP_X_PORTAL="USER",
            HTTP_X_WORKSPACE_TOKEN=token,
        )
        self.assertEqual(internal_denied.status_code, 403)
        self.assertEqual(internal_denied.json()["error"]["code"], "WORKSPACE_INTERNAL_DENIED")

    @override_settings(WORKSPACE_INTERNAL_KEY="internal-secret")
    def test_run_check_creates_a_fake_execution_and_replays_by_request_key(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        WorkspaceSession.objects.filter(pk=session.pk).update(
            capabilities={**session.capabilities, "terminal": False, "snapshot": True}
        )
        client = Client(enforce_csrf_checks=True)
        headers = {
            "HTTP_X_PORTAL": "USER",
            "HTTP_X_WORKSPACE_INTERNAL_KEY": "internal-secret",
            "HTTP_X_WORKSPACE_TOKEN": token,
            "HTTP_IDEMPOTENCY_KEY": "execution-request-1",
        }
        response = client.post(
            f"/workspace/{session.public_id}/operations",
            data=json.dumps({"operation": "RUN_CHECK", "arguments": {"source": "test"}}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 201)
        operation_id = response.json()["data"]["public_id"]
        execution_id = response.json()["data"]["payload"]["execution_run_id"]
        run = WorkspaceExecutionRun.objects.get(public_id=execution_id)
        self.assertEqual(run.status, WorkspaceExecutionRun.Status.PASSED)
        self.assertEqual(run.task_id, self.task.pk)
        public_run = execution_run_data(run)
        for hidden_field in (
            "execution_rule_summary",
            "execution_rule_digest",
            "execution_spec",
            "execution_spec_digest",
            "stdout_asset_id",
            "stderr_asset_id",
            "test_report_asset_id",
        ):
            self.assertNotIn(hidden_field, public_run)
        replay = client.post(
            f"/workspace/{session.public_id}/operations",
            data=json.dumps({"operation": "RUN_CHECK", "arguments": {"source": "test"}}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json()["data"]["public_id"], operation_id)
        self.assertEqual(WorkspaceExecutionRun.objects.filter(task=self.task).count(), 1)

    @override_settings(WORKSPACE_INTERNAL_KEY="internal-secret")
    def test_self_test_is_separate_from_formal_run(self) -> None:
        _, session, token = enter_task(
            task_id=self.task.public_id, actor=self.task.student,
            expected_version=self.task.row_version, context=self.context,
        )
        WorkspaceSession.objects.filter(pk=session.pk).update(
            capabilities={**session.capabilities, "snapshot": True}
        )
        event = record_operation(
            session=session, token=token, actor=self.task.student,
            operation="SELF_TEST", arguments={"input": "debug"},
            context=self.context, request_key="self-test-1",
        )
        run = WorkspaceExecutionRun.objects.get(public_id=event.payload_masked["execution_run_id"])
        self.assertEqual(run.execution_rule_summary["evaluation_mode"], "SELF_TEST")
        self.assertNotEqual(run.idempotency_key, "")

    def test_non_fake_run_is_queued_and_worker_publishes_terminal_rejection(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.task.runtime_adapter_id).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-algorithm",
        )
        type(self.task).objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            runtime_adapter_config_ref="runtime/local-algorithm",
        )
        _, session, token = enter_task(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        run = request_execution_run(
            session=session,
            token=token,
            actor=self.task.student,
            arguments={},
            request_key="docker-local-execution-1",
            context=self.context,
        )
        self.assertEqual(run.status, WorkspaceExecutionRun.Status.QUEUED)
        completed = execute_execution_run(execution_run_id=run.public_id, trace_id="e" * 32)
        self.assertEqual(completed.status, WorkspaceExecutionRun.Status.REJECTED)
        self.assertEqual(completed.error_code, "EXECUTION_SNAPSHOT_REQUIRED")
