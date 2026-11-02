from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.core.errors import ResourceNotFound, StateConflict
from apps.courses.models import (
    AcademicTerm,
    AdministrativeClass,
    AdministrativeClassMembership,
    CourseSchedule,
    Enrollment,
    StudentScheduleEntry,
    TimetableImportJob,
)
from apps.courses.selectors import require_course_capability, visible_course

from .errors import ContentStateConflict
from .tasks import run_timetable_import
from .timetable_serializers import (
    AdministrativeClassMemberWriteSerializer,
    AdministrativeClassWriteSerializer,
    GenericTimetableResponseSerializer,
    TimetableMappingSerializer,
    TimetableUploadSerializer,
)
from .timetable_services import (
    assign_administrative_class_member,
    create_administrative_class,
    create_timetable_import_job,
    end_administrative_class_membership,
    start_timetable_import,
    timetable_import_data,
    update_timetable_import_mapping,
)


def _response(request: HttpRequest, data: Any, *, status: int = 200) -> Response:
    response = Response(
        {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}, status=status
    )
    response["Cache-Control"] = "private, no-store"
    return response


def _schedule_data(item: CourseSchedule | StudentScheduleEntry, *, source: str) -> dict[str, Any]:
    if isinstance(item, CourseSchedule):
        course = item.course
        term_id = course.term.public_id
        code = course.code
        title = course.title
        course_id = course.public_id
    else:
        course = item.course
        term_id = item.term.public_id
        code = item.course_code
        title = item.course_title
        course_id = course.public_id if course else None
    return {
        "source": source,
        "class_type": "TEACHING" if course else "EXTERNAL",
        "course_id": course_id,
        "course_code": code,
        "course_title": title,
        "term_id": term_id,
        "weekday": item.weekday,
        "start_period": item.start_period,
        "end_period": item.end_period,
        "week_start": item.week_start or None,
        "week_end": item.week_end or None,
        "classroom": item.classroom,
        "instructor_name": item.instructor_name,
    }


class TimetableImportCollectionView(APIView):
    permission_classes: list[type] = []
    kind = ""

    @extend_schema(responses={200: GenericTimetableResponseSerializer})
    def get(self, request: HttpRequest) -> Response:
        jobs = (
            TimetableImportJob.objects.filter(owner=request.user, kind=self.kind)
            .select_related("term")
            .order_by("-created_at")[:20]
        )
        return _response(request, [timetable_import_data(item) for item in jobs])

    @extend_schema(
        request=TimetableUploadSerializer, responses={201: GenericTimetableResponseSerializer}
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = TimetableUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        if uploaded.size > 10 * 1024 * 1024:
            raise ContentStateConflict(detail={"file": "too_large"})
        job = create_timetable_import_job(
            actor=request.user,
            kind=self.kind,
            filename=uploaded.name,
            content=uploaded.read(),
            term_id=serializer.validated_data.get("term_id", ""),
        )
        return _response(request, timetable_import_data(job), status=201)


class StudentTimetableImportView(TimetableImportCollectionView):
    permission_classes = [IsUserPortal]
    kind = TimetableImportJob.Kind.STUDENT


class TeachingTimetableImportView(TimetableImportCollectionView):
    permission_classes = [IsTeachingPortal]
    kind = TimetableImportJob.Kind.TEACHER


class TimetableImportDetailView(APIView):
    permission_classes: list[type] = []
    kind = ""

    @extend_schema(request=None, responses={200: GenericTimetableResponseSerializer})
    def get(self, request: HttpRequest, job_id: str) -> Response:
        try:
            job = TimetableImportJob.objects.select_related("term").get(
                public_id=job_id, owner=request.user, kind=self.kind
            )
        except TimetableImportJob.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        return _response(request, timetable_import_data(job))

    @extend_schema(
        request=TimetableMappingSerializer, responses={200: GenericTimetableResponseSerializer}
    )
    def put(self, request: HttpRequest, job_id: str) -> Response:
        serializer = TimetableMappingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = update_timetable_import_mapping(
            job_id=job_id,
            actor=request.user,
            kind=self.kind,
            mapping=serializer.validated_data["mapping"],
        )
        return _response(request, timetable_import_data(job))

    @extend_schema(request=None, responses={202: GenericTimetableResponseSerializer})
    def post(self, request: HttpRequest, job_id: str) -> Response:
        job = start_timetable_import(job_id=job_id, actor=request.user, kind=self.kind)
        transaction.on_commit(
            lambda: run_timetable_import.delay(
                job.public_id,
                request.user.pk,
                self.kind,
                str(getattr(request, "trace_id", "")),
            ),
            robust=True,
        )
        return _response(request, timetable_import_data(job), status=202)


@extend_schema_view(get=extend_schema(operation_id="student_timetable_import_retrieve"))
class StudentTimetableImportDetailView(TimetableImportDetailView):
    permission_classes = [IsUserPortal]
    kind = TimetableImportJob.Kind.STUDENT
    http_method_names = ["get", "head", "options"]


@extend_schema_view(put=extend_schema(operation_id="student_timetable_import_mapping_update"))
class StudentTimetableImportMappingView(StudentTimetableImportDetailView):
    http_method_names = ["put", "options"]


@extend_schema_view(post=extend_schema(operation_id="student_timetable_import_confirm"))
class StudentTimetableImportConfirmView(StudentTimetableImportDetailView):
    http_method_names = ["post", "options"]


@extend_schema_view(get=extend_schema(operation_id="teaching_timetable_import_retrieve"))
class TeachingTimetableImportDetailView(TimetableImportDetailView):
    permission_classes = [IsTeachingPortal]
    kind = TimetableImportJob.Kind.TEACHER
    http_method_names = ["get", "head", "options"]


@extend_schema_view(put=extend_schema(operation_id="teaching_timetable_import_mapping_update"))
class TeachingTimetableImportMappingView(TeachingTimetableImportDetailView):
    http_method_names = ["put", "options"]


@extend_schema_view(post=extend_schema(operation_id="teaching_timetable_import_confirm"))
class TeachingTimetableImportConfirmView(TeachingTimetableImportDetailView):
    http_method_names = ["post", "options"]


class UserTimetableView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses={200: GenericTimetableResponseSerializer})
    def get(self, request: HttpRequest) -> Response:
        term_id = request.query_params.get("term_id", "")
        term = (
            AcademicTerm.objects.filter(public_id=term_id).first()
            if term_id
            else AcademicTerm.objects.filter(is_current=True).first()
        )
        if term is None:
            raise StateConflict(detail={"academic_term": "current_term_required"})
        imported = list(
            StudentScheduleEntry.objects.filter(student=request.user, term=term)
            .select_related("term", "course")
            .order_by("weekday", "start_period", "course_title")
        )
        course_ids = Enrollment.objects.filter(
            student=request.user, course__term=term, status=Enrollment.Status.ACTIVE
        ).values_list("course_id", flat=True)
        platform = (
            CourseSchedule.objects.filter(course_id__in=course_ids)
            .select_related("course__term")
            .order_by("weekday", "start_period", "course__title")
        )
        return _response(
            request,
            {
                "term": {"public_id": term.public_id, "code": term.code, "name": term.name},
                "schedules": [
                    *[_schedule_data(item, source="IMPORTED") for item in imported],
                    *[_schedule_data(item, source="PLATFORM") for item in platform],
                ],
            },
        )


class TeachingCourseTimetableView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses={200: GenericTimetableResponseSerializer})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_course_capability(course=course, actor=request.user, capability="VIEW_PROGRESS")
        schedules = CourseSchedule.objects.filter(course=course).order_by("weekday", "start_period")
        return _response(
            request,
            {
                "course_id": course.public_id,
                "class_type": "TEACHING",
                "schedules": [_schedule_data(item, source="PLATFORM") for item in schedules],
            },
        )


def _administrative_class_data(item: AdministrativeClass) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "class_type": "ADMINISTRATIVE",
        "code": item.code,
        "name": item.name,
        "department": item.department,
        "year_of_entry": item.year_of_entry,
        "status": item.status,
        "row_version": item.row_version,
    }


def _membership_data(item: AdministrativeClassMembership) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "class_id": item.administrative_class.public_id,
        "student_id": item.student.public_id,
        "student_name": item.student.display_name,
        "starts_on": item.starts_on,
        "ends_on": item.ends_on,
        "row_version": item.row_version,
    }


class AdministrativeClassCollectionView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(responses={200: GenericTimetableResponseSerializer})
    def get(self, request: HttpRequest) -> Response:
        values = AdministrativeClass.objects.order_by("year_of_entry", "code")
        return _response(request, [_administrative_class_data(item) for item in values])

    @extend_schema(
        request=AdministrativeClassWriteSerializer,
        responses={201: GenericTimetableResponseSerializer},
    )
    def post(self, request: HttpRequest) -> Response:
        serializer = AdministrativeClassWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            item = create_administrative_class(
                actor=request.user,
                code=serializer.validated_data["code"],
                name=serializer.validated_data["name"],
                department=serializer.validated_data.get("department", ""),
                year_of_entry=serializer.validated_data.get("year_of_entry"),
            )
        except IntegrityError as exc:
            raise ContentStateConflict(detail={"code": "already_exists"}) from exc
        return _response(request, _administrative_class_data(item), status=201)


class AdministrativeClassMembersView(APIView):
    permission_classes = [IsPlatformPortal]

    def _class(self, class_id: str) -> AdministrativeClass:
        try:
            return AdministrativeClass.objects.get(public_id=class_id)
        except AdministrativeClass.DoesNotExist as exc:
            raise ResourceNotFound() from exc

    @extend_schema(responses={200: GenericTimetableResponseSerializer})
    def get(self, request: HttpRequest, class_id: str) -> Response:
        administrative_class = self._class(class_id)
        include_history = request.query_params.get("include_history") == "true"
        values = (
            AdministrativeClassMembership.objects.filter(administrative_class=administrative_class)
            .select_related("student")
            .order_by("student__display_name", "-starts_on")
        )
        if not include_history:
            values = values.filter(ends_on__isnull=True)
        return _response(
            request,
            {
                "class": _administrative_class_data(administrative_class),
                "members": [_membership_data(item) for item in values],
            },
        )

    @extend_schema(
        request=AdministrativeClassMemberWriteSerializer,
        responses={201: GenericTimetableResponseSerializer},
    )
    def post(self, request: HttpRequest, class_id: str) -> Response:
        serializer = AdministrativeClassMemberWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._class(class_id)
        item = assign_administrative_class_member(
            actor=request.user,
            class_id=class_id,
            student_id=serializer.validated_data["student_id"],
        )
        return _response(request, _membership_data(item), status=201)


class AdministrativeClassMemberEndView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_administrative_class_member_end",
        request=None,
        responses={200: GenericTimetableResponseSerializer},
    )
    def post(self, request: HttpRequest, class_id: str, student_id: str) -> Response:
        item = end_administrative_class_membership(class_id=class_id, student_id=student_id)
        return _response(request, _membership_data(item))
