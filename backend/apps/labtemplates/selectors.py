from typing import Any

from django.db.models import Count, QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.ports import published_material_versions
from apps.courses.selectors import require_course_capability, visible_course
from apps.governance.models import ImageAsset
from apps.governance.ports import template_resource_options

from .legacy import LegacyTemplateAdapter
from .models import Template, TemplatePrecheckRun, TemplateVersion


def teaching_course(*, actor: User, course_id: str, capability: str) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(course=course, actor=actor, capability=capability)
    return course


def templates_for_course(*, actor: User, course_id: str) -> QuerySet[Template]:
    course = teaching_course(
        actor=actor, course_id=course_id, capability=CourseStaffGrant.Capability.MANAGE_TEMPLATE
    )
    return (
        Template.objects.filter(course=course)
        .exclude(status=Template.Status.WITHDRAWN)
        .select_related("current_version")
        .order_by("name")
    )


def template_for_course(*, actor: User, course_id: str, template_id: str) -> Template:
    course = teaching_course(
        actor=actor, course_id=course_id, capability=CourseStaffGrant.Capability.MANAGE_TEMPLATE
    )
    try:
        return (
            Template.objects.exclude(status=Template.Status.WITHDRAWN)
            .select_related("course", "current_version")
            .get(public_id=template_id, course=course)
        )
    except Template.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def version_for_course(*, actor: User, course_id: str, version_id: str) -> TemplateVersion:
    course = teaching_course(
        actor=actor, course_id=course_id, capability=CourseStaffGrant.Capability.MANAGE_TEMPLATE
    )
    try:
        return (
            TemplateVersion.objects.select_related(
                "template__course",
                "runtime_adapter",
                "image",
                "resource_profile",
                "manual_asset",
                "starter_asset",
                "report_template_asset",
            )
            .prefetch_related("auto_check_rules")
            .get(public_id=version_id, template__course=course)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def template_content_for_course(
    *, actor: User, course_id: str, version_id: str
) -> LegacyTemplateAdapter:
    return LegacyTemplateAdapter.from_version(
        version_for_course(actor=actor, course_id=course_id, version_id=version_id)
    )


def options_for_course(*, actor: User, course_id: str) -> dict[str, Any]:
    course = teaching_course(
        actor=actor, course_id=course_id, capability=CourseStaffGrant.Capability.MANAGE_TEMPLATE
    )
    result: dict[str, Any] = template_resource_options()
    result["materials"] = [
        {
            "public_id": item.public_id,
            "title": item.material.title,
            "version_no": item.version_no,
            "digest_sha256": item.digest_sha256,
        }
        for item in published_material_versions(course=course)
    ]
    return result


def platform_precheck_summary() -> dict[str, Any]:
    precheck_counts = {
        item["status"]: item["count"]
        for item in TemplatePrecheckRun.objects.values("status").annotate(count=Count("id"))
    }
    image_counts = {
        item["approval_status"]: item["count"]
        for item in ImageAsset.objects.values("approval_status").annotate(count=Count("id"))
    }
    failures = (
        TemplatePrecheckRun.objects.filter(status=TemplatePrecheckRun.Status.FAILED)
        .select_related("template_version__template__course")
        .order_by("-created_at")[:20]
    )
    return {
        "precheck_counts": precheck_counts,
        "image_counts": image_counts,
        "recent_failures": [
            {
                "run_id": item.public_id,
                "course_id": item.template_version.template.course.public_id,
                "template_version_id": item.template_version.public_id,
                "error_code": item.error_code,
                "current_stage": item.current_stage,
                "retryable": item.retryable,
                "trace_id": item.trace_id,
                "created_at": item.created_at,
            }
            for item in failures
        ],
    }
