import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.courses.content_services import (
    change_chapter_status,
    change_material_version_status,
    create_chapter,
    create_material,
)
from apps.courses.models import Course
from apps.courses.services import ActorContext, apply_for_course, publish_course, review_enrollment


class Command(BaseCommand):
    help = "Create disposable course and course-content data for local browser verification."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("course E2E seed is restricted to disposable environments")
        teacher = User.objects.filter(email="teacher.integration@example.edu").first()
        student = User.objects.filter(email="student.integration@example.edu").first()
        if teacher is None or student is None:
            raise CommandError("Run seed_accounts_e2e first")
        course = Course.objects.filter(code="P03-DEMO-001").first()
        trace = secrets.token_hex(16)
        context = ActorContext(teacher.public_id, "TEACHING", trace)
        if course is None:
            from apps.courses.services import create_course

            course = create_course(
                actor=teacher,
                code="P03-DEMO-001",
                title="课程协作实践",
                summary="用于本地课程、内容和名册链路验收。",
                description="该课程仅用于可清理的本地集成验证。",
                visibility=Course.Visibility.PUBLIC,
                enrollment_mode=Course.EnrollmentMode.OPEN,
                capacity=30,
                enrollment_start=None,
                enrollment_end=None,
                teaching_start=None,
                teaching_end=None,
                context=context,
            )
            course = publish_course(
                course_id=course.public_id,
                actor=teacher,
                expected_version=course.row_version,
                context=context,
            )
        chapter = course.chapters.order_by("position").first()
        if chapter is None:
            chapter = create_chapter(
                course_id=course.public_id,
                actor=teacher,
                title="第一章：课程协作",
                summary="内容发布和选课验证章节。",
                position=1,
                context=context,
            )
            chapter = change_chapter_status(
                chapter_id=chapter.public_id,
                actor=teacher,
                expected_version=chapter.row_version,
                status="PUBLISHED",
                context=context,
            )
            material = create_material(
                course_id=course.public_id,
                actor=teacher,
                chapter_id=chapter.public_id,
                title="课程手册",
                kind="TEXT",
                text_content="这是课程协作的本地验证资料。",
                link_url="",
                asset_id=None,
                context=context,
            )
            change_material_version_status(
                version_id=material.current_version.public_id,
                actor=teacher,
                expected_version=material.current_version.row_version,
                status="PUBLISHED",
                context=context,
            )
        if not course.enrollments.filter(student=student, status="ACTIVE").exists():
            enrollment = course.enrollments.filter(student=student, status="PENDING").first()
            enrollment = enrollment or apply_for_course(
                course_id=course.public_id,
                student=student,
                application_message="Course E2E seed",
                context=ActorContext(student.public_id, "USER", trace),
            )
            review_enrollment(
                course_id=course.public_id, enrollment_id=enrollment.public_id,
                decision="APPROVE", note="Course E2E seed", actor=teacher,
                expected_version=enrollment.row_version, context=context,
            )
        self.stdout.write(self.style.SUCCESS(f"course E2E course ready: {course.public_id}"))
