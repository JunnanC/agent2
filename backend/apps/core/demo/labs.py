"""Demo templates, versions, auto-check rules, rubrics, publications, and tasks."""

from __future__ import annotations

import contextlib
from collections import Counter
from decimal import Decimal
from typing import Final

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import ActorContext
from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset
from apps.courses.models import Course
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.experiments.services import (
    close_publication,
    create_publication,
    execute_publication_assignment,
    publish_publication,
)
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter
from apps.labtemplates.models import (
    ExperimentImage,
    Template,
    TemplateChapter,
    TemplateTask,
    TemplateVersion,
)
from apps.labtemplates.services import (
    compute_spec_digest,
    create_template,
    create_version,
    replace_rules,
)
from apps.reviews.models import Rubric, RubricVersion
from apps.reviews.services import (
    create_rubric,
    create_rubric_version,
    publish_rubric_version,
)

from .banks import GRADINGS
from .catalog import demo_course_status
from .config import BuildContext, stable_digest

DEMO_TEMPLATE_NAME: Final[str] = "演示容器实验模板"
DEMO_RUBRIC_NAME: Final[str] = "演示评分量规"
TESTS_ASSET_BUCKET: Final[str] = "demo-assets"

DEMO_WORKSPACE_CAPABILITIES: Final[dict[str, bool]] = {
    "require_gateway": True,
    "webide": True,
    "terminal": True,
    "preview": True,
    "snapshot": True,
    "checkpoint": True,
}

AUTO_CHECK_RULE: Final[dict[str, object]] = {
    "position": 1,
    "checker_type": "PYTEST",
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
    "timeout_seconds": 60,
    "resource_limit": {"cpu_millicores": 1000, "memory_mb": 1024, "disk_gb": 2},
    "network_policy": {"mode": "DENY_ALL"},
    "display_policy": {"show_score": True},
    "failure_semantics": {"on_failure": "FAIL_CHECK"},
}


def build_templates(
    ctx: BuildContext,
    adapter: RuntimeAdapter,
    profile: ResourceProfile,
    images: dict[str, ImageAsset],
    courses: list[Course],
    counts: Counter[str],
) -> dict[str, TemplateVersion]:
    """Create one demo template version per course and hard-publish it.

    Publishing updates the status and digest directly (``.update(status=PUBLISHED, spec_digest=…)``)
    so the dataset never depends on a real Docker registry or runtime.
    """

    versions: dict[str, TemplateVersion] = {}
    for course in courses:
        owner = course.owner
        teaching = _teaching(ctx, owner)
        course.refresh_from_db()
        template = Template.objects.filter(course=course, name=DEMO_TEMPLATE_NAME).first()
        if template is None:
            template = create_template(
                course_id=course.public_id,
                actor=owner,
                name=DEMO_TEMPLATE_NAME,
                category="演示实验",
                description=f"{course.title} 的演示容器实验模板。",
                context=teaching,
            )
            counts["labtemplates.Template"] += 1
        version = template.versions.order_by("-version_no").first()
        if version is None:
            asset = images[course.code]
            version = create_version(
                course_id=course.public_id,
                template_id=template.public_id,
                actor=owner,
                data=_version_payload(adapter, asset, profile),
                context=teaching,
            )
            counts["labtemplates.TemplateVersion"] += 1
        version = _ensure_published_version(ctx, course, owner, version, teaching, counts)
        versions[course.code] = version
    return versions


def _version_payload(
    adapter: RuntimeAdapter,
    image: ImageAsset,
    profile: ResourceProfile,
) -> dict[str, object]:
    return {
        "runtime_type": RuntimeAdapter.RuntimeType.CONTAINER,
        "runtime_adapter_id": adapter.public_id,
        "image_id": image.public_id,
        "resource_profile_id": profile.public_id,
        "dependencies": [{"name": "pytest", "version": "8"}],
        "network_policy": {"mode": "DENY_ALL", "privileged": False},
        "workspace_capabilities": dict(DEMO_WORKSPACE_CAPABILITIES),
        "material_version_ids": [],
        "report_policy": {"required": True},
        "review_policy": {"mode": "MANUAL_WITH_AUTO_CHECK"},
        "retention_days": 30,
    }


def _reconcile_demo_capabilities(version: TemplateVersion, counts: Counter[str]) -> None:
    """幂等升级已存在的演示版本能力声明。

    旧种子的版本可能缺 terminal/preview 等键(真实运行时镜像具备这些能力);
    与运行适配器 seed 一样走原地升级:改变能力后同步刷新 spec_digest,
    让后续发布冻结的快照与模板保持一致。
    """

    caps = dict(version.workspace_capabilities or {})
    if caps == DEMO_WORKSPACE_CAPABILITIES:
        return
    TemplateVersion.objects.filter(pk=version.pk).update(
        workspace_capabilities=dict(DEMO_WORKSPACE_CAPABILITIES)
    )
    version.refresh_from_db()
    if version.spec_digest:
        TemplateVersion.objects.filter(pk=version.pk).update(
            spec_digest=compute_spec_digest(version)
        )
        version.refresh_from_db()
    counts["labs.VersionCapabilitiesReconciled"] += 1


def _ensure_published_version(
    ctx: BuildContext,
    course: Course,
    owner: User,
    version: TemplateVersion,
    teaching: ActorContext,
    counts: Counter[str],
) -> TemplateVersion:
    if version.status == TemplateVersion.Status.PUBLISHED:
        _reconcile_demo_capabilities(version, counts)
        return version
    tests_asset = _ensure_tests_asset(version, counts)
    if not version.execution_spec:
        TemplateVersion.objects.filter(pk=version.pk).update(
            execution_spec={
                "language": "python",
                "entrypoint": "main.py",
                "timeout_seconds": 10,
                "memory_mb": 256,
                "cpu_millicores": 500,
                "comparator": "token",
                "tests_asset": tests_asset.public_id,
                "network_mode": "DENY_ALL",
            }
        )
        version.refresh_from_db()
    if not version.auto_check_rules.filter(is_active=True).exists():
        replace_rules(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            rules=[AUTO_CHECK_RULE],
            context=teaching,
        )
        version.refresh_from_db()
    _ensure_template_content(ctx, owner, version, counts)
    digest = compute_spec_digest(version)
    TemplateVersion.objects.filter(pk=version.pk).update(
        status=TemplateVersion.Status.PUBLISHED,
        spec_digest=digest,
        published_by=owner,
        published_at=timezone.now(),
    )
    version.refresh_from_db()
    counts["labtemplates.TemplateVersionPublished"] += 1
    return version


def _ensure_template_content(
    ctx: BuildContext,
    owner: User,
    version: TemplateVersion,
    counts: Counter[str],
) -> None:
    """Seed a READY image plus one published chapter/task so publication passes."""

    image_exists = ExperimentImage.objects.filter(
        template_version=version, status=ExperimentImage.Status.READY
    ).exists()
    if image_exists and version.chapters.filter(
        status=TemplateChapter.Status.PUBLISHED
    ).exists():
        return
    version.refresh_from_db()
    if not image_exists:
        ExperimentImage.objects.create(
            template_version=version,
            source_type=ExperimentImage.SourceType.EXTERNAL_REFERENCE,
            registry=version.image.registry,
            repository=version.image.repository,
            requested_tag=version.image.display_tag or "demo",
            resolved_digest=version.image.digest,
            image_asset=version.image,
            status=ExperimentImage.Status.READY,
            scan_status=ExperimentImage.ScanStatus.CLEAN,
            trace_id=ctx.trace_id,
            created_by=owner,
        )
        counts["labtemplates.ExperimentImage"] += 1
    if not version.chapters.exists():
        chapter = TemplateChapter.objects.create(
            template_version=version,
            title="演示实验内容",
            description="在容器工作台完成演示算法任务并提交报告。",
            learning_objectives=["熟悉实验平台工作台", "完成一次自动检查"],
            sort_order=1,
            status=TemplateChapter.Status.PUBLISHED,
            resource_profile=version.resource_profile,
        )
        counts["labtemplates.TemplateChapter"] += 1
        TemplateTask.objects.create(
            chapter=chapter,
            title="演示实验任务",
            description="演示任务：容器工作台内完成算法练习。",
            instructions="按指导说明编辑代码、保存快照并运行自动检查。",
            task_type="ALGORITHM",
            sort_order=1,
            status=TemplateTask.Status.PUBLISHED,
        )
        counts["labtemplates.TemplateTask"] += 1


def _ensure_tests_asset(version: TemplateVersion, counts: Counter[str]) -> ObjectAsset:
    asset = ObjectAsset.objects.filter(
        bucket=TESTS_ASSET_BUCKET,
        object_key=f"template-tests/{version.public_id}/tests.json",
    ).first()
    if asset is not None:
        return asset
    payload = b"{}"
    created = ObjectAsset.objects.create(
        public_id=new_ulid(),
        bucket=TESTS_ASSET_BUCKET,
        object_key=f"template-tests/{version.public_id}/tests.json",
        object_version="demo-v1",
        digest_sha256=stable_digest("demo-tests", version.public_id),
        size_bytes=len(payload),
        media_type="application/json",
        original_name="tests.json",
        owner_type="TEMPLATE_VERSION",
        owner_ref=version.public_id,
        purpose="TESTS",
        scan_status=ObjectAsset.ScanStatus.CLEAN,
        status=ObjectAsset.Status.ACTIVE,
    )
    counts["core.ObjectAsset"] += 1
    return created


def build_rubrics(
    ctx: BuildContext,
    courses: list[Course],
    counts: Counter[str],
) -> dict[str, RubricVersion]:
    versions: dict[str, RubricVersion] = {}
    for course in courses:
        owner = course.owner
        teaching = _teaching(ctx, owner)
        rubric = Rubric.objects.filter(course=course, name=DEMO_RUBRIC_NAME).first()
        if rubric is None:
            rubric = create_rubric(
                course_id=course.public_id,
                actor=owner,
                name=DEMO_RUBRIC_NAME,
                description="演示数据集人工评阅量规。",
                context=teaching,
            )
            counts["reviews.Rubric"] += 1
        version = rubric.versions.order_by("-version_no").first()
        if version is None:
            version = create_rubric_version(
                course_id=course.public_id,
                rubric_id=rubric.public_id,
                actor=owner,
                title="演示评阅版本 v1",
                description="",
                total_score=Decimal("100.00"),
                criteria=_criteria_payload(),
                context=teaching,
            )
            counts["reviews.RubricVersion"] += 1
        if version.status == RubricVersion.Status.DRAFT:
            version = publish_rubric_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=version.row_version,
                context=teaching,
            )
            counts["reviews.RubricVersionPublished"] += 1
        versions[course.code] = version
    return versions


def _criteria_payload() -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for position, (title, guidance, weight) in enumerate(GRADINGS, start=1):
        payload.append(
            {
                "position": position,
                "title": title,
                "description": "",
                "guidance": guidance,
                "max_score": str(Decimal(weight)),
                "weight_basis_points": weight * 100,
            }
        )
    return payload


def build_publications(
    ctx: BuildContext,
    courses: list[Course],
    template_versions: dict[str, TemplateVersion],
    rubric_versions: dict[str, RubricVersion],
    counts: Counter[str],
) -> list[TaskPublication]:
    publications: list[TaskPublication] = []
    total = len(courses)
    for index, course in enumerate(courses):
        course.refresh_from_db()
        if (
            demo_course_status(index, total, ctx) != Course.Status.PUBLISHED
            or course.status != Course.Status.PUBLISHED
        ):
            continue
        owner = course.owner
        teaching = _teaching(ctx, owner)
        extra = bool(ctx.config.scale != "small" and index == 0)
        publications.extend(
            _build_course_publications(
                ctx,
                course,
                owner,
                teaching,
                template_versions,
                rubric_versions,
                extra,
                counts,
            )
        )
    return publications


def _build_course_publications(
    ctx: BuildContext,
    course: Course,
    owner: User,
    teaching: ActorContext,
    template_versions: dict[str, TemplateVersion],
    rubric_versions: dict[str, RubricVersion],
    extra: bool,
    counts: Counter[str],
) -> list[TaskPublication]:
    built: list[TaskPublication] = []
    for offset, suffix in enumerate(("一", "二")):
        if offset == 1 and not extra:
            continue
        title = f"演示实验{suffix}"
        publication = TaskPublication.objects.filter(course=course, title=title).first()
        if publication is None:
            now = timezone.now()
            publication = create_publication(
                course_id=course.public_id,
                actor=owner,
                data={
                    "template_version_id": template_versions[course.code].public_id,
                    "rubric_version_id": rubric_versions[course.code].public_id,
                    "title": title,
                    "description": "演示数据集发布：任务窗口与评阅全流程。",
                    "audience_mode": TaskPublication.AudienceMode.ALL_ACTIVE,
                    "late_enrollment_policy": (
                        TaskPublication.LateEnrollmentPolicy.ASSIGN_UNTIL_DEADLINE
                    ),
                    "window_start": now - timezone.timedelta(hours=1),
                    "window_end": now + timezone.timedelta(days=7),
                    "assignment_deadline": now + timezone.timedelta(days=5),
                    "report_required": True,
                    "review_mode": TaskPublication.ReviewMode.MANUAL_WITH_AUTO_CHECK,
                    "prerequisites": [],
                },
                context=teaching,
            )
            counts["experiments.TaskPublication"] += 1
        if publication.status == TaskPublication.Status.DRAFT and offset == 0:
            publication, _ = publish_publication(
                course_id=course.public_id,
                publication_id=publication.public_id,
                actor=owner,
                expected_version=publication.row_version,
                selected_ids=[],
                context=teaching,
            )
            counts["experiments.TaskPublicationPublished"] += 1
        publication.refresh_from_db()
        if publication.status == TaskPublication.Status.PUBLISHED:
            _ensure_tasks_assigned(ctx, publication, counts)
            built.append(publication)
    return built


def close_one_publication(
    ctx: BuildContext,
    publications: list[TaskPublication],
    counts: Counter[str],
) -> None:
    target = next(
        (item for item in publications if item.status == TaskPublication.Status.PUBLISHED),
        None,
    )
    if target is None:
        return
    if ExperimentTask.objects.filter(publication=target).exists():
        return
    owner = target.course.owner
    teaching = _teaching(ctx, owner)
    with contextlib.suppress(Exception):
        close_publication(
            course_id=target.course.public_id,
            publication_id=target.public_id,
            actor=owner,
            expected_version=target.row_version,
            context=teaching,
        )
        counts["experiments.TaskPublicationClosed"] += 1


def _teaching(ctx: BuildContext, owner: User) -> ActorContext:
    return ActorContext(owner.public_id, "TEACHING", ctx.trace_id)


def _ensure_tasks_assigned(
    ctx: BuildContext,
    publication: TaskPublication,
    counts: Counter[str],
) -> None:
    task_total = ExperimentTask.objects.filter(publication=publication).count()
    audience_total = publication.audience.count()
    if audience_total == 0 or task_total >= audience_total:
        return
    before = task_total
    with contextlib.suppress(Exception):
        teaching = _teaching(ctx, publication.course.owner)
        execute_publication_assignment(
            publication_id=publication.public_id,
            context=teaching,
        )
        counts["experiments.ExperimentTask"] += (
            ExperimentTask.objects.filter(publication=publication).count() - before
        )

