from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.core.errors import ResourceNotFound
from apps.core.pagination import PageSpec
from apps.courses.models import (
    AcademicTerm,
    AdministrativeClass,
    AdministrativeClassMembership,
    Course,
    CourseSchedule,
    CourseStaff,
    Enrollment,
    TimetableImportJob,
)
from apps.courses.selectors import (
    require_course_capability,
    term_for_ref,
    visible_course,
    visible_courses,
)

from .errors import ContentStateConflict
from .tasks import run_timetable_import
from .timetable_serializers import (
    AdministrativeClassMemberWriteSerializer,
    AdministrativeClassWriteSerializer,
    GenericTimetableResponseSerializer,
    TeachingCourseTimetableResponseSerializer,
    TermTimetableResponseSerializer,
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


def _term_data(term: AcademicTerm) -> dict[str, Any]:
    # Legacy terms were created to migrate existing courses and have estimated dates.
    calendar = None
    if not term.code.startswith("LEGACY-"):
        school_zone = timezone.get_default_timezone()
        calendar = {
            "starts_on": timezone.localdate(term.starts_at, school_zone).isoformat(),
            "ends_on": timezone.localdate(term.ends_at, school_zone).isoformat(),
        }
    return {
        "public_id": term.public_id,
        "code": term.code,
        "name": term.name,
        "calendar": calendar,
    }


def _class_data(course: Course) -> dict[str, str]:
    return {
        "course_id": course.public_id,
        "course_code": course.timetable_code or course.code,
        "course_title": course.title,
        "instructor_name": course.owner.display_name,
    }


def _schedule_data(item: CourseSchedule) -> dict[str, Any]:
    return {
        **_class_data(item.course),
        "source": "PLATFORM",
        "class_type": "TEACHING",
        "term_id": item.course.term.public_id,
        "weekday": item.weekday,
        "start_period": item.start_period,
        "end_period": item.end_period,
        "week_start": item.week_start or None,
        "week_end": item.week_end or None,
        "week_parity": item.week_parity,
        "classroom": item.classroom,
        "instructor_name": item.instructor_name or item.course.owner.display_name,
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


def _term_timetable(
    courses: QuerySet[Course], term: AcademicTerm, page: PageSpec | None = None
) -> dict[str, Any]:
    courses = courses.filter(term=term).select_related("owner").order_by("title", "pk")
    total = courses.count() if page else None
    class_rows = list(courses[page.offset : page.offset + page.page_size] if page else courses)
    schedules = (
        CourseSchedule.objects.filter(course_id__in=[course.pk for course in class_rows])
        .select_related("course__term", "course__owner")
        .order_by("weekday", "start_period", "course__title", "pk")
    )
    return {
        "term": _term_data(term),
        "terms": [_term_data(item) for item in AcademicTerm.objects.order_by("-starts_at", "pk")],
        "classes": [_class_data(course) for course in class_rows],
        **({"total": total} if page else {}),
        "schedules": [_schedule_data(item) for item in schedules],
    }


class UserTimetableView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        parameters=[OpenApiParameter("term_id", str)],
        responses={200: TermTimetableResponseSerializer},
    )
    def get(self, request: HttpRequest) -> Response:
        term = term_for_ref(request.query_params.get("term_id") or "current")
        courses = Course.objects.select_related("owner").filter(
            enrollments__student=request.user, enrollments__status=Enrollment.Status.ACTIVE
        )
        return _response(request, _term_timetable(courses, term))


class TeachingTimetableView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        parameters=[OpenApiParameter("term_id", str)],
        responses={200: TermTimetableResponseSerializer},
    )
    def get(self, request: HttpRequest) -> Response:
        term = term_for_ref(request.query_params.get("term_id") or "current")
        courses = visible_courses(actor=request.user, portal="TEACHING")
        return _response(request, _term_timetable(courses, term))


class TeachingCourseTimetableView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses={200: TeachingCourseTimetableResponseSerializer})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_course_capability(course=course, actor=request.user, capability="VIEW_PROGRESS")
        schedules = CourseSchedule.objects.filter(course=course).order_by("weekday", "start_period")
        return _response(
            request,
            {
                "course_id": course.public_id,
                "class_type": "TEACHING",
                "term": _term_data(course.term),
                "schedules": [_schedule_data(item) for item in schedules],
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


class PlatformTeachingClassMembersView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(responses={200: GenericTimetableResponseSerializer})
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="PLATFORM", course_id=course_id)
        enrollments = (
            Enrollment.objects.filter(
                course=course,
                status=Enrollment.Status.ACTIVE,
            )
            .select_related("student")
            .order_by("student__display_name", "pk")
        )
        return _response(
            request,
            {
                "class": {"public_id": course.public_id, "name": course.title},
                "members": [
                    {
                        "public_id": item.public_id,
                        "student_id": item.student.public_id,
                        "student_name": item.student.display_name,
                    }
                    for item in enrollments
                ],
            },
        )


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


class PlatformTermClassesView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        parameters=[
            OpenApiParameter(name, kind)
            for name, kind in (
                ("term_id", str),
                ("role", str),
                ("person_id", str),
                ("q", str),
                ("page", int),
                ("page_size", int),
            )
        ],
        responses={200: TermTimetableResponseSerializer},
    )
    def get(self, request: HttpRequest) -> Response:
        params = request.query_params
        term = term_for_ref(params.get("term_id") or "current")
        page = PageSpec.parse(params.get("page", 1), params.get("page_size", 20))
        courses = Course.objects.all()
        person = params.get("person_id")
        role = params.get("role")
        if role not in (None, "TEACHER", "STUDENT") or (person and not role):
            raise ValidationError({"role": "请选择教师或学生"})
        if person:
            if not User.objects.filter(public_id=person).exists():
                raise ResourceNotFound()
            if role == "TEACHER":
                courses = courses.filter(
                    staff__user__public_id=person, staff__status=CourseStaff.Status.ACTIVE
                )
            else:
                courses = courses.filter(
                    enrollments__student__public_id=person,
                    enrollments__status=Enrollment.Status.ACTIVE,
                )
        query = (params.get("q") or "").strip()
        if query:
            courses = courses.filter(
                Q(title__icontains=query)
                | Q(timetable_code__icontains=query)
                | Q(code__icontains=query)
            )
        return _response(request, _term_timetable(courses.distinct(), term, page))
