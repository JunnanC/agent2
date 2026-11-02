import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.core.models import ObjectAsset
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.experiments.services import create_publication, publish_publication
from apps.governance.models import Quota, RuntimeAdapter
from apps.labtemplates.models import TemplateVersion
from apps.labtemplates.services import create_version
from apps.reviews.models import RubricVersion
from apps.workspaces.workbench import _validate_tests_asset


class Command(BaseCommand):
    help = "Initialize a simulated experiment environment, task, and quotas for local verification."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("simulated experiment seed is restricted to disposable environments")
        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        course = Course.objects.filter(code="P03-DEMO-001").first()
        if teacher is None or student is None or course is None:
            raise CommandError("Run seed_accounts_e2e through seed_publications_e2e first")
        trace_id = secrets.token_hex(16)
        fake = self._fake_adapter()
        template_version = self._fake_template_version(course, teacher, fake, trace_id)
        self._quota(
            scope_type=Quota.ScopeType.PLATFORM,
            scope_key="PLATFORM",
            values={
                "max_concurrent_instances": 100,
                "max_concurrent_starts": 100,
                "max_cpu_millicores": 200000,
                "max_memory_mb": 400000,
                "max_disk_gb": 2000,
            },
        )
        self._quota(
            scope_type=Quota.ScopeType.COURSE,
            scope_key=f"COURSE:{course.public_id}",
            course=course,
            values={"max_concurrent_instances": 100, "max_concurrent_starts": 100},
        )
        self._quota(
            scope_type=Quota.ScopeType.USER,
            scope_key=f"USER:{student.public_id}",
            user=student,
            values={
                "max_concurrent_instances": 10,
                "max_concurrent_starts": 10,
                "max_cpu_millicores": 20000,
                "max_memory_mb": 40960,
                "max_disk_gb": 200,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Simulated experiment data ready: "
                f"course={course.public_id} fake_runtime={fake.public_id} "
                f"template_version={template_version.public_id} trace={trace_id}"
            )
        )

    @staticmethod
    @transaction.atomic
    def _fake_template_version(
        course: Course, teacher: User, fake: RuntimeAdapter, trace_id: str
    ) -> TemplateVersion:
        existing = (
            TemplateVersion.objects.filter(
                template__course=course,
                runtime_adapter=fake,
                status=TemplateVersion.Status.PUBLISHED,
            )
            .select_related("template")
            .order_by("-version_no")
            .first()
        )
        if existing is not None:
            context = ActorContext(teacher.public_id, "TEACHING", trace_id)
            version = existing
        else:
            context = ActorContext(teacher.public_id, "TEACHING", trace_id)
            source = (
                TemplateVersion.objects.filter(template__course=course)
                .exclude(runtime_adapter=fake)
                .select_related("template", "image", "resource_profile")
                .order_by("-version_no")
                .first()
            )
            if source is None:
                raise CommandError("template/publication template version is missing")
            version = create_version(
                course_id=course.public_id,
                template_id=source.template.public_id,
                actor=teacher,
                data={
                    "runtime_type": source.runtime_type,
                    "runtime_adapter_id": fake.public_id,
                    "image_id": source.image.public_id,
                    "resource_profile_id": source.resource_profile.public_id,
                    "dependencies": source.dependencies,
                    "execution_spec": source.execution_spec,
                    "network_policy": source.network_policy,
                    "workspace_capabilities": source.workspace_capabilities,
                    "material_version_ids": [],
                    "report_policy": source.report_policy,
                    "review_policy": source.review_policy,
                    "retention_days": source.retention_days,
                },
                context=context,
            )
        version = Command._ensure_tests_asset(version)
        if version.status != TemplateVersion.Status.PUBLISHED:
            version = compare_and_swap(
                TemplateVersion,
                pk=version.pk,
                expected_version=version.row_version,
                changes={
                    "status": TemplateVersion.Status.PUBLISHED,
                    "spec_digest": "f" * 64,
                    "published_by": teacher,
                    "published_at": timezone.now(),
                },
            )
        rubric = (
            RubricVersion.objects.filter(
                rubric__course=course, status=RubricVersion.Status.PUBLISHED
            )
            .order_by("-published_at", "-version_no")
            .first()
        )
        student = User.objects.filter(email="student.integration@example.edu").first()
        if rubric is None or student is None:
            raise CommandError("template rubric and integration student are required")
        enrollment = course.enrollments.filter(student=student, status="ACTIVE").first()
        if enrollment is None:
            raise CommandError("Integration student must be actively enrolled")
        publication = TaskPublication.objects.filter(
            course=course, title__in=("模拟环境实验任务", "P07 FakeRuntime 任务")
        ).first()
        if publication is not None and publication.title == "P07 FakeRuntime 任务":
            publication = compare_and_swap(
                TaskPublication,
                pk=publication.pk,
                expected_version=publication.row_version,
                changes={
                    "title": "模拟环境实验任务",
                    "description": "用于验证实验环境启动、工作台访问和任务执行的模拟实验。",
                },
            )
        if publication is None:
            now = timezone.now()
            publication = create_publication(
                course_id=course.public_id,
                actor=teacher,
                data={
                    "template_version_id": version.public_id,
                    "rubric_version_id": rubric.public_id,
                    "title": "模拟环境实验任务",
                    "description": "用于验证实验环境启动、工作台访问和任务执行的模拟实验。",
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
            publish_publication(
                course_id=course.public_id,
                publication_id=publication.public_id,
                actor=teacher,
                expected_version=publication.row_version,
                selected_ids=[enrollment.public_id],
                context=context,
            )
        task = ExperimentTask.objects.filter(
            publication=publication, student=student
        ).first()
        if task is None:
            raise CommandError("provisioning publication did not create the integration task")
        # Keep the disposable fixture on the first page despite older local runs.
        ExperimentTask.objects.filter(pk=task.pk).update(created_at=timezone.now())
        return version

    @staticmethod
    def _ensure_tests_asset(version: TemplateVersion) -> TemplateVersion:
        tests_id = (version.execution_spec or {}).get("tests_asset")
        source = ObjectAsset.objects.filter(public_id=tests_id).first()
        if (
            source is None
            or source.owner_type != "TEMPLATE_VERSION"
            or source.purpose != "TESTS"
            or source.status != ObjectAsset.Status.ACTIVE
            or source.scan_status != ObjectAsset.ScanStatus.CLEAN
            or not TemplateVersion.objects.filter(
                public_id=source.owner_ref, template=version.template
            ).exists()
        ):
            raise CommandError("FakeRuntime seed requires a clean TESTS asset from this template")
        if source.owner_ref != version.public_id:
            # Like seed_templates_e2e, FakeRuntime uses metadata-only fixture assets.
            # Give each version its own fixture key; never reassign the source asset.
            asset, _ = ObjectAsset.objects.get_or_create(
                bucket=source.bucket,
                object_key=f"template-tests/{version.public_id}/tests.json",
                object_version="seed-v1",
                defaults={
                    "digest_sha256": source.digest_sha256,
                    "size_bytes": source.size_bytes,
                    "media_type": source.media_type,
                    "original_name": source.original_name,
                    "owner_type": "TEMPLATE_VERSION",
                    "owner_ref": version.public_id,
                    "purpose": "TESTS",
                    "scan_status": ObjectAsset.ScanStatus.CLEAN,
                    "status": ObjectAsset.Status.ACTIVE,
                },
            )
            version = compare_and_swap(
                TemplateVersion,
                pk=version.pk,
                expected_version=version.row_version,
                changes={
                    "execution_spec": {**version.execution_spec, "tests_asset": asset.public_id}
                },
            )
        _validate_tests_asset(version)
        return version

    @staticmethod
    def _fake_adapter() -> RuntimeAdapter:
        adapter = RuntimeAdapter.objects.filter(
            code__in=("LOCAL-SIMULATED-EXPERIMENT", "FAKE-LOCAL-P07")
        ).first()
        if adapter is not None:
            if adapter.name == "P07 Local FakeRuntime":
                adapter = compare_and_swap(
                    RuntimeAdapter,
                    pk=adapter.pk,
                    expected_version=adapter.row_version,
                    changes={"name": "本地模拟实验环境"},
                )
            return adapter
        return RuntimeAdapter.objects.create(
            code="LOCAL-SIMULATED-EXPERIMENT",
            name="本地模拟实验环境",
            runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
            driver=RuntimeAdapter.Driver.FAKE,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
            node_count=1,
            capacity_cpu_millicores=200000,
            available_cpu_millicores=200000,
            capacity_memory_mb=400000,
            available_memory_mb=400000,
            config_ref="local-fake-runtime",
            last_health_at=timezone.now(),
            change_reason="simulated experiment initialization",
        )

    @staticmethod
    def _quota(
        *, scope_type: str, scope_key: str, values: dict[str, int], **targets: object
    ) -> None:
        quota = Quota.objects.filter(scope_key=scope_key).first()
        if quota is None:
            Quota.objects.create(
                scope_type=scope_type,
                scope_key=scope_key,
                change_reason="simulated experiment initialization",
                **targets,
                **values,
            )
            return
        changes = {key: value for key, value in values.items() if getattr(quota, key) != value}
        if changes:
            compare_and_swap(
                Quota, pk=quota.pk, expected_version=quota.row_version, changes=changes
            )
