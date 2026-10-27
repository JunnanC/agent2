import json
from io import StringIO
from typing import Any
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.experiments.services import publish_publication
from apps.experiments.tests.helpers import (
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.governance.models import QuotaReservation, RuntimeAdapter

from ..adapters import (
    DockerSwarmAdapter,
    RuntimeAdapterFailure,
    docker_local_protocol_stub,
    fake_runtime,
    reset_docker_local_protocol_stub,
    reset_fake_runtime,
)
from ..models import ProvisioningInstance, ProvisioningJob
from ..ports import RuntimeSpec
from .test_swarm_adapter import FakeDockerClient


def runtime_spec(**overrides: Any) -> RuntimeSpec:
    values: dict[str, Any] = {
        "task_id": "01TASKMATRIX",
        "course_id": "01COURSEMATRIX",
        "student_id": "01STUDENTMATRIX",
        "runtime_type": "CONTAINER",
        "image_registry": "registry.example.edu",
        "image_repository": "labs/python",
        "image_digest": "sha256:" + "a" * 64,
        "resource_profile_id": "01PROFILEMATRIX",
        "cpu_millicores": 500,
        "memory_mb": 256,
        "disk_gb": 2,
        "network_policy": {"mode": "DENY_ALL"},
        "workspace_capabilities": {"webide": True, "terminal": True},
        "ttl_seconds": 300,
        "workspace_port": 8080,
        "healthcheck_path": "/healthz",
        "trace_id": "a" * 32,
        "instance_public_id": "01INSTANCEMATRIX",
    }
    values.update(overrides)
    return RuntimeSpec(**values)


class RuntimeMatrixTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_fake_runtime()
        reset_docker_local_protocol_stub()

    def tearDown(self) -> None:
        reset_fake_runtime()
        reset_docker_local_protocol_stub()

    def test_fake_local_and_swarm_share_the_same_lifecycle_assertions(self) -> None:
        cases = (
            ("fake", fake_runtime()),
            ("local", docker_local_protocol_stub("runtime/local-matrix")),
            (
                "swarm",
                DockerSwarmAdapter(
                    client=FakeDockerClient(),
                    config={"boot_timeout": 0},
                    config_ref="runtime/swarm-matrix",
                ),
            ),
        )
        for name, adapter in cases:
            with self.subTest(runtime=name):
                spec = runtime_spec(instance_public_id=f"01INSTANCE{name.upper()}")
                adapter.preflight(spec)
                adapter.prepare_image(spec)
                adapter.attach_network(spec)
                created = adapter.create(spec, f"matrix:{name}")

                self.assertTrue(created.external_id)
                self.assertTrue(created.metadata["managed"])
                self.assertEqual(adapter.status(created.external_id), "READY")
                self.assertTrue(adapter.endpoint(created.external_id))
                self.assertEqual(
                    [item.external_id for item in adapter.inventory()],
                    [created.external_id],
                )

                adapter.destroy(created.external_id, f"destroy:{name}")
                self.assertEqual(adapter.status(created.external_id), "ABSENT")
                self.assertEqual(adapter.inventory(), [])


class RuntimeReconciliationCommandTests(TestCase):
    def setUp(self) -> None:
        reset_fake_runtime()
        self.owner, self.course, self.template_version, self.rubric_version = create_domain(
            suffix="reconcile"
        )
        self.adapter = self.template_version.runtime_adapter
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            driver=RuntimeAdapter.Driver.FAKE,
            config_ref="runtime/fake-reconcile",
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        self.adapter.refresh_from_db()
        enrollment = create_enrollment(self.course, suffix="reconcile-student")
        publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="reconcile",
        )
        published, _ = publish_publication(
            course_id=self.course.public_id,
            publication_id=publication.public_id,
            actor=self.owner,
            expected_version=publication.row_version,
            selected_ids=[],
            context=self._context(),
        )
        self.task = published.tasks.get(student=enrollment.student)

    def tearDown(self) -> None:
        reset_fake_runtime()

    def _context(self) -> Any:
        from apps.courses.services import ActorContext

        return ActorContext(self.owner.public_id, "TEACHING", "r" * 32)

    def _instance(self, *, external_id: str | None, status: str) -> ProvisioningInstance:
        return ProvisioningInstance.objects.create(
            task=self.task,
            course=self.course,
            runtime_adapter=self.adapter,
            image=self.task.image,
            resource_profile=self.task.resource_profile,
            runtime_type=self.task.runtime_type,
            status=status,
            external_id=external_id,
            created_trace_id="r" * 32,
        )

    def test_report_only_skips_unavailable_adapter_and_continues(self) -> None:
        RuntimeAdapter.objects.create(
            code="legacy-unavailable",
            name="Legacy unavailable runtime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.DOCKER_SWARM,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
            config_ref="runtime/legacy-unavailable",
            change_reason="test",
        )

        def resolve(driver: str, *, config_ref: str) -> Any:
            if config_ref == "runtime/legacy-unavailable":
                raise RuntimeAdapterFailure("RUNTIME_INVENTORY_FAILED", retryable=True)
            return fake_runtime()

        output = StringIO()
        with patch(
            "apps.provisioning.management.commands.reconcile_runtime_resources.runtime_for_driver",
            side_effect=resolve,
        ):
            call_command("reconcile_runtime_resources", stdout=output)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertTrue(
            any(self.adapter.code in adapter["codes"] for adapter in payload["adapters"])
        )
        self.assertEqual(payload["errors"][0]["adapter_codes"], ["legacy-unavailable"])

    def test_report_only_does_not_relink_or_destroy(self) -> None:
        instance = self._instance(external_id=None, status=ProvisioningInstance.Status.READY)
        result = fake_runtime().create(
            runtime_spec(
                task_id=self.task.public_id,
                course_id=self.course.public_id,
                student_id=self.task.student.public_id,
                instance_public_id=instance.public_id,
            ),
            "reconcile-relink",
        )

        output = StringIO()
        call_command("reconcile_runtime_resources", stdout=output)
        payload = json.loads(output.getvalue())

        instance.refresh_from_db()
        self.assertIsNone(instance.external_id)
        self.assertEqual(payload["summary"]["relinked"], 1)
        self.assertEqual(fake_runtime().inventory()[0].external_id, result.external_id)

    def test_apply_repairs_unique_mapping_and_cleans_unknown_resource(self) -> None:
        instance = self._instance(external_id=None, status=ProvisioningInstance.Status.READY)
        result = fake_runtime().create(
            runtime_spec(
                task_id=self.task.public_id,
                course_id=self.course.public_id,
                student_id=self.task.student.public_id,
                instance_public_id=instance.public_id,
            ),
            "reconcile-relink",
        )
        unknown = fake_runtime().create(
            runtime_spec(
                task_id="01UNKNOWNRECONCILE",
                instance_public_id="",
            ),
            "reconcile-unknown",
        )

        output = StringIO()
        call_command("reconcile_runtime_resources", "--apply", stdout=output)
        payload = json.loads(output.getvalue())

        instance.refresh_from_db()
        self.assertEqual(instance.external_id, result.external_id)
        self.assertEqual(payload["summary"]["relinked"], 1)
        self.assertEqual(payload["summary"]["unknown_resources"], 1)
        self.assertNotIn(
            unknown.external_id,
            [item.external_id for item in fake_runtime().inventory()],
        )

    def test_apply_marks_missing_instance_orphaned_and_releases_only_its_reservation(self) -> None:
        instance = self._instance(
            external_id="missing-runtime-resource",
            status=ProvisioningInstance.Status.READY,
        )
        reservation = QuotaReservation.objects.create(
            reservation_key="reconcile-reservation",
            reservation_type=QuotaReservation.ReservationType.STANDARD,
            subject_type="EXPERIMENT_TASK",
            subject_ref=self.task.public_id,
            course=self.course,
            user=self.task.student,
            resource_profile=self.task.resource_profile,
            reserved_at=timezone.now(),
            trace_id="r" * 32,
        )
        ProvisioningJob.objects.create(
            task=self.task,
            course=self.course,
            reservation=reservation,
            attempt_no=1,
            status=ProvisioningJob.Status.FAILED,
            current_stage=ProvisioningJob.Stage.CREATE,
            idempotency_key="reconcile-job",
            trace_id="r" * 32,
        )

        output = StringIO()
        call_command("reconcile_runtime_resources", "--apply", stdout=output)
        payload = json.loads(output.getvalue())

        instance.refresh_from_db()
        reservation.refresh_from_db()
        self.assertEqual(instance.status, ProvisioningInstance.Status.ORPHANED)
        self.assertEqual(reservation.status, QuotaReservation.Status.RELEASED)
        self.assertEqual(payload["summary"]["orphaned"], 1)
        self.assertEqual(payload["summary"]["reservations_released"], 1)

    def test_apply_releases_terminal_reservation_even_when_runtime_resource_exists(self) -> None:
        instance = self._instance(
            external_id=None,
            status=ProvisioningInstance.Status.FAILED,
        )
        fake_runtime().create(
            runtime_spec(
                task_id=self.task.public_id,
                course_id=self.course.public_id,
                student_id=self.task.student.public_id,
                instance_public_id=instance.public_id,
            ),
            "reconcile-terminal",
        )
        reservation = QuotaReservation.objects.create(
            reservation_key="reconcile-terminal-reservation",
            reservation_type=QuotaReservation.ReservationType.STANDARD,
            subject_type="EXPERIMENT_TASK",
            subject_ref=self.task.public_id,
            course=self.course,
            user=self.task.student,
            resource_profile=self.task.resource_profile,
            reserved_at=timezone.now(),
            trace_id="r" * 32,
        )
        ProvisioningJob.objects.create(
            task=self.task,
            course=self.course,
            reservation=reservation,
            attempt_no=1,
            status=ProvisioningJob.Status.FAILED,
            current_stage=ProvisioningJob.Stage.CREATE,
            idempotency_key="reconcile-terminal-job",
            trace_id="r" * 32,
        )

        output = StringIO()
        call_command("reconcile_runtime_resources", "--apply", stdout=output)

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, QuotaReservation.Status.RELEASED)
        self.assertEqual(json.loads(output.getvalue())["summary"]["reservations_released"], 1)
