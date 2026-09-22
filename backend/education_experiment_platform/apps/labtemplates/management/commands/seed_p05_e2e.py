import os
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import Course, MaterialVersion
from apps.courses.services import ActorContext
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter
from apps.reviews.models import Rubric
from apps.reviews.services import create_rubric, create_rubric_version

from ...models import Template, TemplateVersion
from ...services import create_template, create_version, replace_rules


class Command(BaseCommand):
    help = "Create disposable P05 template and rubric data for local browser verification."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P05 E2E seed is restricted to disposable environments")

        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        course = Course.objects.filter(code="P03-DEMO-001").first()
        if teacher is None or course is None:
            raise CommandError("Run seed_p02_e2e and seed_p03_e2e first")

        trace = secrets.token_hex(16)
        context = ActorContext(teacher.public_id, "TEACHING", trace)
        adapter = self._runtime_adapter()
        image = self._image(teacher)
        profile = self._resource_profile()

        template = Template.objects.filter(course=course, name="P05 容器实验模板").first()
        if template is None:
            template = create_template(
                course_id=course.public_id,
                actor=teacher,
                name="P05 容器实验模板",
                category="系统实验",
                description="用于本地预检、资产扫描和版本冻结验证。",
                context=context,
            )
        version = template.versions.order_by("version_no").first()
        if version is None:
            material = (
                MaterialVersion.objects.filter(
                    material__course=course,
                    status=MaterialVersion.Status.PUBLISHED,
                )
                .order_by("material__title", "-version_no")
                .first()
            )
            version = create_version(
                course_id=course.public_id,
                template_id=template.public_id,
                actor=teacher,
                data={
                    "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                    "runtime_adapter_id": adapter.public_id,
                    "image_id": image.public_id,
                    "resource_profile_id": profile.public_id,
                    "dependencies": [{"name": "pytest", "version": "8"}],
                    "network_policy": {"mode": "DENY_ALL", "privileged": False},
                    "workspace_capabilities": {"require_gateway": True},
                    "material_version_ids": [material.public_id] if material else [],
                    "report_policy": {"required": True},
                    "review_policy": {"mode": "MANUAL_WITH_AUTO_CHECK"},
                    "retention_days": 30,
                },
                context=context,
            )
        if version.status == TemplateVersion.Status.DRAFT and not version.auto_check_rules.filter(
            is_active=True
        ).exists():
            replace_rules(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=teacher,
                expected_version=version.row_version,
                rules=[
                    {
                        "position": 1,
                        "checker_type": "PYTEST",
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "timeout_seconds": 60,
                        "resource_limit": {
                            "cpu_millicores": 1000,
                            "memory_mb": 1024,
                            "disk_gb": 2,
                        },
                        "network_policy": {"mode": "DENY_ALL"},
                        "display_policy": {"show_score": True},
                        "failure_semantics": {"on_failure": "FAIL_CHECK"},
                    }
                ],
                context=context,
            )

        rubric = Rubric.objects.filter(course=course, name="P05 实验评分量规").first()
        if rubric is None:
            rubric = create_rubric(
                course_id=course.public_id,
                actor=teacher,
                name="P05 实验评分量规",
                description="用于本地 Rubric 约束和发布验证。",
                context=context,
            )
        if not rubric.versions.exists():
            create_rubric_version(
                course_id=course.public_id,
                rubric_id=rubric.public_id,
                actor=teacher,
                title="P05 初始评分版本",
                description="",
                total_score=Decimal("100.00"),
                criteria=[
                    {
                        "position": 1,
                        "title": "功能正确性",
                        "description": "",
                        "guidance": "检查实验结果和自动检查输出。",
                        "max_score": "60.00",
                        "weight_basis_points": 6000,
                    },
                    {
                        "position": 2,
                        "title": "报告质量",
                        "description": "",
                        "guidance": "检查报告完整性和可复现性。",
                        "max_score": "40.00",
                        "weight_basis_points": 4000,
                    },
                ],
                context=context,
            )

        self.stdout.write(
            self.style.SUCCESS(
                "P05 E2E data ready: "
                f"course={course.public_id} template={template.public_id} "
                f"version={version.public_id} rubric={rubric.public_id}"
            )
        )

    @staticmethod
    def _runtime_adapter() -> RuntimeAdapter:
        adapter, _ = RuntimeAdapter.objects.get_or_create(
            code="LOCAL-P05",
            defaults={
                "name": "本地 P05 容器运行时",
                "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                "driver": RuntimeAdapter.Driver.DOCKER_SWARM,
                "status": RuntimeAdapter.Status.ENABLED,
                "health_status": RuntimeAdapter.HealthStatus.HEALTHY,
                "node_count": 1,
                "capacity_cpu_millicores": 8000,
                "available_cpu_millicores": 8000,
                "capacity_memory_mb": 16384,
                "available_memory_mb": 16384,
                "config_ref": "runtime/local-p05",
                "change_reason": "P05 disposable seed",
            },
        )
        RuntimeAdapter.objects.filter(pk=adapter.pk).update(
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        )
        adapter.refresh_from_db()
        return adapter

    @staticmethod
    def _image(teacher: User) -> ImageAsset:
        image, _ = ImageAsset.objects.get_or_create(
            digest="sha256:" + "b" * 64,
            defaults={
                "registry": "registry.local",
                "repository": "edu/p05-lab",
                "display_tag": "2026.09",
                "scan_status": ImageAsset.ScanStatus.CLEAN,
                "approval_status": ImageAsset.ApprovalStatus.APPROVED,
                "risk_level": ImageAsset.RiskLevel.LOW,
                "scan_report_ref": "scan/p05-e2e",
                "scanned_at": timezone.now(),
                "approved_by": teacher,
                "approved_at": timezone.now(),
                "change_reason": "P05 disposable seed",
            },
        )
        ImageAsset.objects.filter(pk=image.pk).update(
            scan_status=ImageAsset.ScanStatus.CLEAN,
            approval_status=ImageAsset.ApprovalStatus.APPROVED,
            approved_by=teacher,
            approved_at=timezone.now(),
        )
        image.refresh_from_db()
        return image

    @staticmethod
    def _resource_profile() -> ResourceProfile:
        profile, _ = ResourceProfile.objects.get_or_create(
            code="P05-STANDARD-2C-4G-20G",
            defaults={
                "name": "P05 标准容器规格",
                "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                "status": ResourceProfile.Status.ACTIVE,
                "cpu_millicores": 2000,
                "memory_mb": 4096,
                "disk_gb": 20,
                "network_mode": ResourceProfile.NetworkMode.DENY_ALL,
                "cost_minor_per_hour": 0,
                "currency_code": "CNY",
                "activated_at": timezone.now(),
                "change_reason": "P05 disposable seed",
            },
        )
        ResourceProfile.objects.filter(pk=profile.pk).update(
            status=ResourceProfile.Status.ACTIVE,
            retired_at=None,
        )
        profile.refresh_from_db()
        return profile
