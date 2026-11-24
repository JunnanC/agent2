import json
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import F, Q

from apps.courses.models import Course, CourseSchedule, Enrollment, StudentScheduleEntry
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.reports.models import ReportSubmission


class Command(BaseCommand):
    help = "List legacy schedule entries and experimental tasks that need class confirmation."

    def handle(self, *args, **options):
        classes = Course.objects.all()
        schedules = StudentScheduleEntry.objects.select_related("term").order_by("pk")
        with connection.cursor() as cursor:
            has_timetable_code = any(
                column.name == "timetable_code"
                for column in connection.introspection.get_table_description(
                    cursor, Course._meta.db_table
                )
            )
        awaiting = []
        linked_legacy_schedules = 0
        for schedule in schedules.iterator():
            if (
                schedule.course_id
                and classes.filter(pk=schedule.course_id, term_id=schedule.term_id).exists()
            ):
                linked_legacy_schedules += 1
                continue
            candidates = classes.filter(term=schedule.term)
            code_filter = Q(code=schedule.course_code)
            if has_timetable_code:
                code_filter |= Q(timetable_code=schedule.course_code)
            same_code = candidates.filter(code_filter)
            ids = (
                list(same_code.order_by("pk").values_list("public_id", flat=True))
                if schedule.course_code
                else []
            )
            if not ids:
                ids = list(
                    candidates.filter(title=schedule.course_title)
                    .order_by("pk")
                    .values_list("public_id", flat=True)
                )
            awaiting.append({
                "type": "student_schedule",
                "id": schedule.public_id,
                "term_id": schedule.term.public_id,
                "candidate_class_ids": ids,
            })
        consistent = (
            Q(course_id=F("publication__course_id"))
            & Q(course_id=F("enrollment__course_id"))
            & Q(student_id=F("enrollment__student_id"))
            & Q(enrollment__activated_at__isnull=False)
        )
        inconsistent_tasks = (
            ExperimentTask.objects.exclude(consistent)
            .select_related(
                "course",
                "publication__course",
                "enrollment__course",
            )
            .order_by("pk")
        )
        inconsistent_tasks = inconsistent_tasks.only(
            "public_id",
            "course__public_id",
            "publication__course__public_id",
            "enrollment__course__public_id",
        )
        for task in inconsistent_tasks.iterator():
            awaiting.append({
                "type": "experiment_task",
                "id": task.public_id,
                "candidate_class_ids": sorted({
                    task.course.public_id,
                    task.publication.course.public_id,
                    task.enrollment.course.public_id,
                }),
            })
        self.stdout.write(
            json.dumps(
                {
                    "counts": {
                        "classes": classes.count(),
                        "schedules": CourseSchedule.objects.count(),
                        "legacy_student_schedules": schedules.count(),
                        "linked_legacy_schedules": linked_legacy_schedules,
                        "enrollments": Enrollment.objects.count(),
                        "publications": TaskPublication.objects.count(),
                        "tasks": ExperimentTask.objects.count(),
                        "reports": ReportSubmission.objects.count(),
                        "scored_reports": ReportSubmission.objects.filter(
                            score__isnull=False
                        ).count(),
                    },
                    "awaiting_by_type": dict(Counter(item["type"] for item in awaiting)),
                    "awaiting_confirmation": awaiting,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
