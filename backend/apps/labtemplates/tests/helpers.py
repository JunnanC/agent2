from django.utils import timezone

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.courses.tests.helpers import create_draft_course, create_teacher
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter

from ..models import Template, TemplateVersion
from ..services import create_template, create_version, replace_rules


def context(actor: User, trace: str = "p") -> ActorContext:
    return ActorContext(actor.public_id, "TEACHING", trace * 32)


def create_resources(
    owner: User, *, suffix: str = "p05"
) -> tuple[RuntimeAdapter, ImageAsset, ResourceProfile]:
    adapter = RuntimeAdapter.objects.create(
        code=f"runtime-{suffix}",
        name="P05 Runtime",
        runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
        driver=RuntimeAdapter.Driver.DOCKER_SWARM,
        status=RuntimeAdapter.Status.ENABLED,
        health_status=RuntimeAdapter.HealthStatus.HEALTHY,
        change_reason="test",
    )
    image = ImageAsset.objects.create(
        registry="registry.example.edu",
        repository=f"labs/{suffix}",
        digest="sha256:" + "a" * 64,
        scan_status=ImageAsset.ScanStatus.CLEAN,
        approval_status=ImageAsset.ApprovalStatus.APPROVED,
        risk_level=ImageAsset.RiskLevel.LOW,
        approved_by=owner,
        approved_at=timezone.now(),
        change_reason="test",
    )
    profile = ResourceProfile.objects.create(
        code=f"profile-{suffix}",
        name="P05 Profile",
        runtime_type=RuntimeAdapter.RuntimeType.CONTAINER,
        status=ResourceProfile.Status.ACTIVE,
        cpu_millicores=2000,
        memory_mb=4096,
        cpu_request_millicores=2000,
        cpu_limit_millicores=2000,
        memory_request_mb=4096,
        memory_limit_mb=4096,
        disk_gb=20,
        network_mode=ResourceProfile.NetworkMode.DENY_ALL,
        activated_at=timezone.now(),
        change_reason="test",
    )
    return adapter, image, profile


def create_template_version(
    *, suffix: str = "p05"
) -> tuple[User, Course, Template, TemplateVersion]:
    owner = create_teacher(suffix=f"{suffix}-owner")
    course = create_draft_course(owner, code=f"COURSE-{suffix.upper()}")
    adapter, image, profile = create_resources(owner, suffix=suffix)
    template = create_template(
        course_id=course.public_id,
        actor=owner,
        name="Container Lab",
        category="systems",
        description="P05 test template",
        context=context(owner),
    )
    version = create_version(
        course_id=course.public_id,
        template_id=template.public_id,
        actor=owner,
        data={
            "runtime_type": "CONTAINER",
            "runtime_adapter_id": adapter.public_id,
            "image_id": image.public_id,
            "resource_profile_id": profile.public_id,
            "dependencies": [{"name": "pytest", "version": "8"}],
            "network_policy": {"mode": "DENY_ALL", "privileged": False},
            "workspace_capabilities": {
                "require_gateway": True,
                "webide": True,
                "notebook": True,
                "terminal": True,
                "preview": True,
                "snapshot": True,
                "checkpoint": True,
            },
            "material_version_ids": [],
            "report_policy": {"required": True},
            "review_policy": {"mode": "MANUAL_WITH_AUTO_CHECK"},
            "retention_days": 30,
        },
        context=context(owner),
    )
    tests_asset = ObjectAsset.objects.create(
        public_id=new_ulid(),
        bucket="test-assets",
        object_key=f"template-tests/{version.public_id}/tests.json",
        object_version="tests-v1",
        digest_sha256="b" * 64,
        size_bytes=2,
        media_type="application/json",
        original_name="tests.json",
        owner_type="TEMPLATE_VERSION",
        owner_ref=version.public_id,
        purpose="TESTS",
        scan_status=ObjectAsset.ScanStatus.CLEAN,
        status=ObjectAsset.Status.ACTIVE,
    )
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
    return owner, course, template, version


def add_valid_rule(*, owner: User, course: Course, version: TemplateVersion) -> TemplateVersion:
    return replace_rules(
        course_id=course.public_id,
        version_id=version.public_id,
        actor=owner,
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
        context=context(owner),
    )
