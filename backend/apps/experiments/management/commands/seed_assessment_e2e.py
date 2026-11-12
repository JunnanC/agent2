"""Create repeatable assessment fixtures through the real publication/precheck services."""

import json
import os
import re
import secrets
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.courses.models import Course, Enrollment
from apps.courses.services import ActorContext
from apps.governance.models import ImageAsset, ResourceProfile, RuntimeAdapter
from apps.labtemplates.assessment_assets import store_question_tests
from apps.labtemplates.models import Template, TemplateChapter, TemplateVersion
from apps.labtemplates.questions import ENTRYPOINTS
from apps.labtemplates.services import (
    create_chapter,
    create_task,
    create_template,
    create_version,
    execute_precheck,
    publish_version,
    request_precheck,
)
from apps.reviews.models import Rubric
from apps.reviews.services import create_rubric, create_rubric_version, publish_rubric_version

from ...models import TaskPublication
from ...services import create_publication, publish_publication


class Command(BaseCommand):
    help = "Seed CHOICE, PROGRAMMING and MIXED assessments in an existing disposable course."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--course-id", required=True)
        parser.add_argument("--run-id", default="assessment-e2e")
        parser.add_argument(
            "--kind", choices=("CHOICE", "PROGRAMMING", "MIXED", "ALL"), default="ALL"
        )
        parser.add_argument("--runtime-id")
        parser.add_argument("--image-id")
        parser.add_argument("--profile-id")

    def handle(self, *args: Any, **options: Any) -> None:
        if os.getenv("APP_ENV") not in {"local", "integration", "test"}:
            raise CommandError(
                "Set APP_ENV=local|integration|test; never seed a production database"
            )
        run_id = options["run_id"]
        if not re.fullmatch(r"[A-Za-z0-9-]{1,32}", run_id):
            raise CommandError("run-id must contain 1-32 letters, numbers or hyphens")
        try:
            course = Course.objects.select_related("owner").get(
                public_id=options["course_id"],
                status="PUBLISHED",
            )
        except Course.DoesNotExist as exc:
            raise CommandError("A published disposable course is required") from exc
        if not Enrollment.objects.filter(course=course, status="ACTIVE").exists():
            raise CommandError("Enroll at least one student before seeding")
        kinds = (
            ("CHOICE", "PROGRAMMING", "MIXED") if options["kind"] == "ALL" else (options["kind"],)
        )
        runtime_data = {}
        if any(kind != "CHOICE" for kind in kinds):
            if settings.LOCAL_RUNTIME_MODE != "REAL":
                raise CommandError("Programming fixtures require LOCAL_RUNTIME_MODE=REAL")
            try:
                runtime = RuntimeAdapter.objects.get(
                    public_id=options["runtime_id"],
                    driver="DOCKER_LOCAL",
                    status="ENABLED",
                )
                image = ImageAsset.objects.get(
                    public_id=options["image_id"],
                    scan_status="CLEAN",
                    approval_status="APPROVED",
                )
                profile = ResourceProfile.objects.get(
                    public_id=options["profile_id"], status="ACTIVE"
                )
            except (
                RuntimeAdapter.DoesNotExist,
                ImageAsset.DoesNotExist,
                ResourceProfile.DoesNotExist,
            ) as exc:
                raise CommandError(
                    "Provide enabled runtime, approved stdio image and active profile IDs"
                ) from exc
            runtime_data = {
                "runtime_type": "CONTAINER",
                "runtime_adapter_id": runtime.public_id,
                "image_id": image.public_id,
                "resource_profile_id": profile.public_id,
            }
        actor = course.owner
        context = ActorContext(actor.public_id, "TEACHING", secrets.token_hex(16))
        result = []
        for kind in kinds:
            name = f"{run_id}-{kind.lower()}"
            publication = TaskPublication.objects.filter(course=course, title=name).first()
            if publication is None:
                template = Template.objects.filter(course=course, name=name).first()
                if template is None:
                    template = create_template(
                        course_id=course.public_id,
                        actor=actor,
                        name=name,
                        category="算法验收",
                        description="Disposable assessment fixture",
                        context=context,
                    )
                version = template.versions.order_by("-version_no").first()
                if version is None:
                    version = create_version(
                        course_id=course.public_id,
                        template_id=template.public_id,
                        actor=actor,
                        data=runtime_data if kind != "CHOICE" else {},
                        context=context,
                    )
                chapter = version.chapters.first()
                if chapter is None:
                    chapter = create_chapter(
                        course_id=course.public_id,
                        version_id=version.public_id,
                        actor=actor,
                        expected_version=version.row_version,
                        data={"title": "算法基础"},
                        context=context,
                    )
                if version.status in {"DRAFT", "PRECHECK_FAILED"}:
                    self._questions(course, version, chapter, kind, context)
                    version.refresh_from_db()
                    run = request_precheck(
                        course_id=course.public_id,
                        version_id=version.public_id,
                        actor=actor,
                        expected_version=version.row_version,
                        context=context,
                    )
                    run = execute_precheck(run_id=run.public_id)
                    if run.status != "PASSED":
                        raise CommandError(f"Reference precheck failed: {run.error_code}")
                    version.refresh_from_db()
                if version.status == "PRECHECK_PASSED":
                    version = publish_version(
                        course_id=course.public_id,
                        version_id=version.public_id,
                        actor=actor,
                        expected_version=version.row_version,
                        context=context,
                    )
                if version.status != "PUBLISHED":
                    raise CommandError(
                        "Fixture version is not published; resolve its precheck first"
                    )
                rubric = self._rubric(course, name, context) if kind == "MIXED" else None
                now = timezone.now()
                publication = create_publication(
                    course_id=course.public_id,
                    actor=actor,
                    context=context,
                    data={
                        "template_version_id": version.public_id,
                        "rubric_version_id": rubric.public_id if rubric else None,
                        "title": name,
                        "audience_mode": "ALL_ACTIVE",
                        "late_enrollment_policy": "DO_NOT_ASSIGN",
                        "window_start": now - timezone.timedelta(minutes=5),
                        "window_end": now + timezone.timedelta(days=7),
                        "report_required": kind == "MIXED",
                        "review_mode": "MANUAL_WITH_AUTO_CHECK",
                    },
                )
            if publication.status == "DRAFT":
                publication, _ = publish_publication(
                    course_id=course.public_id,
                    publication_id=publication.public_id,
                    actor=actor,
                    expected_version=publication.row_version,
                    selected_ids=[],
                    context=context,
                )
            if publication.status != "PUBLISHED":
                raise CommandError(
                    "Existing fixture was closed/withdrawn; use a different --run-id"
                )
            result.append({
                "kind": kind,
                "title": name,
                "publication_id": publication.public_id,
                "template_id": publication.template_version.template.public_id,
                "version_id": publication.template_version.public_id,
                "tasks": [
                    {"task_id": task.public_id, "student": task.student.email}
                    for task in publication.tasks.select_related("student")
                ],
            })
        self.stdout.write(
            json.dumps({"course_id": course.public_id, "fixtures": result}, ensure_ascii=False)
        )

    def _questions(
        self,
        course: Course,
        version: TemplateVersion,
        chapter: TemplateChapter,
        kind: str,
        context: ActorContext,
    ) -> None:
        def add(title: str, data: dict[str, Any]) -> None:
            if chapter.tasks.filter(title=title, active=True).exists():
                return
            version.refresh_from_db()
            create_task(
                course_id=course.public_id,
                chapter_id=chapter.public_id,
                actor=course.owner,
                expected_version=version.row_version,
                data={"title": title, **data},
                context=context,
            )

        if kind != "PROGRAMMING":
            options = {
                "options": [{"id": "a", "text": "先进先出"}, {"id": "b", "text": "后进先出"}]
            }
            add(
                "栈的访问顺序",
                {
                    "task_type": "SINGLE_CHOICE",
                    "description": "栈的访问顺序是什么？",
                    "max_score": "5",
                    "question_spec": options,
                    "marking_spec": {
                        "correct_option_ids": ["b"],
                        "explanation": "栈遵循后进先出。",
                    },
                },
            )
            add(
                "线性结构",
                {
                    "task_type": "MULTIPLE_CHOICE",
                    "description": "选择线性结构。",
                    "max_score": "5",
                    "question_spec": {
                        "options": [
                            {"id": "array", "text": "数组"},
                            {"id": "list", "text": "链表"},
                            {"id": "tree", "text": "树"},
                        ]
                    },
                    "marking_spec": {
                        "correct_option_ids": ["array", "list"],
                        "explanation": "数组与链表。",
                    },
                },
            )
        if kind == "CHOICE" or chapter.tasks.filter(task_type="PROGRAMMING", active=True).exists():
            return
        version.refresh_from_db()
        stored = store_question_tests(
            actor=course.owner,
            course_id=course.public_id,
            version_id=version.public_id,
            expected_version=version.row_version,
            context=context,
            groups=[
                {"id": "basic", "cases": [{"input": "3 5\n", "output": "8\n"}]},
                {"id": "edge", "cases": [{"input": "-2 9\n", "output": "7\n"}]},
            ],
            scores=[{"id": "basic", "score": "7"}, {"id": "edge", "score": "3"}],
        )
        add(
            "整数求和",
            {
                "task_type": "PROGRAMMING",
                "description": "读取两个整数，输出它们的和。",
                "max_score": "10",
                "question_spec": {
                    "allowed_languages": list(ENTRYPOINTS),
                    "samples": [{"input": "3 5\n", "output": "8\n"}],
                    "starter_files": {
                        language: {entry: ""} for language, entry in ENTRYPOINTS.items()
                    },
                    "limits": {
                        language: {
                            "timeout_seconds": 3,
                            "memory_mb": 512 if language == "java" else 256,
                        }
                        for language in ENTRYPOINTS
                    },
                },
                "marking_spec": {
                    "tests_asset_id": stored["asset_id"],
                    "groups": [{"id": "basic", "score": "7"}, {"id": "edge", "score": "3"}],
                    "reference_solutions": {
                        "python": {"main.py": "a,b=map(int,input().split());print(a+b)\n"}
                    },
                },
            },
        )

    def _rubric(self, course: Course, name: str, context: ActorContext) -> Any:
        rubric = Rubric.objects.filter(course=course, name=name).first()
        if rubric is None:
            rubric = create_rubric(
                course_id=course.public_id,
                actor=course.owner,
                name=name,
                description="实验总报告评分",
                context=context,
            )
        version = rubric.versions.first()
        if version is None:
            version = create_rubric_version(
                course_id=course.public_id,
                rubric_id=rubric.public_id,
                actor=course.owner,
                title="实验报告",
                description="",
                total_score=Decimal("10"),
                criteria=[
                    {
                        "position": 1,
                        "title": "分析与结论",
                        "max_score": "10",
                        "weight_basis_points": 10000,
                    }
                ],
                context=context,
            )
        if version.status != "PUBLISHED":
            version = publish_rubric_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=course.owner,
                expected_version=version.row_version,
                context=context,
            )
        return version
