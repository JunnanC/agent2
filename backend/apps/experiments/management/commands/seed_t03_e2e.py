import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter
from apps.labtemplates.models import Template, TemplatePrecheckRun, TemplateVersion
from apps.labtemplates.services import (
    create_template,
    create_version,
    execute_precheck,
    request_precheck,
)
from apps.reviews.models import RubricVersion

from ...models import ExperimentTask, TaskPublication
from ...services import (
    create_publication,
    execute_publication_assignment,
    publish_publication,
)


class Command(BaseCommand):
    help = "Create a disposable, independent T03 DOCKER_LOCAL algorithm task."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("T03 E2E seed is restricted to disposable environments")
        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        course = Course.objects.filter(code="P03-DEMO-001").first()
        if teacher is None or student is None or course is None:
            raise CommandError("Run seed_p02_e2e and seed_p03_e2e first")
        rubric_version = (
            RubricVersion.objects.filter(
                rubric__course=course, status=RubricVersion.Status.PUBLISHED
            )
            .select_related("rubric")
            .order_by("-published_at", "-version_no")
            .first()
        )
        if rubric_version is None:
            raise CommandError("Run seed_p05_e2e first to create a published rubric")

        trace = secrets.token_hex(16)
        context = ActorContext(teacher.public_id, "TEACHING", trace)
        adapter = self._runtime_adapter()
        image = self._image(teacher)
        profile = self._resource_profile()
        template = Template.objects.filter(course=course, name="T03 本地算法实验模板").first()
        if template is None:
            template = create_template(
                course_id=course.public_id,
                actor=teacher,
                name="T03 本地算法实验模板",
                category="算法实验",
                description="独立于 P07 FakeRuntime 的本地 Docker 算法实验。",
                context=context,
            )
        version = template.versions.order_by("version_no").first()
        if version is None:
            version = create_version(
                course_id=course.public_id,
                template_id=template.public_id,
                actor=teacher,
                data={
                    "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                    "runtime_adapter_id": adapter.public_id,
                    "image_id": image.public_id,
                    "resource_profile_id": profile.public_id,
                    "dependencies": [],
                    "network_policy": {"mode": "DENY_ALL", "privileged": False},
                    "workspace_capabilities": {
                        "require_gateway": True,
                        "webide": True,
                        "terminal": True,
                    },
                    "material_version_ids": [],
                    "report_policy": {"required": True},
                    "review_policy": {"mode": "MANUAL_WITH_AUTO_CHECK"},
                    "retention_days": 30,
                },
                context=context,
            )
        tests_asset = ObjectAsset.objects.filter(
            owner_type="TEMPLATE_VERSION", owner_ref=version.public_id, purpose="TESTS"
        ).first()
        if tests_asset is None:
            tests_asset = ObjectAsset.objects.create(
                public_id=new_ulid(),
                bucket="template-assets",
                object_key=f"template-tests/{version.public_id}/tests.json",
                object_version="t03-seed-v1",
                digest_sha256="d" * 64,
                size_bytes=2,
                media_type="application/json",
                original_name="tests.json",
                owner_type="TEMPLATE_VERSION",
                owner_ref=version.public_id,
                purpose="TESTS",
                scan_status=ObjectAsset.ScanStatus.CLEAN,
                status=ObjectAsset.Status.ACTIVE,
            )
        if version.status in {TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECK_FAILED}:
            TemplateVersion.objects.filter(pk=version.pk).update(
                execution_spec={
                    "language": "python",
                    "entrypoint": "main.py",
                    "timeout_seconds": 5,
                    "memory_mb": 256,
                    "cpu_millicores": 500,
                    "comparator": "token",
                    "tests_asset": tests_asset.public_id,
                    "network_mode": "DENY_ALL",
                }
            )
            version.refresh_from_db()
            run = request_precheck(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=teacher,
                expected_version=version.row_version,
                context=context,
            )
            execute_precheck(run_id=run.public_id)
            version.refresh_from_db()
        elif version.status == TemplateVersion.Status.PRECHECKING:
            run = TemplatePrecheckRun.objects.filter(
                template_version=version,
                status__in=(
                    TemplatePrecheckRun.Status.QUEUED,
                    TemplatePrecheckRun.Status.RUNNING,
                    TemplatePrecheckRun.Status.RETRY,
                ),
            ).order_by("-created_at").first()
            if run is None:
                raise CommandError("T03 template precheck state is inconsistent")
            execute_precheck(run_id=run.public_id)
            version.refresh_from_db()
        if version.status == TemplateVersion.Status.PRECHECK_PASSED:
            from apps.labtemplates.services import publish_version

            version = publish_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=teacher,
                expected_version=version.row_version,
                context=context,
            )
        if version.status != TemplateVersion.Status.PUBLISHED:
            raise CommandError(f"T03 template version cannot be published: {version.status}")

        publication = TaskPublication.objects.filter(
            course=course, title="T03 本地算法运行任务"
        ).first()
        if publication is None:
            now = timezone.now()
            publication = create_publication(
                course_id=course.public_id,
                actor=teacher,
                data={
                    "template_version_id": version.public_id,
                    "rubric_version_id": rubric_version.public_id,
                    "title": "T03 本地算法运行任务",
                    "description": "用于验证发布时固定执行规则和运行时配置。",
                    "audience_mode": TaskPublication.AudienceMode.SELECTED,
                    "late_enrollment_policy": TaskPublication.LateEnrollmentPolicy.DO_NOT_ASSIGN,
                    "window_start": now - timezone.timedelta(hours=1),
                    "window_end": now + timezone.timedelta(days=7),
                    "assignment_deadline": now + timezone.timedelta(days=5),
                    "report_required": True,
                    "review_mode": TaskPublication.ReviewMode.MANUAL_WITH_AUTO_CHECK,
                    "prerequisites": [],
                },
                context=context,
            )
        if publication.status == TaskPublication.Status.DRAFT:
            publication, _ = publish_publication(
                course_id=course.public_id,
                publication_id=publication.public_id,
                actor=teacher,
                expected_version=publication.row_version,
                selected_ids=[
                    item.public_id
                    for item in course.enrollments.filter(
                        student=student, status="ACTIVE"
                    )
                ],
                context=context,
            )
        if publication.status == TaskPublication.Status.PUBLISHING:
            publication = execute_publication_assignment(
                publication_id=publication.public_id, context=context
            )
        task = ExperimentTask.objects.filter(publication=publication, student=student).first()
        if task is None:
            raise CommandError("T03 publication did not create the integration student's task")
        self.stdout.write(
            self.style.SUCCESS(
                "T03 E2E data ready: "
                f"course={course.public_id} template_version={version.public_id} "
                f"template_spec_digest={version.spec_digest} tests_asset={tests_asset.public_id} "
                f"publication={publication.public_id} task={task.public_id} "
                f"student={student.public_id} teacher={teacher.public_id} "
                f"runtime_adapter={adapter.public_id} image={image.public_id} "
                f"resource_profile={profile.public_id}"
            )
        )

    @staticmethod
    def _runtime_adapter() -> RuntimeAdapter:
        adapter, _ = RuntimeAdapter.objects.get_or_create(
            code="T03-DOCKER-LOCAL",
            defaults={
                "name": "T03 本地 Docker 算法运行时",
                "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                "driver": RuntimeAdapter.Driver.DOCKER_LOCAL,
                "status": RuntimeAdapter.Status.ENABLED,
                "health_status": RuntimeAdapter.HealthStatus.HEALTHY,
                "node_count": 1,
                "capacity_cpu_millicores": 8000,
                "available_cpu_millicores": 8000,
                "capacity_memory_mb": 16384,
                "available_memory_mb": 16384,
                "config_ref": "runtime/local-algorithm",
                "last_health_at": timezone.now(),
                "change_reason": "T03 disposable local seed",
            },
        )
        RuntimeAdapter.objects.filter(pk=adapter.pk).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
            config_ref="runtime/local-algorithm",
        )
        adapter.refresh_from_db()
        return adapter

    @staticmethod
    def _image(teacher: User) -> ImageAsset:
        image, _ = ImageAsset.objects.get_or_create(
            digest="sha256:" + "e" * 64,
            defaults={
                "registry": "registry.local",
                "repository": "edu/algorithm-workspace",
                "display_tag": "local",
                "scan_status": ImageAsset.ScanStatus.CLEAN,
                "approval_status": ImageAsset.ApprovalStatus.APPROVED,
                "risk_level": ImageAsset.RiskLevel.LOW,
                "approved_by": teacher,
                "approved_at": timezone.now(),
                "change_reason": "T03 disposable local seed",
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
            code="T03-PYTHON-256M",
            defaults={
                "name": "T03 Python 算法规格",
                "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                "status": ResourceProfile.Status.ACTIVE,
                "cpu_millicores": 500,
                "memory_mb": 256,
                "disk_gb": 2,
                "network_mode": ResourceProfile.NetworkMode.DENY_ALL,
                "activated_at": timezone.now(),
                "change_reason": "T03 disposable local seed",
            },
        )
        ResourceProfile.objects.filter(pk=profile.pk).update(
            status=ResourceProfile.Status.ACTIVE,
            retired_at=None,
        )
        profile.refresh_from_db()
        return profile
