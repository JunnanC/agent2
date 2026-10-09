from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask
from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import context as experiment_context
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import Quota, RuntimeAdapter

from ..adapters import (
    docker_local_protocol_stub,
    fake_runtime,
    reset_docker_local_protocol_stub,
    reset_fake_runtime,
)
from ..errors import ProvisioningStateConflict
from ..models import ProvisioningInstance, ProvisioningJob, ProvisioningStageEvent
from ..selectors import job_for_user
from ..services import (
    cancel_queued_provisioning,
    compensate_provisioning,
    enabled_runtime_inventory,
    execute_provisioning_job,
    retry_provisioning,
    runtime_inventory,
    runtime_inventory_snapshot,
    start_provisioning,
)


class ProvisioningServiceTests(TestCase):
    def setUp(self) -> None:
        reset_fake_runtime()
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="p07"
        )
        self.adapter = self.template_version.runtime_adapter
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        self.adapter.refresh_from_db()
        self.enrollment = create_enrollment(self.course, suffix="p07-student")
        self.publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="p07",
        )
        self.platform_quota = Quota.objects.create(
            scope_type=Quota.ScopeType.PLATFORM,
            scope_key="PLATFORM",
            max_concurrent_instances=10,
            max_concurrent_starts=10,
            max_cpu_millicores=20000,
            max_memory_mb=40000,
            max_disk_gb=200,
            change_reason="P07 test quota",
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.COURSE,
            scope_key=f"COURSE:{self.course.public_id}",
            course=self.course,
            max_concurrent_instances=10,
            max_concurrent_starts=10,
            max_cpu_millicores=20000,
            max_memory_mb=40000,
            max_disk_gb=200,
            change_reason="P07 test quota",
        )
        Quota.objects.create(
            scope_type=Quota.ScopeType.USER,
            scope_key=f"USER:{self.enrollment.student.public_id}",
            user=self.enrollment.student,
            max_concurrent_instances=10,
            max_concurrent_starts=10,
            max_cpu_millicores=20000,
            max_memory_mb=40000,
            max_disk_gb=200,
            change_reason="P07 test quota",
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=experiment_context(self.owner),
        )
        self.task = published.tasks.get(student=self.enrollment.student)
        self.context = ActorContext(
            self.task.student.public_id,
            "USER",
            "p07" * 8,
        )

    def tearDown(self) -> None:
        reset_fake_runtime()
        reset_docker_local_protocol_stub()

    def _start(self) -> ProvisioningJob:
        _, job = start_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        return job

    def _new_task(self, suffix: str) -> tuple[ExperimentTask, User]:
        enrollment = create_enrollment(self.course, suffix=suffix)
        publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix=suffix,
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.owner,
            expected_version=publication.row_version,
            selected_ids=[],
            context=experiment_context(self.owner),
        )
        return published.tasks.get(student=enrollment.student), enrollment.student

    def test_success_writes_append_only_start_and_pass_events_for_all_stages(self) -> None:
        job = self._start()
        finished = execute_provisioning_job(job_id=job.public_id)

        self.assertEqual(finished.status, ProvisioningJob.Status.PASSED)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, self.task.Status.READY)
        events = list(
            ProvisioningStageEvent.objects.filter(job=finished).order_by("created_at", "pk")
        )
        self.assertEqual(len(events), len(ProvisioningJob.Stage.values) * 2)
        for stage in ProvisioningJob.Stage.values:
            stage_events = [event for event in events if event.stage == stage]
            self.assertEqual([event.status for event in stage_events], ["STARTED", "PASSED"])
        instance = ProvisioningInstance.objects.get(task=self.task)
        self.assertEqual(instance.status, ProvisioningInstance.Status.READY)
        self.assertTrue(instance.external_id)
        self.assertEqual(instance.endpoint, "http://tasks.fake-runtime:8080")
        self.assertTrue(instance.external_metadata["managed"])
        self.assertEqual(instance.external_metadata["service_name"], "fake-runtime")
        self.assertEqual(instance.external_metadata["workspace_port"], 8080)

    def test_each_fake_failure_records_failed_stage_and_retryable_failure(self) -> None:
        for index, stage in enumerate(ProvisioningJob.Stage.values):
            with self.subTest(stage=stage):
                reset_fake_runtime()
                task, student = self._new_task(f"p07-failure-{index}")
                fake_runtime().failures[stage] = f"FAKE_{stage}_FAILED"
                _, job = start_provisioning(
                    task_id=task.public_id,
                    actor=student,
                    expected_version=task.row_version,
                    context=ActorContext(student.public_id, "USER", f"f{index}" * 32),
                )
                finished = execute_provisioning_job(job_id=job.public_id)
                self.assertEqual(finished.status, ProvisioningJob.Status.FAILED)
                self.assertTrue(finished.retryable)
                failed_event = ProvisioningStageEvent.objects.get(
                    job=finished,
                    stage=stage,
                    status=ProvisioningStageEvent.Status.FAILED,
                )
                self.assertEqual(failed_event.error_code, f"FAKE_{stage}_FAILED")

    def test_partial_create_failure_requires_compensation_before_retry(self) -> None:
        fake_runtime().failures[ProvisioningJob.Stage.CREATE] = "FAKE_CREATE_FAILED"
        fake_runtime().partial_success.add(ProvisioningJob.Stage.CREATE)
        job = self._start()
        failed = execute_provisioning_job(job_id=job.public_id)
        self.assertEqual(failed.status, ProvisioningJob.Status.FAILED)
        failed.refresh_from_db()
        instance = ProvisioningInstance.objects.get(task=self.task)
        self.assertTrue(instance.external_id)
        self.assertIsNotNone(failed.compensation_task_id)

        self.task.refresh_from_db()
        with self.assertRaises(ProvisioningStateConflict):
            retry_provisioning(
                task_id=self.task.public_id,
                actor=self.task.student,
                expected_version=self.task.row_version,
                context=self.context,
            )

        compensation = failed.compensation_task
        compensate_provisioning(compensation)
        compensation.refresh_from_db()
        instance.refresh_from_db()
        self.assertEqual(instance.status, ProvisioningInstance.Status.DESTROYED)
        self.assertIsNone(instance.external_id)

        self.task.refresh_from_db()
        _, retry_job = retry_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(retry_job.attempt_no, 2)
        self.assertEqual(
            job_for_user(actor=self.task.student, task_id=self.task.public_id).attempt_no,
            2,
        )

    def test_queued_cancel_releases_reservation_and_does_not_call_runtime(self) -> None:
        job = self._start()
        self.task.refresh_from_db()
        _, cancelled = cancel_queued_provisioning(
            task_id=self.task.public_id,
            actor=self.task.student,
            expected_version=self.task.row_version,
            context=self.context,
        )
        self.assertEqual(cancelled.status, ProvisioningJob.Status.CANCELLED)
        self.assertEqual(cancelled.reservation.status, "RELEASED")
        self.assertEqual(fake_runtime().calls, [])
        self.assertFalse(ProvisioningStageEvent.objects.filter(job=job).exists())
        self.assertEqual(
            ProvisioningInstance.objects.get(task=self.task).status,
            ProvisioningInstance.Status.DESTROYED,
        )

    def test_worker_replay_is_idempotent(self) -> None:
        job = self._start()
        first = execute_provisioning_job(job_id=job.public_id)
        calls = list(fake_runtime().calls)
        second = execute_provisioning_job(job_id=job.public_id)
        self.assertEqual(first.public_id, second.public_id)
        self.assertEqual(second.status, ProvisioningJob.Status.PASSED)
        self.assertEqual(calls, fake_runtime().calls)

    def test_docker_local_protocol_stub_uses_the_same_six_stage_service_contract(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-algorithm",
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            runtime_adapter_driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            runtime_adapter_config_ref="runtime/local-algorithm",
        )
        self.task.refresh_from_db()

        job = self._start()
        finished = execute_provisioning_job(job_id=job.public_id)

        self.assertEqual(finished.status, ProvisioningJob.Status.PASSED)
        instance = ProvisioningInstance.objects.get(task=self.task)
        self.assertEqual(instance.status, ProvisioningInstance.Status.READY)
        self.assertEqual(instance.endpoint, "http://tasks.docker-local-stub:8080")
        self.assertEqual(instance.external_metadata["driver"], "DOCKER_LOCAL")
        self.assertTrue(instance.external_metadata["protocol_stub"])
        self.assertEqual(
            ProvisioningStageEvent.objects.filter(job=finished).count(),
            len(ProvisioningJob.Stage.values) * 2,
        )
        self.assertEqual(fake_runtime().calls, [])
        self.assertEqual(
            [stage for stage, _ in docker_local_protocol_stub().calls],
            [
                "QUOTA_CHECK",
                "IMAGE_PREPARE",
                "CREATE",
                "NETWORK_ATTACH",
                "BOOT_PROBE",
                "WORKSPACE_READY",
            ],
        )

    def test_runtime_inventory_snapshot_reports_managed_and_orphan_resources(self) -> None:
        from ..services import _runtime_spec

        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            config_ref="runtime/local-algorithm",
        )
        stub = docker_local_protocol_stub("runtime/local-algorithm")
        created = stub.create(_runtime_spec(self.task, trace_id="inventory-trace"), "inventory-1")

        snapshot = runtime_inventory_snapshot(trace_id="inventory-trace")

        self.assertEqual(snapshot["status"], "HEALTHY")
        self.assertEqual(snapshot["inventory"], {"runtime": 1, "transient": 1})
        self.assertEqual(snapshot["orphans"], {"runtime": 1, "judge": 0, "volume": 1})
        self.assertEqual(created.external_id, stub.inventory()[0].external_id)

    def test_runtime_inventory_snapshot_identifies_engine_outage_by_trace(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            driver=RuntimeAdapter.Driver.DOCKER_SWARM,
        )
        adapter = Mock()
        adapter.health.return_value = {
            "status": "UNAVAILABLE",
            "error_code": "RUNTIME_UNAVAILABLE",
        }

        with (
            self.assertLogs("runtime.provisioning", level="ERROR") as logs,
            patch("apps.provisioning.services.runtime_for_driver", return_value=adapter),
        ):
            snapshot = runtime_inventory_snapshot(trace_id="engine-outage-trace")

        self.assertEqual(snapshot["status"], "UNAVAILABLE")
        self.assertEqual(snapshot["drivers"][0]["status"], "UNAVAILABLE")
        self.assertEqual(logs.records[0].trace_id, "engine-outage-trace")
        self.assertEqual(logs.records[0].resource_ref, self.adapter.public_id)
        adapter.inventory.assert_not_called()

    def test_enabled_runtime_inventory_can_preserve_unavailable_adapter_marker(self) -> None:
        with patch(
            "apps.provisioning.services.runtime_inventory",
            side_effect=RuntimeError("docker socket is unavailable"),
        ):
            items = enabled_runtime_inventory(include_unavailable=True)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, "")
        self.assertEqual(items[0].status, "UNAVAILABLE")
        self.assertEqual(items[0].metadata["adapter_id"], self.adapter.public_id)
        self.assertTrue(items[0].metadata["inventory_unavailable"])

    @override_settings(RUNTIME_MODE="fake", RUNTIME_ADAPTER_CODE="runtime/fake")
    def test_runtime_inventory_uses_the_explicit_runtime_mode_resolver(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            code="runtime/fake",
            driver=RuntimeAdapter.Driver.FAKE,
        )

        with patch("apps.provisioning.services.runtime_adapter_for") as resolver:
            resolver.return_value = fake_runtime()
            runtime_inventory(driver=RuntimeAdapter.Driver.FAKE, config_ref="runtime/fake")

        resolver.assert_called_once_with("runtime/fake")

    @override_settings(RUNTIME_MODE="fake", RUNTIME_ADAPTER_CODE="runtime/fake")
    def test_provisioning_uses_the_explicit_runtime_mode_resolver(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(code="runtime/fake")
        self.task.refresh_from_db()
        job = self._start()

        with patch(
            "apps.provisioning.services.runtime_adapter_for", return_value=fake_runtime()
        ) as resolver:
            finished = execute_provisioning_job(job_id=job.public_id)

        self.assertEqual(finished.status, ProvisioningJob.Status.PASSED)
        resolver.assert_called_once_with("runtime/fake")
