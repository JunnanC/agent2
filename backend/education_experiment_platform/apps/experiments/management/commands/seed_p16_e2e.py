"""Seed one disposable P16 real-workspace journey.

The command deliberately creates a separate publication from the older P07/P15
fixtures.  Its template exposes only the capabilities implemented by the P16
workspace image and points at a real, clean MinIO object for both the starter
file and the judge cases.
"""

from __future__ import annotations

import hashlib
import io
import os
import secrets
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.core.assets import register_asset, set_scan_result
from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter
from apps.labtemplates.models import Template, TemplatePrecheckRun, TemplateVersion
from apps.labtemplates.services import (
    create_template,
    create_version,
    execute_precheck,
    replace_rules,
)
from apps.reviews.models import RubricVersion

from ...models import ExperimentTask, TaskPublication
from ...services import create_publication, execute_publication_assignment, publish_publication


class Command(BaseCommand):
    help = "Create a disposable P16 DOCKER_LOCAL real-workspace task and assets."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--run-id", default="manual")

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P16 E2E seed is restricted to disposable environments")
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

        run_id = str(options.get("run_id") or "manual").strip()[:48]
        trace = secrets.token_hex(16)
        context = ActorContext(teacher.public_id, "TEACHING", trace)
        adapter = self._runtime_adapter()
        image = self._image(teacher)
        profile = self._resource_profile()
        template = Template.objects.filter(course=course, name="P16 真实工作区模板").first()
        if template is None:
            template = create_template(
                course_id=course.public_id,
                actor=teacher,
                name="P16 真实工作区模板",
                category="算法实验",
                description="P16 单文件 Python WebIDE 与快照隔离验收模板。",
                context=context,
            )
        version = template.versions.order_by("-version_no").first()
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
                        "notebook": False,
                        "terminal": False,
                        "preview": False,
                        "snapshot": True,
                        "checkpoint": True,
                    },
                    "material_version_ids": [],
                    "report_policy": {"required": False},
                    "review_policy": {"mode": "MANUAL_WITH_AUTO_CHECK"},
                    "retention_days": 30,
                },
                context=context,
            )

        starter = self._asset(
            version,
            purpose="STARTER",
            name="main.py",
            media_type="text/x-python",
            content=(b"import sys\n\nvalue = sys.stdin.read().strip()\nprint(value.upper())\n"),
        )
        tests = self._asset(
            version,
            purpose="TESTS",
            name="tests.json",
            media_type="application/json",
            content=b'{"cases":[{"input":"p16\n","expected":"P16"}]}',
        )
        if version.status in {TemplateVersion.Status.DRAFT, TemplateVersion.Status.PRECHECK_FAILED}:
            TemplateVersion.objects.filter(pk=version.pk).update(
                starter_asset=starter,
                execution_spec={
                    "language": "python",
                    "entrypoint": "main.py",
                    "timeout_seconds": 5,
                    "memory_mb": 256,
                    "cpu_millicores": 500,
                    "comparator": "token",
                    "tests_asset": tests.public_id,
                    "network_mode": "DENY_ALL",
                },
                workspace_capabilities={
                    "require_gateway": True,
                    "webide": True,
                    "notebook": False,
                    "terminal": False,
                    "preview": False,
                    "snapshot": True,
                    "checkpoint": True,
                },
            )
            version.refresh_from_db()
            if not version.auto_check_rules.filter(is_active=True).exists():
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
                            "timeout_seconds": 30,
                            "resource_limit": {
                                "cpu_millicores": 500,
                                "memory_mb": 256,
                                "disk_gb": 1,
                            },
                            "network_policy": {"mode": "DENY_ALL"},
                            "display_policy": {"show_score": True},
                            "failure_semantics": {"on_failure": "FAIL_CHECK"},
                        }
                    ],
                    context=context,
                )
                version.refresh_from_db()
            run = request_precheck_for_seed(version, course.public_id, teacher, context)
            execute_precheck(run_id=run.public_id)
            version.refresh_from_db()
        elif version.status == TemplateVersion.Status.PRECHECKING:
            run = (
                TemplatePrecheckRun.objects.filter(
                    template_version=version,
                    status__in=(
                        TemplatePrecheckRun.Status.QUEUED,
                        TemplatePrecheckRun.Status.RUNNING,
                        TemplatePrecheckRun.Status.RETRY,
                    ),
                )
                .order_by("-created_at")
                .first()
            )
            if run is None:
                raise CommandError("P16 template precheck state is inconsistent")
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
            raise CommandError(f"P16 template version cannot be published: {version.status}")

        title = f"P16 真实工作区验收 {run_id}"
        publication = TaskPublication.objects.filter(course=course, title=title).first()
        if publication is None:
            now = timezone.now()
            publication = create_publication(
                course_id=course.public_id,
                actor=teacher,
                data={
                    "template_version_id": version.public_id,
                    "rubric_version_id": rubric_version.public_id,
                    "title": title,
                    "description": "用于验证 WebIDE、快照、检查点恢复和运行时回收。",
                    "audience_mode": TaskPublication.AudienceMode.SELECTED,
                    "late_enrollment_policy": TaskPublication.LateEnrollmentPolicy.DO_NOT_ASSIGN,
                    "window_start": now - timezone.timedelta(hours=1),
                    "window_end": now + timezone.timedelta(days=1),
                    "assignment_deadline": now + timezone.timedelta(days=1),
                    "report_required": False,
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
                    for item in course.enrollments.filter(student=student, status="ACTIVE")
                ],
                context=context,
            )
        if publication.status == TaskPublication.Status.PUBLISHING:
            publication = execute_publication_assignment(
                publication_id=publication.public_id, context=context
            )
        task = ExperimentTask.objects.filter(publication=publication, student=student).first()
        if task is None:
            raise CommandError("P16 publication did not create the integration student's task")
        self.stdout.write(
            self.style.SUCCESS(
                "P16 E2E data ready: "
                f"title={title} course={course.public_id} template_version={version.public_id} "
                f"publication={publication.public_id} task={task.public_id} "
                f"student={student.public_id} image_digest={image.digest}"
            )
        )

    @staticmethod
    def _runtime_adapter() -> RuntimeAdapter:
        adapter, _ = RuntimeAdapter.objects.get_or_create(
            code="P16-DOCKER-LOCAL",
            defaults={
                "name": "P16 本地 Docker 真实工作区",
                "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                "driver": RuntimeAdapter.Driver.DOCKER_LOCAL,
                "status": RuntimeAdapter.Status.ENABLED,
                "health_status": RuntimeAdapter.HealthStatus.HEALTHY,
                "node_count": 1,
                "capacity_cpu_millicores": 8000,
                "available_cpu_millicores": 8000,
                "capacity_memory_mb": 16384,
                "available_memory_mb": 16384,
                "config_ref": "runtime/local-docker",
                "last_health_at": timezone.now(),
                "change_reason": "P16 disposable local seed",
            },
        )
        RuntimeAdapter.objects.filter(pk=adapter.pk).update(
            driver=RuntimeAdapter.Driver.DOCKER_LOCAL,
            status=RuntimeAdapter.Status.ENABLED,
            health_status=RuntimeAdapter.HealthStatus.HEALTHY,
            config_ref="runtime/local-docker",
        )
        adapter.refresh_from_db()
        return adapter

    @staticmethod
    def _image(teacher: User) -> ImageAsset:
        digest = str(os.getenv("P16_IMAGE_DIGEST", "")).strip()
        if not (digest.startswith("sha256:") and len(digest) == 71):
            digest = "sha256:" + "0" * 64
        image, _ = ImageAsset.objects.get_or_create(
            digest=digest,
            defaults={
                "registry": "local",
                "repository": "edu-platform-algorithm-workspace",
                "display_tag": "p16-local",
                "scan_status": ImageAsset.ScanStatus.CLEAN,
                "approval_status": ImageAsset.ApprovalStatus.APPROVED,
                "risk_level": ImageAsset.RiskLevel.LOW,
                "approved_by": teacher,
                "approved_at": timezone.now(),
                "change_reason": "P16 disposable local seed",
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
            code="P16-PYTHON-256M",
            defaults={
                "name": "P16 Python 工作区规格",
                "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
                "status": ResourceProfile.Status.ACTIVE,
                "cpu_millicores": 500,
                "memory_mb": 256,
                "disk_gb": 2,
                "network_mode": ResourceProfile.NetworkMode.DENY_ALL,
                "activated_at": timezone.now(),
                "change_reason": "P16 disposable local seed",
            },
        )
        ResourceProfile.objects.filter(pk=profile.pk).update(
            status=ResourceProfile.Status.ACTIVE, retired_at=None
        )
        profile.refresh_from_db()
        return profile

    @staticmethod
    def _asset(
        version: TemplateVersion,
        *,
        purpose: str,
        name: str,
        media_type: str,
        content: bytes,
    ) -> ObjectAsset:
        existing = ObjectAsset.objects.filter(
            owner_type="TEMPLATE_VERSION", owner_ref=version.public_id, purpose=purpose
        ).first()
        if existing is not None and existing.digest_sha256 == hashlib.sha256(content).hexdigest():
            if existing.scan_status != ObjectAsset.ScanStatus.CLEAN:
                existing = set_scan_result(
                    asset_id=existing.pk,
                    expected_version=existing.row_version,
                    scan_status=ObjectAsset.ScanStatus.CLEAN,
                )
            return existing
        key = f"template-assets/p16/{version.public_id}/{purpose.casefold()}/{name}"
        stored = object_storage().put_stream(
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            stream=io.BytesIO(content),
            media_type=media_type,
        )
        asset = register_asset(
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            object_version=stored.version_id,
            digest_sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            owner_type="TEMPLATE_VERSION",
            owner_ref=version.public_id,
            purpose=purpose,
            media_type=media_type,
            original_name=name,
        )
        return set_scan_result(
            asset_id=asset.pk,
            expected_version=asset.row_version,
            scan_status=ObjectAsset.ScanStatus.CLEAN,
        )


def request_precheck_for_seed(
    version: TemplateVersion, course_id: str, teacher: User, context: ActorContext
) -> TemplatePrecheckRun:
    from apps.labtemplates.services import request_precheck

    return request_precheck(
        course_id=course_id,
        version_id=version.public_id,
        actor=teacher,
        expected_version=version.row_version,
        context=context,
    )
