from django.test import TestCase
from django.utils import timezone

from apps.experiments.tests.helpers import create_draft_publication
from apps.governance.errors import QuotaExceeded
from apps.governance.models import QuotaReservation, RuntimeAdapter

from ..models import RuntimeCapacityReservation
from ..services import release_runtime_capacity, reserve_runtime_capacity


class RuntimeCapacityTests(TestCase):
    def setUp(self) -> None:
        from apps.experiments.tests.test_assessment import AssessmentTests
        AssessmentTests.setUp(self)
        self.adapter = self.publication.template_version.runtime_adapter
        self.template_version = self.publication.template_version
        self.rubric_version = self.publication.rubric_version

    def test_health_probe_preserves_active_execution_capacity(self) -> None:
        from apps.governance.services import record_runtime_health

        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            driver="DOCKER_LOCAL", config_ref="capacity/local",
            capacity_cpu_millicores=4000, available_cpu_millicores=4000,
            capacity_memory_mb=8192, available_memory_mb=8192,
        )
        reservation = QuotaReservation.objects.create(
            reservation_key="health-capacity", reservation_type="STANDARD",
            subject_type="ASSESSMENT", subject_ref=self.task.public_id,
            reserved_at=timezone.now(), trace_id="capacity",
        )
        reserve_runtime_capacity(
            reservation_id=reservation, runtime_adapter_id=self.adapter.public_id,
            cpu_millicores=1000, memory_mb=1024,
        )
        updated = record_runtime_health(
            adapter_id=self.adapter.public_id, health_status="HEALTHY", node_count=1,
            capacity_cpu_millicores=4000, available_cpu_millicores=4000,
            capacity_memory_mb=8192, available_memory_mb=8192, detail={}, trace_id="capacity",
        )
        assert updated.available_cpu_millicores == 3000
        assert updated.available_memory_mb == 7168

    def test_template_creation_does_not_change_runtime_capacity(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            capacity_cpu_millicores=4000,
            available_cpu_millicores=4000,
            capacity_memory_mb=8192,
            available_memory_mb=8192,
        )
        before = RuntimeAdapter.objects.values_list(
            "available_cpu_millicores", "available_memory_mb"
        ).get(pk=self.adapter.pk)

        create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=self.template_version,
            rubric_version=self.rubric_version,
            suffix="provisioning-capacity-publication",
        )

        self.assertEqual(
            RuntimeAdapter.objects.values_list(
                "available_cpu_millicores", "available_memory_mb"
            ).get(pk=self.adapter.pk),
            before,
        )

    def test_runtime_capacity_rejects_insufficient_capacity(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            capacity_cpu_millicores=1000,
            available_cpu_millicores=1000,
            capacity_memory_mb=2048,
            available_memory_mb=2048,
        )
        reservation = QuotaReservation.objects.create(
            reservation_key="runtime-capacity-insufficient",
            reservation_type=QuotaReservation.ReservationType.STANDARD,
            subject_type="TASK",
            subject_ref="runtime-capacity-insufficient",
            course=self.course,
            user=self.enrollment.student,
            resource_profile=self.template_version.resource_profile,
            reserved_at=timezone.now(),
            trace_id="capacity-insufficient-test",
        )

        with self.assertRaises(QuotaExceeded) as raised:
            reserve_runtime_capacity(
                reservation_id=reservation,
                runtime_adapter_id=self.adapter.public_id,
                cpu_millicores=2000,
                memory_mb=4096,
            )

        self.assertEqual(raised.exception.code, "QUOTA_EXCEEDED")
        self.adapter.refresh_from_db()
        self.assertEqual(self.adapter.available_cpu_millicores, 1000)
        self.assertEqual(self.adapter.available_memory_mb, 2048)

    def test_runtime_capacity_binding_is_reused_and_release_is_idempotent(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            capacity_cpu_millicores=4000,
            available_cpu_millicores=4000,
            capacity_memory_mb=8192,
            available_memory_mb=8192,
        )
        reservation = QuotaReservation.objects.create(
            reservation_key="runtime-capacity-replay",
            reservation_type=QuotaReservation.ReservationType.STANDARD,
            subject_type="TASK",
            subject_ref="runtime-capacity-replay",
            course=self.course,
            user=self.enrollment.student,
            resource_profile=self.template_version.resource_profile,
            reserved_at=timezone.now(),
            trace_id="capacity-replay-test",
        )

        binding = reserve_runtime_capacity(
            reservation_id=reservation,
            runtime_adapter_id=self.adapter.public_id,
            cpu_millicores=2000,
            memory_mb=4096,
        )
        replay = reserve_runtime_capacity(
            reservation_id=reservation,
            runtime_adapter_id=self.adapter.public_id,
            cpu_millicores=2000,
            memory_mb=4096,
        )
        self.assertEqual(binding.pk, replay.pk)
        self.adapter.refresh_from_db()
        self.assertEqual(self.adapter.available_cpu_millicores, 2000)
        self.assertEqual(self.adapter.available_memory_mb, 4096)

        released = release_runtime_capacity(reservation_id=reservation)
        again = release_runtime_capacity(reservation_id=reservation)

        self.assertEqual(released.pk, binding.pk)
        self.assertEqual(again.pk, binding.pk)
        self.assertEqual(again.status, RuntimeCapacityReservation.Status.RELEASED)
        self.adapter.refresh_from_db()
        self.assertEqual(self.adapter.available_cpu_millicores, 4000)
        self.assertEqual(self.adapter.available_memory_mb, 8192)

    def test_runtime_capacity_release_restores_memory_when_cpu_capacity_is_unreported(self) -> None:
        RuntimeAdapter.objects.filter(pk=self.adapter.pk).update(
            capacity_cpu_millicores=0,
            available_cpu_millicores=0,
            capacity_memory_mb=8192,
            available_memory_mb=8192,
        )
        reservation = QuotaReservation.objects.create(
            reservation_key="runtime-capacity-memory-only",
            reservation_type=QuotaReservation.ReservationType.STANDARD,
            subject_type="TASK",
            subject_ref="runtime-capacity-memory-only",
            course=self.course,
            user=self.enrollment.student,
            resource_profile=self.template_version.resource_profile,
            reserved_at=timezone.now(),
            trace_id="capacity-memory-test",
        )

        reserve_runtime_capacity(
            reservation_id=reservation,
            runtime_adapter_id=self.adapter.public_id,
            cpu_millicores=2000,
            memory_mb=4096,
        )
        self.adapter.refresh_from_db()
        self.assertEqual(self.adapter.available_memory_mb, 4096)
        release_runtime_capacity(reservation_id=reservation)
        self.adapter.refresh_from_db()
        self.assertEqual(self.adapter.available_memory_mb, 8192)
