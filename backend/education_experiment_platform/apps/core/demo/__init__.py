"""Demo dataset builder entrypoint (``manage.py seed_demo_full``)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from apps.governance.models import ResourceProfile

from . import assistants, catalog, identity, labs, lifecycle, observe
from .config import BuildContext, context_for


def build_demo_dataset(ctx: BuildContext) -> dict[str, Any]:
    """Generate the full demo dataset; returns entity counts for the CLI summary."""

    counts: Counter[str] = Counter()

    admin = identity.ensure_platform_admin(ctx, counts)
    teachers = identity.ensure_teachers(ctx, admin, counts)
    students = identity.ensure_students(ctx, counts)
    identity.seed_identity_verifications(ctx, admin, students, counts)

    catalog.ensure_academic_terms(ctx, counts)
    adapter = catalog.ensure_runtime_catalog(ctx, admin, counts)
    courses = catalog.build_demo_courses(ctx, teachers, counts)
    catalog.build_course_content(ctx, courses, students, counts)
    images = {
        course.code: catalog.ensure_demo_image(ctx, admin, index, counts)
        for index, course in enumerate(courses)
    }
    catalog.build_roster(ctx, courses, teachers, students, counts)
    catalog.seed_course_scoped_governance(ctx, admin, courses, counts)

    template_vers = labs.build_templates(
        ctx, adapter, profile_resource(), images, courses, counts
    )
    rubric_vers = labs.build_rubrics(ctx, courses, counts)
    publications = labs.build_publications(ctx, courses, template_vers, rubric_vers, counts)
    task_statuses = lifecycle.run_task_flows(ctx, admin, publications, counts)

    assistants.build_assistant_stack(ctx, courses, students, counts)
    observe.populate_notifications(ctx, counts)
    observe.rebuild_analytics(ctx, courses, counts)

    gateway_accounts = {
        "admin": identity.admin_username(),
        "teachers": [teacher.username for teacher in teachers],
        "students": [student.username for student in students[:3]],
    }

    return {
        "entities": dict(counts),
        "task_statuses": task_statuses,
        "accounts": gateway_accounts,
        "students": len(students),
        "courses": [course.code for course in courses],
        "publications": len(publications),
    }


def profile_resource() -> ResourceProfile:
    from .catalog import DEMO_PROFILE_CODE

    return ResourceProfile.objects.get(code=DEMO_PROFILE_CODE)


__all__ = ["build_demo_dataset", "context_for"]
