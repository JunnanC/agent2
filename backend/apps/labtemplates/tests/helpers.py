from django.utils import timezone

from apps.accounts.models import User
from apps.courses.models import Course
from apps.courses.services import ActorContext
from apps.courses.tests.helpers import create_draft_course, create_teacher
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter

from ..models import Template, TemplateVersion
from ..services import create_template, create_version


def context(actor: User, trace: str = "p") -> ActorContext:
    return ActorContext(actor.public_id, "TEACHING", trace * 32)


def create_resources(
    owner: User, *, suffix: str = "templates"
) -> tuple[RuntimeAdapter, ImageAsset, ResourceProfile]:
    adapter = RuntimeAdapter.objects.create(
        code=f"runtime-{suffix}",
        name="templates Runtime",
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
        name="templates Profile",
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
    *, suffix: str = "templates"
) -> tuple[User, Course, Template, TemplateVersion]:
    owner = create_teacher(suffix=f"{suffix}-owner")
    course = create_draft_course(owner, code=f"COURSE-{suffix.upper()}")
    adapter, image, profile = create_resources(owner, suffix=suffix)
    template = create_template(
        course_id=course.public_id,
        actor=owner,
        name="Container Lab",
        category="systems",
        description="templates test template",
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
            "material_version_ids": [],
            "report_policy": {"required": True},
            "review_policy": {"mode": "MANUAL_WITH_AUTO_CHECK"},
            "retention_days": 30,
        },
        context=context(owner),
    )
    return owner, course, template, version
