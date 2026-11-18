from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.tests.helpers import create_user
from apps.courses.content_services import _import_identity


class StudentNumberImportTests(TestCase):
    def test_number_resolves_and_conflicting_columns_are_rejected(self):
        student = create_user(username="2026001")
        User.objects.filter(pk=student.pk).update(student_number="2026001")
        assert _import_identity({"student_number": " 2026001 "}) == (student.username, "")
        assert (
            _import_identity({"student_number": "2026001", "username": "missing"})[1]
            == "IDENTITY_MISMATCH"
        )
        assert _import_identity({"student_number": "missing"})[1] == "USER_NOT_FOUND"
        User.objects.filter(pk=student.pk).update(is_active=False, account_status="DISABLED")
        assert _import_identity({"student_number": "2026001"})[1] == "STUDENT_UNAVAILABLE"

    def test_provision_login_and_course_enrollment(self):
        from io import StringIO
        from unittest.mock import patch

        from apps.accounts.services import ActorContext as AccountContext
        from apps.accounts.services import authenticate_credentials
        from apps.accounts.student_imports import import_students
        from apps.courses.content_services import execute_import, precheck_import
        from apps.courses.models import Enrollment
        from apps.courses.services import ActorContext, publish_course
        from apps.courses.tests.helpers import create_draft_course, create_teacher

        owner = create_teacher()
        context = ActorContext(owner.public_id, "TEACHING", "a" * 32)
        course = create_draft_course(owner)
        course = publish_course(
            course_id=course.public_id,
            actor=owner,
            expected_version=course.row_version,
            context=context,
        )
        password = "Student-2026!abc"
        with patch("apps.accounts.services.enqueue_relay_after_commit"):
            rows = import_students(
                csv_payload="student_number,email,display_name,password\n"
                f"2026999,student@example.edu,Student,{password}\n",
                context=AccountContext(owner.public_id, "PLATFORM", "a" * 32),
            )
        assert rows[0]["status"] == "CREATED"
        student = authenticate_credentials("2026999", password)
        job = precheck_import(
            course_id=course.public_id,
            actor=owner,
            rows=StringIO("student_number\n2026999\n"),
            filename="roster.csv",
            context=context,
        )
        assert job.summary["valid"] == 1
        execute_import(job_id=job.public_id, actor=owner, context=context)
        assert job.items.get().status == "SUCCEEDED"
        assert Enrollment.objects.filter(course=course, student=student).exists()
