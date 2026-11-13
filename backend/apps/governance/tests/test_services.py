from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.errors import RowVersionConflict
from apps.core.tests.image_runtime import image_runtime, reset_image_runtime

from ..errors import (
    GovernanceStateConflict,
    GovernanceValidationError,
    ImageNotApproved,
    QuotaExceeded,
)
from ..models import ImageAsset, QuotaReservation, ResourceProfile, RuntimeAdapter
from ..selectors import resource_summary
from ..services import (
    ActorContext,
    create_image,
    create_quota,
    create_resource_profile,
    decide_image,
    effective_resource_profile,
    release_reservation,
    reresolve_image_digest,
    reserve_quota,
    resolve_image_digest,
    transition_resource_profile,
    update_image_scan,
    validate_resource_profile,
)
from ..tasks import probe_runtime_adapters
from .helpers import create_governance_admin, create_governance_course, create_governance_teacher


class GovernanceServiceTests(TestCase):
    def setUp(self) -> None:
        self.admin = create_governance_admin()
        self.owner = create_governance_teacher(suffix="service-owner")
        self.student = create_governance_admin(suffix="service-student")
        self.course = create_governance_course(self.owner, code="GOV-SVC-001")
        self.context = ActorContext(self.admin.public_id, "PLATFORM", "s" * 32)
        self.profile = create_resource_profile(
            actor=self.admin,
            code="SVC-2C-4G",
            name="Service profile",
            runtime_type="CONTAINER",
            cpu_millicores=2000,
            memory_mb=4096,
            disk_gb=20,
            network_mode="DENY_ALL",
            cost_minor_per_hour=100,
            currency_code="CNY",
            reason="test profile",
            context=self.context,
        )
        self.profile = transition_resource_profile(
            profile_id=self.profile.public_id,
            actor=self.admin,
            expected_version=self.profile.row_version,
            target_status=ResourceProfile.Status.ACTIVE,
            reason="activate for test",
            context=self.context,
        )
        self.platform_quota = create_quota(
            actor=self.admin,
            scope_type="PLATFORM",
            course_id=None,
            user_id=None,
            values={
                "max_concurrent_instances": 3,
                "max_concurrent_starts": 3,
                "max_cpu_millicores": 6000,
                "max_memory_mb": 12288,
                "max_disk_gb": 60,
            },
            reason="platform quota",
            context=self.context,
        )
        self.course_quota = create_quota(
            actor=self.admin,
            scope_type="COURSE",
            course_id=self.course.public_id,
            user_id=None,
            values={
                "max_concurrent_instances": 2,
                "max_concurrent_starts": 2,
                "max_cpu_millicores": 4000,
                "max_memory_mb": 8192,
                "max_disk_gb": 40,
            },
            reason="course quota",
            context=self.context,
        )
        self.user_quota = create_quota(
            actor=self.admin,
            scope_type="USER",
            course_id=None,
            user_id=self.student.public_id,
            values={
                "max_concurrent_instances": 1,
                "max_concurrent_starts": 1,
                "max_cpu_millicores": 2000,
                "max_memory_mb": 4096,
                "max_disk_gb": 20,
            },
            reason="user quota",
            context=self.context,
        )

    def _reserve(self, key: str) -> QuotaReservation:
        return reserve_quota(
            reservation_key=key,
            reservation_type="STANDARD",
            subject_type="TASK",
            subject_ref=key,
            course_id=self.course.public_id,
            user_id=self.student.public_id,
            resource_profile_id=self.profile.public_id,
            values={
                "instance_count": 1,
                "start_count": 1,
                "cpu_millicores": 2000,
                "memory_mb": 4096,
                "disk_gb": 20,
            },
            expires_at=timezone.now() + timedelta(hours=1),
            context=ActorContext(self.student.public_id, "USER", "r" * 32),
        )

    def test_resource_profile_validation_normalizes_legacy_values(self) -> None:
        values = validate_resource_profile(
            {"cpu_millicores": 500, "memory_mb": 1024, "disk_gb": 5}
        )

        self.assertEqual(values["cpu_request_millicores"], 500)
        self.assertEqual(values["cpu_limit_millicores"], 500)
        self.assertEqual(values["memory_request_mb"], 1024)
        self.assertEqual(values["memory_limit_mb"], 1024)

    def test_resource_profile_validation_rejects_non_positive_and_inverted_limits(self) -> None:
        with self.assertRaises(GovernanceValidationError):
            validate_resource_profile(
                {
                    "cpu_millicores": 500,
                    "memory_mb": 1024,
                    "cpu_request_millicores": 0,
                    "cpu_limit_millicores": 500,
                    "disk_gb": 5,
                }
            )
        with self.assertRaises(GovernanceValidationError):
            validate_resource_profile(
                {
                    "cpu_millicores": 500,
                    "memory_mb": 1024,
                    "cpu_request_millicores": 600,
                    "cpu_limit_millicores": 500,
                    "disk_gb": 5,
                }
            )

    def test_effective_resource_profile_falls_back_for_legacy_task_snapshot(self) -> None:
        task = SimpleNamespace(
            resource_profile=self.profile,
            resource_profile_snapshot={
                "public_id": self.profile.public_id,
                "cpu_millicores": 2000,
                "memory_mb": 4096,
            },
        )

        effective = effective_resource_profile(task)

        self.assertEqual(effective["cpu_request_millicores"], 2000)
        self.assertEqual(effective["cpu_limit_millicores"], 2000)
        self.assertEqual(effective["memory_request_mb"], 4096)
        self.assertEqual(effective["memory_limit_mb"], 4096)

    def test_effective_legacy_snapshot_is_unchanged_when_profile_changes(self) -> None:
        task = SimpleNamespace(
            resource_profile=self.profile,
            resource_profile_snapshot={
                "public_id": self.profile.public_id,
                "cpu_millicores": 2000,
                "memory_mb": 4096,
                "disk_gb": 20,
                "network_mode": "DENY_ALL",
            },
        )
        ResourceProfile.objects.filter(pk=self.profile.pk).update(
            cpu_millicores=8000,
            memory_mb=16384,
            cpu_request_millicores=4000,
            cpu_limit_millicores=8000,
            memory_request_mb=8192,
            memory_limit_mb=16384,
            disk_gb=80,
            network_mode="ALLOWLIST",
        )

        effective = effective_resource_profile(task)

        self.assertEqual(effective["cpu_request_millicores"], 2000)
        self.assertEqual(effective["cpu_limit_millicores"], 2000)
        self.assertEqual(effective["memory_request_mb"], 4096)
        self.assertEqual(effective["memory_limit_mb"], 4096)
        self.assertEqual(effective["disk_gb"], 20)
        self.assertEqual(effective["network_mode"], "DENY_ALL")

    @override_settings(RUNTIME_MODE="fake", RUNTIME_ADAPTER_CODE="runtime/governance")
    def test_runtime_health_probe_uses_configured_runtime_resolver(self) -> None:
        RuntimeAdapter.objects.create(
            code="runtime/governance",
            name="Governance runtime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            status=RuntimeAdapter.Status.ENABLED,
            config_ref="test/local",
            change_reason="test",
        )
        reset_image_runtime()

        with patch(
            "apps.governance.tasks.runtime_for_driver", return_value=image_runtime()
        ) as resolver:
            result = probe_runtime_adapters.run(trace_id="governance-runtime-test")

        self.assertEqual(result, {"runtime/governance": "HEALTHY"})
        resolver.assert_called_once_with(
            RuntimeAdapter.Driver.DOCKER_LOCAL, config_ref="test/local",
        )

    @override_settings(RUNTIME_MODE="fake", RUNTIME_ADAPTER_CODE="runtime/budget")
    def test_runtime_probe_cannot_raise_configured_capacity(self) -> None:
        from types import SimpleNamespace

        adapter = RuntimeAdapter.objects.create(
            code="runtime/budget",
            name="Budgeted runtime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            status=RuntimeAdapter.Status.ENABLED,
            config_ref="test/budget",
            budget_cpu_millicores=1000,
            budget_memory_mb=1024,
            change_reason="test",
        )
        health = {
            "status": "HEALTHY",
            "node_count": 1,
            "capacity_cpu_millicores": 8000,
            "available_cpu_millicores": 6000,
            "capacity_memory_mb": 8192,
            "available_memory_mb": 4096,
        }
        runtime = SimpleNamespace(health=lambda: health)

        with patch("apps.governance.tasks.runtime_for_driver", return_value=runtime):
            probe_runtime_adapters.run(trace_id="governance-budget-test")
            adapter.refresh_from_db()
            self.assertEqual(adapter.capacity_cpu_millicores, 1000)
            self.assertEqual(adapter.available_cpu_millicores, 1000)
            self.assertEqual(adapter.capacity_memory_mb, 1024)
            self.assertEqual(adapter.available_memory_mb, 1024)

            health["capacity_cpu_millicores"] = 500
            health["available_cpu_millicores"] = 400
            probe_runtime_adapters.run(trace_id="governance-budget-test-2")
            adapter.refresh_from_db()
            self.assertEqual(adapter.capacity_cpu_millicores, 500)
            self.assertEqual(adapter.available_cpu_millicores, 400)

    def test_reservation_uses_platform_course_user_intersection(self) -> None:
        reservation = self._reserve("reservation-1")
        self.assertEqual(reservation.status, QuotaReservation.Status.ACTIVE)
        summary = resource_summary(course=self.course, user=self.student)
        self.assertEqual(summary["used"]["instance_count"], 1)
        self.assertEqual(summary["available"]["instance_count"], 0)
        with self.assertRaises(QuotaExceeded):
            self._reserve("reservation-2")

    def test_resource_summary_counts_other_users_against_course_quota(self) -> None:
        self._reserve("reservation-course-user-1")
        other_student = create_governance_admin(suffix="service-other-student")
        create_quota(
            actor=self.admin,
            scope_type="USER",
            course_id=None,
            user_id=other_student.public_id,
            values={"max_concurrent_instances": 1},
            reason="other user quota",
            context=self.context,
        )
        reserve_quota(
            reservation_key="reservation-course-user-2",
            reservation_type="STANDARD",
            subject_type="TASK",
            subject_ref="reservation-course-user-2",
            course_id=self.course.public_id,
            user_id=other_student.public_id,
            resource_profile_id=self.profile.public_id,
            values={"instance_count": 1},
            expires_at=timezone.now() + timedelta(hours=1),
            context=ActorContext(other_student.public_id, "USER", "o" * 32),
        )

        summary = resource_summary(course=self.course, user=self.student)
        self.assertEqual(summary["used"]["instance_count"], 2)
        self.assertEqual(summary["available"]["instance_count"], 0)

    def test_reservation_retry_replays_exactly_and_release_is_idempotent(self) -> None:
        reservation = self._reserve("reservation-replay")
        replay = self._reserve("reservation-replay")
        self.assertEqual(replay.pk, reservation.pk)
        released = release_reservation(
            reservation_id=reservation.public_id,
            reason="finished",
            context=self.context,
        )
        again = release_reservation(
            reservation_id=reservation.public_id,
            reason="duplicate release",
            context=self.context,
        )
        self.assertEqual(released.status, QuotaReservation.Status.RELEASED)
        self.assertEqual(again.pk, reservation.pk)

    def test_image_requires_clean_scan_before_approval(self) -> None:
        image = create_image(
            actor=self.admin,
            registry="registry.example",
            repository="lab/secure",
            display_tag="latest",
            digest="sha256:" + "c" * 64,
            risk_level="LOW",
            reason="register",
            context=self.context,
        )
        with self.assertRaises(ImageNotApproved):
            decide_image(
                image_id=image.public_id,
                actor=self.admin,
                expected_version=image.row_version,
                decision="APPROVED",
                reason="approve",
                context=self.context,
            )
        scanned = update_image_scan(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=image.row_version,
            scan_status="CLEAN",
            scan_report_ref="scan-1",
            risk_level="LOW",
            reason="scan complete",
            context=self.context,
        )
        approved = decide_image(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=scanned.row_version,
            decision="APPROVED",
            reason="approve",
            context=self.context,
        )
        self.assertEqual(approved.approval_status, ImageAsset.ApprovalStatus.APPROVED)

    def test_approved_image_cannot_be_scanned_again_and_cas_is_enforced(self) -> None:
        image = ImageAsset.objects.create(
            registry="registry.example",
            repository="lab/approved",
            digest="sha256:" + "d" * 64,
            scan_status="CLEAN",
            approval_status="APPROVED",
            risk_level="LOW",
            approved_by=self.admin,
            approved_at=timezone.now(),
            change_reason="test",
        )
        with self.assertRaises(GovernanceStateConflict):
            update_image_scan(
                image_id=image.public_id,
                actor=self.admin,
                expected_version=image.row_version,
                scan_status="CLEAN",
                scan_report_ref="scan-2",
                risk_level="LOW",
                reason="invalid",
                context=self.context,
            )
        with self.assertRaises(RowVersionConflict):
            decide_image(
                image_id=image.public_id,
                actor=self.admin,
                expected_version=999,
                decision="RETIRED",
                reason="retire",
                context=self.context,
            )


class ImageDigestResolutionTests(TestCase):
    def setUp(self) -> None:
        reset_image_runtime()
        self.addCleanup(reset_image_runtime)
        runtime = patch("apps.governance.services.runtime_for_driver", return_value=image_runtime())
        runtime.start()
        self.addCleanup(runtime.stop)
        self.admin = create_governance_admin(suffix="resolve-admin")
        self.context = ActorContext(self.admin.public_id, "PLATFORM", "r" * 32)

    def _create_pending_image(self, *, with_digest: bool) -> ImageAsset:
        return create_image(
            actor=self.admin,
            registry="docker.io",
            repository="library/ubuntu",
            display_tag="22.04",
            digest="sha256:" + "e" * 64 if with_digest else "",
            risk_level="LOW",
            reason="catalog import",
            context=self.context,
        )

    def _enabled_image_runtime(self) -> RuntimeAdapter:
        return RuntimeAdapter.objects.create(
            code="RESOLVE-FAKE",
            name="Resolve fake runtime",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            status=RuntimeAdapter.Status.ENABLED,
            config_ref="test/local",
        )

    def test_create_image_without_digest_stays_pending_resolution(self) -> None:
        image = self._create_pending_image(with_digest=False)
        self.assertIsNone(image.digest)
        self.assertFalse(image.is_ready)
        self.assertEqual(image.approval_status, ImageAsset.ApprovalStatus.PENDING)

    def test_resolve_image_digest_uses_enabled_runtime_and_locks_afterwards(self) -> None:
        self._enabled_image_runtime()
        image = self._create_pending_image(with_digest=False)
        resolved = resolve_image_digest(
            image_id=image.public_id,
            expected_version=image.row_version,
            reason="platform resolve",
            context=self.context,
        )
        self.assertTrue(resolved.digest.startswith("sha256:"))
        self.assertEqual(len(resolved.digest), 71)
        with self.assertRaises(GovernanceStateConflict):
            resolve_image_digest(
                image_id=image.public_id,
                expected_version=resolved.row_version,
                reason="repeat resolve",
                context=self.context,
            )
        unlocked = resolve_image_digest(
            image_id=image.public_id,
            reason="worker retry replay",
            allow_resolved=True,
            context=self.context,
        )
        self.assertEqual(unlocked.public_id, image.public_id)
        self.assertTrue(unlocked.digest.startswith("sha256:"))

    def test_resolve_image_without_expected_version_uses_current_row(self) -> None:
        self._enabled_image_runtime()
        image = self._create_pending_image(with_digest=False)
        resolved = resolve_image_digest(
            image_id=image.public_id,
            reason="worker resolve",
            context=self.context,
        )
        self.assertTrue(resolved.digest.startswith("sha256:"))

    def test_resolve_duplicate_content_marks_row_rejected_with_reference(self) -> None:
        self._enabled_image_runtime()
        first = self._create_pending_image(with_digest=False)
        approved = resolve_image_digest(
            image_id=first.public_id,
            reason="first import",
            context=self.context,
        )
        duplicate_row = create_image(
            actor=self.admin,
            registry="docker.io",
            repository="library/ubuntu",
            display_tag="22.04",
            digest="",
            risk_level="LOW",
            reason="duplicate import",
            context=self.context,
        )
        duplicate = resolve_image_digest(
            image_id=duplicate_row.public_id,
            reason="duplicate import",
            context=self.context,
        )
        self.assertEqual(duplicate.approval_status, ImageAsset.ApprovalStatus.REJECTED)
        self.assertIsNone(duplicate.digest)
        self.assertIn(approved.public_id, duplicate.change_reason)
        self.assertNotEqual(duplicate.public_id, first.public_id)

    def test_resolve_image_requires_enabled_runtime(self) -> None:
        image = self._create_pending_image(with_digest=False)
        with self.assertRaises(GovernanceValidationError):
            resolve_image_digest(
                image_id=image.public_id,
                reason="no runtime",
                context=self.context,
            )

    def test_resolve_rejected_for_retired_image(self) -> None:
        self._enabled_image_runtime()
        image = ImageAsset.objects.create(
            registry="docker.io",
            repository="library/retired",
            digest=None,
            approval_status=ImageAsset.ApprovalStatus.RETIRED,
            risk_level="LOW",
        )
        with self.assertRaises(GovernanceStateConflict):
            resolve_image_digest(
                image_id=image.public_id,
                reason="resolve retired",
                context=self.context,
            )

    def test_approval_blocked_until_digest_resolved(self) -> None:
        self._enabled_image_runtime()
        image = self._create_pending_image(with_digest=False)
        scanned = update_image_scan(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=image.row_version,
            scan_status=ImageAsset.ScanStatus.CLEAN,
            scan_report_ref="scan-1",
            risk_level="LOW",
            reason="scan complete",
            context=self.context,
        )
        with self.assertRaises(GovernanceValidationError):
            decide_image(
                image_id=image.public_id,
                actor=self.admin,
                expected_version=scanned.row_version,
                decision="APPROVED",
                reason="approve",
                context=self.context,
            )
        resolved = resolve_image_digest(
            image_id=image.public_id,
            reason="platform resolve",
            context=self.context,
        )
        approved = decide_image(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=resolved.row_version,
            decision="APPROVED",
            reason="approve",
            context=self.context,
        )
        self.assertEqual(approved.approval_status, ImageAsset.ApprovalStatus.APPROVED)
        self.assertTrue(approved.is_ready)

    def test_reresolve_is_idempotent_when_digest_unchanged(self) -> None:
        self._enabled_image_runtime()
        image = self._create_pending_image(with_digest=False)
        resolved = resolve_image_digest(
            image_id=image.public_id,
            reason="first resolve",
            context=self.context,
        )
        scanned = update_image_scan(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=resolved.row_version,
            scan_status=ImageAsset.ScanStatus.CLEAN,
            scan_report_ref="scan-reresolve-idle",
            risk_level="LOW",
            reason="scan before approve",
            context=self.context,
        )
        approved = decide_image(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=scanned.row_version,
            decision="APPROVED",
            reason="approve",
            context=self.context,
        )
        before_version = approved.row_version
        revisited = reresolve_image_digest(
            image_id=image.public_id,
            reason="no drift",
            context=self.context,
        )
        self.assertEqual(revisited.digest, approved.digest)
        self.assertEqual(revisited.approval_status, ImageAsset.ApprovalStatus.APPROVED)
        self.assertEqual(revisited.scan_status, ImageAsset.ScanStatus.CLEAN)
        self.assertEqual(revisited.row_version, before_version)

    def test_reresolve_updates_digest_and_resets_scan_approval(self) -> None:
        self._enabled_image_runtime()
        image = self._create_pending_image(with_digest=True)
        scanned = update_image_scan(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=image.row_version,
            scan_status=ImageAsset.ScanStatus.CLEAN,
            scan_report_ref="scan-reresolve-drift",
            risk_level="LOW",
            reason="scan before approve",
            context=self.context,
        )
        decide_image(
            image_id=image.public_id,
            actor=self.admin,
            expected_version=scanned.row_version,
            decision="APPROVED",
            reason="approve baseline",
            context=self.context,
        )
        drifted = "sha256:" + "a" * 64
        with patch("apps.governance.services.runtime_for_driver") as factory:
            factory.return_value.resolve_image.return_value = {"digest": drifted}
            result = reresolve_image_digest(
                image_id=image.public_id,
                reason="runtime image rebuilt",
                context=self.context,
            )
        self.assertEqual(result.digest, drifted)
        self.assertEqual(result.approval_status, ImageAsset.ApprovalStatus.PENDING)
        self.assertEqual(result.scan_status, ImageAsset.ScanStatus.PENDING)
        self.assertIsNone(result.approved_at)

    def test_reresolve_delegates_to_first_resolution_when_digest_missing(self) -> None:
        self._enabled_image_runtime()
        image = self._create_pending_image(with_digest=False)
        result = reresolve_image_digest(
            image_id=image.public_id,
            reason="no digest yet",
            context=self.context,
        )
        self.assertTrue((result.digest or "").startswith("sha256:"))
        self.assertEqual(result.approval_status, ImageAsset.ApprovalStatus.PENDING)

    def test_reresolve_conflicts_for_retired_image(self) -> None:
        self._enabled_image_runtime()
        image = ImageAsset.objects.create(
            registry="docker.io",
            repository="library/retired",
            digest="sha256:" + "c" * 64,
            approval_status=ImageAsset.ApprovalStatus.RETIRED,
            risk_level="LOW",
        )
        with self.assertRaises(GovernanceStateConflict):
            reresolve_image_digest(
                image_id=image.public_id,
                reason="reresolve retired",
                context=self.context,
            )

    def test_reresolve_conflicts_when_new_digest_collides_with_catalog(self) -> None:
        self._enabled_image_runtime()
        holder = ImageAsset.objects.create(
            registry="docker.io",
            repository="library/holder",
            digest="sha256:" + "a" * 64,
            approval_status=ImageAsset.ApprovalStatus.APPROVED,
            risk_level="LOW",
        )
        image = self._create_pending_image(with_digest=True)
        with patch("apps.governance.services.runtime_for_driver") as factory:
            factory.return_value.resolve_image.return_value = {"digest": holder.digest}
            with self.assertRaises(GovernanceStateConflict) as ctx:
                reresolve_image_digest(
                    image_id=image.public_id,
                    reason="drift into existing asset",
                    context=self.context,
                )
        self.assertEqual(ctx.exception.detail.get("duplicate_of"), holder.public_id)
