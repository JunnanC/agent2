from datetime import timedelta
from io import BytesIO
from re import sub
from zipfile import ZipFile

from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook

from apps.accounts.tests.helpers import create_user

from ..models import (
    AcademicTerm,
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

        course = Course.objects.get(timetable_code="BIO-204")
        schedule = CourseSchedule.objects.get(course=course)
        self.assertEqual(course.owner, self.teacher)
        self.assertEqual(course.term, self.term)
        self.assertEqual((schedule.weekday, schedule.start_period, schedule.end_period), (5, 5, 6))
        self.assertEqual(completed.public_id, replay.public_id)
        self.assertEqual(CourseSchedule.objects.filter(course=course).count(), 1)
        self.assertFalse(Enrollment.objects.filter(course=course).exists())

    def test_two_excel_layouts_reimport_and_cross_term_number_reuse(self) -> None:
        now = timezone.now()
        past = AcademicTerm.objects.create(
            code="FIXTURE-PAST",
            name="虚构往期",
            status=AcademicTerm.Status.CLOSED,
            starts_at=now - timedelta(days=180),
            ends_at=now - timedelta(days=30),
        )
        context = ActorContext(self.teacher.public_id, "TEACHING", "e" * 32)

        def import_workbook(term, code, *, compact=False):
            headers = (
                ["班号", "课程名称", "上课日", "节次", "周次", "地点"]
                if compact
                else [
                    "教学班编号",
                    "教学班名",
                    "星期",
                    "开始节",
                    "结束节",
                    "起始周",
                    "结束周",
                    "教室",
                ]
            )
            values = (
                [code, "数据结构", "3", "3-4", "2-16双周", "B202"]
                if compact
                else [
                    code,
                    "数据结构",
                    "周一",
                    "1",
                    "2",
                    "1",
                    "16",
                    "A101",
                ]
            )
            fields = [
                "course_code",
                "course_title",
                "weekday",
                "start_period",
                "end_period",
                "week_start",
                "week_end",
                "classroom",
            ]
            columns = (
                [*headers[:4], headers[3], headers[4], headers[4], headers[5]]
                if compact
                else headers
            )
            kind = TimetableImportJob.Kind.TEACHER
            content = workbook_bytes(headers, values)
            if compact:
                # Some spreadsheet exporters omit the worksheet dimension.
                stream = BytesIO()
                with ZipFile(BytesIO(content)) as source, ZipFile(stream, "w") as target:
                    for filename in source.namelist():
                        data = source.read(filename)
                        if filename == "xl/worksheets/sheet1.xml":
                            data = sub(rb"<dimension [^>]*/>", b"", data)
                        target.writestr(filename, data)
                content = stream.getvalue()
            job = create_timetable_import_job(
                actor=self.teacher,
                kind=kind,
                filename="fixture.xlsx",
                content=content,
                term_id=term.public_id,
            )
            job = update_timetable_import_mapping(
                job_id=job.public_id,
                actor=self.teacher,
                kind=kind,
                mapping=dict(zip(fields, columns, strict=True)),
            )
            self.assertEqual(job.row_errors, [])
            start_timetable_import(job_id=job.public_id, actor=self.teacher, kind=kind)
            return execute_timetable_import(
                job_id=job.public_id, actor=self.teacher, kind=kind, context=context
            )

        import_workbook(self.term, "DS-01")
        import_workbook(self.term, "DS-02", compact=True)
        import_workbook(past, "DS-01")
        replay = import_workbook(self.term, "DS-02", compact=True)
        self.assertEqual(replay.summary["schedules"], 0)
        self.assertEqual(Course.objects.filter(owner=self.teacher, title="数据结构").count(), 3)
        self.assertEqual(Course.objects.filter(timetable_code="DS-01").count(), 2)
        even = CourseSchedule.objects.get(course__timetable_code="DS-02")
        self.assertEqual((even.week_start, even.week_end, even.week_parity), (2, 16, "EVEN"))
        self.assertEqual(even.course.status, Course.Status.PUBLISHED)

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

    def test_student_can_join_multiple_classes_without_losing_membership(self) -> None:
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
        self.assertIsNone(membership.ends_on)
        self.assertEqual(current.administrative_class, second)
        self.assertEqual(repeated.pk, membership.pk)
        self.assertEqual(
            AdministrativeClassMembership.objects.filter(student=self.student).count(), 2
        )
        self.assertEqual(
            AdministrativeClass.objects.filter(status=AdministrativeClass.Status.ACTIVE).count(), 2
        )
