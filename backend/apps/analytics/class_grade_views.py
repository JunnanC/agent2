import csv
from io import StringIO

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.accounts.permissions import IsTeachingPortal

from .class_grades import analyze_released_grades, current_released_results
from .selectors import teaching_course
from .views import AnalyticsAPIView, _response


class GradeSummarySerializer(serializers.Serializer):
    expected = serializers.IntegerField()
    completed = serializers.IntegerField()
    completion_rate = serializers.FloatField(allow_null=True)
    score = serializers.FloatField()
    max_score = serializers.FloatField()
    percent = serializers.FloatField(allow_null=True)


class ClassGradeSummarySerializer(GradeSummarySerializer):
    failure_rate = serializers.FloatField(allow_null=True)


class ExperimentGradeSummarySerializer(GradeSummarySerializer):
    publication_id = serializers.CharField()
    title = serializers.CharField()
    deadline = serializers.DateTimeField()
    released_at = serializers.DateTimeField()


class StudentGradeSummarySerializer(GradeSummarySerializer):
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    rank = serializers.IntegerField(allow_null=True)
    failed = serializers.BooleanField(allow_null=True)


class GradePartSummarySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["CHOICE", "PROGRAMMING", "REPORT"])
    label = serializers.CharField()
    percent = serializers.FloatField(allow_null=True)
    suggestion = serializers.CharField(allow_blank=True)


class ReleasedResultSerializer(serializers.Serializer):
    publication_id = serializers.CharField()
    task_id = serializers.CharField(allow_null=True)
    student_id = serializers.CharField()
    student_name = serializers.CharField()
    status = serializers.ChoiceField(choices=["SUBMITTED", "PARTIAL", "NOT_SUBMITTED"])
    score = serializers.FloatField()
    max_score = serializers.FloatField()


class UnconfirmedGradeSerializer(serializers.Serializer):
    publication_id = serializers.CharField(required=False)
    task_id = serializers.CharField(allow_blank=True)
    reason = serializers.CharField()


class ReleasedGradeReportSerializer(serializers.Serializer):
    summary = ClassGradeSummarySerializer()
    experiments = ExperimentGradeSummarySerializer(many=True)
    students = StudentGradeSummarySerializer(many=True)
    parts = GradePartSummarySerializer(many=True)
    results = ReleasedResultSerializer(many=True)
    awaiting_confirmation = UnconfirmedGradeSerializer(many=True)


class ReleasedGradeResponseSerializer(serializers.Serializer):
    data = ReleasedGradeReportSerializer()
    meta = serializers.DictField()


class GradeExportDataSerializer(serializers.Serializer):
    filename = serializers.CharField()
    csv = serializers.CharField()


class GradeExportResponseSerializer(serializers.Serializer):
    data = GradeExportDataSerializer()
    meta = serializers.DictField()


def _report(request, course_id):
    course = teaching_course(actor=request.user, course_id=course_id)
    experiments, results, awaiting = current_released_results(course)
    selected = {key for key in request.query_params.get("publication_ids", "").split(",") if key}
    if selected - {experiment.publication_id for experiment in experiments}:
        raise ValidationError({"publication_ids": "选择本班已发布成绩的实验"})
    return analyze_released_grades(experiments, results, selected, awaiting)


def _csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class TeachingClassGradesView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        parameters=[OpenApiParameter("publication_ids", str)],
        responses=ReleasedGradeResponseSerializer,
        tags=["teaching-analytics"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request, course_id):
        return _response(request, _report(request, course_id))


class TeachingClassGradesExportView(AnalyticsAPIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        parameters=[OpenApiParameter("publication_ids", str)],
        responses=GradeExportResponseSerializer,
        tags=["teaching-analytics"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request, course_id):
        report = _report(request, course_id)
        output = StringIO()
        writer = csv.writer(output)
        summary = report["summary"]
        writer.writerow(["完成度(%)", "挂科率(%)", "总实得分", "总满分", "待确认记录数"])
        writer.writerow([
            summary["completion_rate"],
            summary["failure_rate"],
            summary["score"],
            summary["max_score"],
            len(report["awaiting_confirmation"]),
        ])
        writer.writerow(["实验ID", "实验", "应做人数", "完成人数", "得分率(%)"])
        for experiment in report["experiments"]:
            writer.writerow([
                _csv_cell(experiment[key])
                for key in (
                    "publication_id",
                    "title",
                    "expected",
                    "completed",
                    "percent",
                )
            ])
        writer.writerow(["学生ID", "学生", "排名", "总评(%)", "实得分", "满分", "完成度(%)"])
        for student in report["students"]:
            writer.writerow([
                _csv_cell(student[key])
                for key in (
                    "student_id",
                    "student_name",
                    "rank",
                    "percent",
                    "score",
                    "max_score",
                    "completion_rate",
                )
            ])
        writer.writerow(["实验ID", "学生ID", "提交状态", "实得分", "满分"])
        statuses = {"NOT_SUBMITTED": "未提交", "PARTIAL": "部分提交", "SUBMITTED": "已完成"}
        for row in report["results"]:
            writer.writerow([
                row["publication_id"],
                row["student_id"],
                statuses[row["status"]],
                row["score"],
                row["max_score"],
            ])
        writer.writerow(["分项", "得分率(%)", "教学建议"])
        for part in report["parts"]:
            writer.writerow([part["label"], part["percent"], part["suggestion"]])
        writer.writerow(["待确认任务ID", "原因"])
        for row in report["awaiting_confirmation"]:
            writer.writerow([_csv_cell(row["task_id"]), row["reason"]])
        return _response(
            request, {"filename": f"class-{course_id}-grades.csv", "csv": output.getvalue()}
        )
