from django.db import IntegrityError, transaction
from django.test import TestCase

from ..models import ImageAsset, Quota, ResourceProfile, RuntimeAdapter, SecurityPolicy
from .helpers import create_governance_admin, create_governance_course, create_governance_teacher


class GovernanceModelTests(TestCase):
    def setUp(self) -> None:
        self.admin = create_governance_admin()
        self.owner = create_governance_teacher(suffix="governance-owner")
        self.course = create_governance_course(self.owner)

    def test_quota_scope_target_matches_scope_type(self) -> None:
        with self.assertRaises(IntegrityError):
            Quota.objects.create(
                scope_type=Quota.ScopeType.PLATFORM,
                scope_key="PLATFORM-BAD",
                course=self.course,
                change_reason="invalid",
            )

    def test_runtime_capacity_cannot_have_more_available_than_total(self) -> None:
        with self.assertRaises(IntegrityError):
            RuntimeAdapter.objects.create(
                code="BAD-RUNTIME",
                name="Bad",
                runtime_type="CONTAINER",
                driver="FAKE",
                capacity_cpu_millicores=100,
                available_cpu_millicores=101,
                capacity_memory_mb=100,
                available_memory_mb=0,
                change_reason="invalid",
            )

    def test_local_docker_requires_container_and_config_reference(self) -> None:
        with transaction.atomic(), self.assertRaises(IntegrityError):
            RuntimeAdapter.objects.create(
                code="LOCAL-VM",
                name="Invalid local VM",
                runtime_type="VM",
                driver="DOCKER_LOCAL",
                change_reason="invalid",
            )

    def test_local_docker_requires_config_reference(self) -> None:
        with transaction.atomic(), self.assertRaises(IntegrityError):
            RuntimeAdapter.objects.create(
                code="LOCAL-NO-CONFIG",
                name="Missing local config",
                runtime_type="CONTAINER",
                driver="DOCKER_LOCAL",
                change_reason="invalid",
            )

    def test_image_digest_is_unique_and_profile_has_positive_resources(self) -> None:
        ImageAsset.objects.create(
            registry="registry.example",
            repository="lab/python",
            digest="sha256:" + "b" * 64,
            risk_level="LOW",
            change_reason="test",
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ImageAsset.objects.create(
                registry="registry.example",
                repository="lab/python-copy",
                digest="sha256:" + "b" * 64,
                risk_level="LOW",
                change_reason="duplicate",
            )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ResourceProfile.objects.create(
                code="INVALID-PROFILE",
                name="Invalid",
                runtime_type="CONTAINER",
                cpu_millicores=0,
                memory_mb=1024,
                disk_gb=1,
                network_mode="DENY_ALL",
                change_reason="invalid",
            )

    def test_policy_kind_scope_is_unique(self) -> None:
        SecurityPolicy.objects.create(
            policy_kind="RUNTIME_SECURITY",
            scope_type="PLATFORM",
            scope_key="PLATFORM",
            risk_level="HIGH",
            rules={
                "default_egress": "DENY_ALL",
                "allow_privileged": False,
                "require_execution_isolation": True,
            },
            updated_by=self.admin,
            change_reason="test",
        )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            SecurityPolicy.objects.create(
                policy_kind="RUNTIME_SECURITY",
                scope_type="PLATFORM",
                scope_key="PLATFORM",
                risk_level="HIGH",
                rules={},
                updated_by=self.admin,
                change_reason="duplicate",
            )
