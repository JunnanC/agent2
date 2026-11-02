from io import BytesIO

from django.test import TestCase
from openpyxl import Workbook

from apps.accounts.tests.helpers import create_user

from ..models import (
    AdministrativeClass,
    AdministrativeClassMembership,
    Course,
    CourseSchedule,
    Enrollment,
    StudentScheduleEntry,
    TimetableImportJob,
)
from ..services import ActorContext, current_academic_term
from ..timetable_services import (
    assign_administrative_class_member,
    create_administrative_class,
    create_timetable_import_job,
    execute_timetable_import,
    start_timetable_import,
    update_timetable_import_mapping,
)
from .helpers import create_teacher


def workbook_bytes(headers: list[str], values: list[str]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    sheet.append(values)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


class TimetableImportTests(TestCase):
    def setUp(self) -> None:
        self.teacher = create_teacher(suffix="timetable-teacher")
        self.student = create_user(
            email="timetable-student@example.edu", username="timetable-student"
        )
        self.term = current_academic_term()

    def _job(
        self, *, kind: str, filename: str, headers: list[str], values: list[str]
    ) -> TimetableImportJob:
        return create_timetable_import_job(
            actor=self.teacher if kind == TimetableImportJob.Kind.TEACHER else self.student,
            kind=kind,
            filename=filename,
            content=workbook_bytes(headers, values),
        )

    def test_student_import_maps_local_headers_and_does_not_enroll_student(self) -> None:
        job = self._job(
            kind=TimetableImportJob.Kind.STUDENT,
            filename="student.xlsx",
            headers=["課程", "周几", "节数", "周次", "地点"],
            values=["数据结构", "周二", "3-4", "1-16周", "A-101"],
        )
        mapping = {
            "course_title": "課程",
            "weekday": "周几",
            "start_period": "节数",
            "end_period": "节数",
            "week_start": "周次",
            "week_end": "周次",
            "classroom": "地点",
        }
        job = update_timetable_import_mapping(
            job_id=job.public_id,
            actor=self.student,
            kind=job.kind,
            mapping=mapping,
        )
        self.assertEqual(job.status, TimetableImportJob.Status.READY)
        self.assertEqual(job.row_errors, [])

        job = start_timetable_import(job_id=job.public_id, actor=self.student, kind=job.kind)
        context = ActorContext(self.student.public_id, "USER", "c" * 32)
        completed = execute_timetable_import(
            job_id=job.public_id, actor=self.student, kind=job.kind, context=context
        )

        entry = StudentScheduleEntry.objects.get(student=self.student, term=self.term)
        self.assertEqual(completed.status, TimetableImportJob.Status.COMPLETED)
        self.assertEqual(
            (entry.course_title, entry.weekday, entry.start_period, entry.end_period),
            ("数据结构", 2, 3, 4),
        )
        self.assertEqual((entry.week_start, entry.week_end, entry.classroom), (1, 16, "A-101"))
        self.assertFalse(Enrollment.objects.filter(student=self.student).exists())

    def test_teacher_import_creates_course_and_schedule_and_replays_idempotently(self) -> None:
        job = self._job(
            kind=TimetableImportJob.Kind.TEACHER,
            filename="teacher.xlsx",
            headers=["编号", "课程名", "星期", "节次"],
            values=["BIO-204", "生物实验", "星期五", "5-6"],
        )
        job = update_timetable_import_mapping(
            job_id=job.public_id,
            actor=self.teacher,
            kind=job.kind,
            mapping={
                "course_code": "编号",
                "course_title": "课程名",
                "weekday": "星期",
                "start_period": "节次",
                "end_period": "节次",
            },
        )
        job = start_timetable_import(job_id=job.public_id, actor=self.teacher, kind=job.kind)
        context = ActorContext(self.teacher.public_id, "TEACHING", "d" * 32)
        completed = execute_timetable_import(
            job_id=job.public_id, actor=self.teacher, kind=job.kind, context=context
        )
        replay = execute_timetable_import(
            job_id=job.public_id, actor=self.teacher, kind=job.kind, context=context
        )

        course = Course.objects.get(code="BIO-204")
        schedule = CourseSchedule.objects.get(course=course)
        self.assertEqual(course.owner, self.teacher)
        self.assertEqual(course.term, self.term)
        self.assertEqual((schedule.weekday, schedule.start_period, schedule.end_period), (5, 5, 6))
        self.assertEqual(completed.public_id, replay.public_id)
        self.assertEqual(CourseSchedule.objects.filter(course=course).count(), 1)
        self.assertFalse(Enrollment.objects.filter(course=course).exists())

    def test_invalid_mapped_row_is_reported_and_blocks_import(self) -> None:
        job = self._job(
            kind=TimetableImportJob.Kind.STUDENT,
            filename="invalid.xlsx",
            headers=["课程", "星期", "开始", "结束"],
            values=["课程 A", "星期八", "1", "2"],
        )
        job = update_timetable_import_mapping(
            job_id=job.public_id,
            actor=self.student,
            kind=job.kind,
            mapping={
                "course_title": "课程",
                "weekday": "星期",
                "start_period": "开始",
                "end_period": "结束",
            },
        )
        self.assertEqual(job.status, TimetableImportJob.Status.READY)
        self.assertEqual(job.row_errors, [{"row_no": 2, "code": "weekday_required"}])

    def test_administrative_class_transfer_preserves_membership_history(self) -> None:
        first = create_administrative_class(
            actor=self.teacher,
            code="CS-2026-A",
            name="计算机行政班 A",
            department="计算机学院",
            year_of_entry=2026,
        )
        second = create_administrative_class(
            actor=self.teacher,
            code="CS-2026-B",
            name="计算机行政班 B",
            department="计算机学院",
            year_of_entry=2026,
        )
        membership = assign_administrative_class_member(
            actor=self.teacher, class_id=first.public_id, student_id=self.student.public_id
        )
        repeated = assign_administrative_class_member(
            actor=self.teacher, class_id=first.public_id, student_id=self.student.public_id
        )
        current = assign_administrative_class_member(
            actor=self.teacher, class_id=second.public_id, student_id=self.student.public_id
        )

        membership.refresh_from_db()
        self.assertEqual(membership.administrative_class, first)
        self.assertIsNotNone(membership.ends_on)
        self.assertEqual(current.administrative_class, second)
        self.assertEqual(repeated.pk, membership.pk)
        self.assertEqual(
            AdministrativeClassMembership.objects.filter(student=self.student).count(), 2
        )
        self.assertEqual(
            AdministrativeClass.objects.filter(status=AdministrativeClass.Status.ACTIVE).count(), 2
        )
