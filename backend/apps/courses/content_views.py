from pathlib import PurePosixPath
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsTeachingPortal, IsUserPortal
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import StoredResponse

from .content_serializers import (
    AnswerWriteSerializer,
    CalendarWriteSerializer,
    ContentWriteSerializer,
    CopyWriteSerializer,
    CourseContentListResponseSerializer,
    CourseContentResponseSerializer,
    InvitationWriteSerializer,
    QuestionWriteSerializer,
    StatusActionSerializer,
)
from .content_services import (
    add_chapter_prerequisite,
    add_course_prerequisite,
    answer_question,
    change_chapter_status,
    change_material_version_status,
    create_announcement,
    create_calendar_event,
    create_chapter,
    create_copy_job,
    create_import_job,
    create_invitation,
    create_material,
    create_material_version,
    create_question,
    moderate_question,
    prerequisite_status,
    publish_announcement,
)
from .models import (
    Announcement,
    Answer,
    CalendarEvent,
    Chapter,
    Course,
    CourseCopyJob,
    EnrollmentImportJob,
    Material,
    MaterialVersion,
    Question,
)
from .selectors import active_enrollment, require_course_capability, visible_course
from .services import ActorContext
from .tasks import run_copy_job, run_enrollment_import, run_enrollment_import_precheck
from .teaching_crypto import readable_invitation
from .views import _body, _context, _idempotent_response, _response


def _data(item: Any) -> dict[str, object]:
    if isinstance(item, Chapter):
        return {
            "public_id": item.public_id,
            "course_id": item.course.public_id,
            "title": item.title,
            "summary": item.summary,
            "content": item.content,
            "position": item.position,
            "status": item.status,
            "row_version": item.row_version,
        }
    if isinstance(item, Material):
        current = item.current_version
        return {
            "public_id": item.public_id,
            "course_id": item.course.public_id,
            "chapter_id": item.chapter.public_id,
            "title": item.title,
            "kind": item.kind,
            "current_version_id": current.public_id if current else None,
            "link_url": current.link_url if current else "",
            "text_content": current.text_content if current else "",
            "object_asset_id": (
                current.object_asset.public_id if current and current.object_asset else None
            ),
            "asset_name": current.object_asset.original_name
            if current and current.object_asset
            else "",
            "size_bytes": current.object_asset.size_bytes
            if current and current.object_asset
            else None,
            "version_status": current.status if current else None,
            "row_version": item.row_version,
        }
    if isinstance(item, MaterialVersion):
        return {
            "public_id": item.public_id,
            "material_id": item.material.public_id,
            "version_no": item.version_no,
            "status": item.status,
            "text_content": item.text_content,
            "link_url": item.link_url,
            "object_asset_id": item.object_asset.public_id if item.object_asset else None,
            "published_at": item.published_at,
            "row_version": item.row_version,
        }
    if isinstance(item, Announcement):
        return {
            "public_id": item.public_id,
            "course_id": item.course.public_id,
            "title": item.title,
            "body": item.body,
            "status": item.status,
            "pinned": item.pinned,
            "publish_at": item.publish_at,
            "expires_at": item.expires_at,
            "row_version": item.row_version,
        }
    if isinstance(item, CalendarEvent):
        return {
            "public_id": item.public_id,
            "course_id": item.course.public_id,
            "title": item.title,
            "description": item.description,
            "starts_at": item.starts_at,
            "ends_at": item.ends_at,
            "status": item.status,
            "row_version": item.row_version,
        }
    if isinstance(item, Question):
        return {
            "public_id": item.public_id,
            "course_id": item.course.public_id,
            "author_id": item.author.public_id,
            "author_name": item.author.display_name,
            "title": item.title,
            "body": item.body,
            "status": item.status,
            "pinned": item.pinned,
            "row_version": item.row_version,
            "answers": [
                _data(answer)
                for answer in item.answers
                .filter(status="VISIBLE")
                .select_related("author")
                .order_by("created_at")
            ],
        }
    if isinstance(item, Answer):
        return {
            "public_id": item.public_id,
            "question_id": item.question.public_id,
            "author_id": item.author.public_id,
            "author_name": item.author.display_name,
            "body": item.body,
            "status": item.status,
            "row_version": item.row_version,
        }
    if isinstance(item, EnrollmentImportJob):
        return {
            "public_id": item.public_id,
            "course_id": item.course.public_id,
            "status": item.status,
            "filename": item.filename,
            "summary": item.summary,
            "items": [
                {
                    "row_no": row.row_no,
                    "identity": row.normalized_identity,
                    "status": row.status,
                    "error_code": row.error_code,
                    "enrollment_id": row.enrollment.public_id if row.enrollment else None,
                }
                for row in item.items.all().order_by("row_no")
            ],
        }
    if isinstance(item, CourseCopyJob):
        return {
            "public_id": item.public_id,
            "source_course_id": item.source_course.public_id,
            "target_course_id": item.target_course.public_id if item.target_course else None,
            "status": item.status,
            "options": item.options,
            "error_code": item.error_code,
            "items": [
                {
                    "item_type": row.item_type,
                    "source_ref": row.source_ref,
                    "target_ref": row.target_ref,
                    "status": row.status,
                    "error_code": row.error_code,
                }
                for row in item.items.all()
            ],
        }
    return {}


def _ctx(request: HttpRequest) -> ActorContext:
    return _context(request)


def _wrapped(
    request: HttpRequest, value: Any, *, status: int = 200, etag: str | None = None
) -> Response:
    return _response(
        request,
        _data(value) if not isinstance(value, list) else [_data(item) for item in value],
        status=status,
        etag=etag,
    )


def _list(request: HttpRequest, values: list[Any]) -> Response:
    return _response(request, [_data(item) for item in values])


class UserCourseContentView(APIView):
    permission_classes = [IsUserPortal]

    def _course(self, request: HttpRequest, course_id: str) -> Course:
        course = visible_course(actor=request.user, portal="USER", course_id=course_id)
        active_enrollment(course=course, student=request.user) or self._require_pending(
            course, request.user
        )
        return course

    @staticmethod
    def _require_pending(course: Any, user: User) -> Any:
        from .errors import ActiveEnrollmentRequired

        raise ActiveEnrollmentRequired(detail={"course_id": course.public_id})

    @extend_schema(
        operation_id="user_course_content_list",
        responses={200: CourseContentListResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str, resource: str) -> Response:
        course = self._course(request, course_id)
        if resource == "chapters":
            return _list(
                request,
                list(course.chapters.filter(status=Chapter.Status.PUBLISHED).order_by("position")),
            )
        if resource == "materials":
            return _list(
                request,
                list(
                    Material.objects.filter(
                        course=course,
                        chapter__status=Chapter.Status.PUBLISHED,
                        current_version__status=MaterialVersion.Status.PUBLISHED,
                    ).select_related("course", "chapter", "current_version__object_asset")
                ),
            )
        if resource == "announcements":
            now = timezone.now()
            return _list(
                request,
                list(
                    course.announcements
                    .filter(status=Announcement.Status.PUBLISHED)
                    .filter(publish_at__lte=now)
                    .order_by("-pinned", "-publish_at")
                ),
            )
        if resource == "calendar":
            return _list(
                request, list(course.calendar_events.filter(status="ACTIVE").order_by("starts_at"))
            )
        if resource == "questions":
            return _list(
                request,
                list(
                    course.questions
                    .exclude(status__in=(Question.Status.HIDDEN, Question.Status.LOCKED))
                    .select_related("author")
                    .order_by("-pinned", "-created_at")
                ),
            )
        if resource == "prerequisites":
            return _response(request, prerequisite_status(course=course, student=request.user))
        return _response(request, [])

    @extend_schema(
        operation_id="user_course_content_create",
        request=QuestionWriteSerializer,
        responses={201: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, resource: str) -> Response:
        if resource != "questions":
            return _response(request, {"error": "unsupported_resource"}, status=405)
        serializer = QuestionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_question(
                course_id=course_id,
                actor=request.user,
                title=serializer.validated_data["title"],
                body=serializer.validated_data["body"],
                context=_ctx(request),
            )
            return StoredResponse(
                201,
                _body(request, _data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class UserQuestionCreateView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_course_questions_create",
        request=QuestionWriteSerializer,
        responses={201: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = QuestionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_question(
                course_id=course_id,
                actor=request.user,
                title=serializer.validated_data["title"],
                body=serializer.validated_data["body"],
                context=_ctx(request),
            )
            return StoredResponse(
                201, _body(request, _data(item)), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class QuestionAnswerView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="user_question_answers_create",
        request=AnswerWriteSerializer,
        responses={201: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, question_id: str) -> Response:
        serializer = AnswerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = answer_question(
                question_id=question_id,
                actor=request.user,
                body=serializer.validated_data["body"],
                context=_ctx(request),
            )
            return StoredResponse(
                201, _body(request, _data(item)), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TeachingContentCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_course_content_list",
        responses={200: CourseContentListResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str, resource: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        if resource == "chapters":
            require_course_capability(
                course=course, actor=request.user, capability="MANAGE_CONTENT"
            )
            return _list(request, list(course.chapters.order_by("position")))
        if resource == "materials":
            require_course_capability(
                course=course, actor=request.user, capability="MANAGE_CONTENT"
            )
            return _list(
                request,
                list(
                    course.materials.select_related(
                        "course", "chapter", "current_version__object_asset"
                    ).order_by("chapter__position", "title")
                ),
            )
        if resource == "announcements":
            require_course_capability(
                course=course, actor=request.user, capability="MANAGE_CONTENT"
            )
            return _list(request, list(course.announcements.order_by("-created_at")))
        if resource == "calendar-events":
            require_course_capability(
                course=course, actor=request.user, capability="MANAGE_CONTENT"
            )
            return _list(request, list(course.calendar_events.order_by("starts_at")))
        if resource == "questions":
            require_course_capability(course=course, actor=request.user, capability="MODERATE_QA")
            return _list(
                request, list(course.questions.select_related("author").order_by("-created_at"))
            )
        if resource == "prerequisites":
            require_course_capability(course=course, actor=request.user, capability="OWNER")
            return _response(
                request,
                [
                    {"course_id": row.prerequisite_course.public_id, "status": "NOT_EVALUABLE"}
                    for row in course.prerequisites.select_related("prerequisite_course")
                ],
            )
        return _response(request, [])

    @extend_schema(
        operation_id="teaching_course_content_create",
        request=ContentWriteSerializer,
        responses={201: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, resource: str) -> Response:
        serializer = ContentWriteSerializer(data=request.data)
        if resource == "calendar-events":
            serializer = CalendarWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        def operation() -> StoredResponse:
            if resource == "chapters":
                item = create_chapter(
                    course_id=course_id,
                    actor=request.user,
                    title=data["title"],
                    summary=data.get("summary", ""),
                    content=data.get("content", ""),
                    position=data["position"],
                    context=_ctx(request),
                )
            elif resource == "materials":
                item = create_material(
                    course_id=course_id,
                    actor=request.user,
                    chapter_id=str(request.data.get("chapter_id", "")),
                    title=data["title"],
                    kind=data["kind"],
                    text_content=data.get("text_content", ""),
                    link_url=data.get("link_url", ""),
                    asset_id=data.get("object_asset_id") or None,
                    context=_ctx(request),
                )
            elif resource == "announcements":
                item = create_announcement(
                    course_id=course_id,
                    actor=request.user,
                    title=data["title"],
                    body=data.get("body", ""),
                    pinned=data.get("pinned", False),
                    context=_ctx(request),
                )
            elif resource == "calendar-events":
                item = create_calendar_event(
                    course_id=course_id,
                    actor=request.user,
                    title=data["title"],
                    description=data.get("description", ""),
                    starts_at=data["starts_at"],
                    ends_at=data["ends_at"],
                    context=_ctx(request),
                )
            else:
                raise ValueError("unsupported content resource")
            return StoredResponse(
                201, _body(request, _data(item)), {"ETag": etag_for_version(item.row_version)}
            )

        return _idempotent_response(request, payload=data, operation=operation)


class TeachingChapterStatusView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_chapter_status",
        request=None,
        responses={200: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, chapter_id: str, status: str) -> Response:
        value = change_chapter_status(
            chapter_id=chapter_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")) or 0,
            status=status.upper(),
            context=_ctx(request),
        )
        return _wrapped(request, value, etag=etag_for_version(value.row_version))


class TeachingMaterialVersionCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_material_versions_list",
        responses={200: CourseContentListResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str, material_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_course_capability(course=course, actor=request.user, capability="MANAGE_CONTENT")
        return _list(
            request,
            list(
                MaterialVersion.objects.filter(
                    material__public_id=material_id, material__course=course
                ).order_by("-version_no")
            ),
        )

    @extend_schema(
        operation_id="teaching_material_versions_create",
        request=ContentWriteSerializer,
        responses={201: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, material_id: str) -> Response:
        serializer = ContentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        def operation() -> StoredResponse:
            value = create_material_version(
                material_id=material_id,
                actor=request.user,
                expected_version=None,
                text_content=data.get("text_content", ""),
                link_url=data.get("link_url", ""),
                asset_id=data.get("object_asset_id") or None,
                context=_ctx(request),
            )
            return StoredResponse(
                201, _body(request, _data(value)), {"ETag": etag_for_version(value.row_version)}
            )

        return _idempotent_response(request, payload=data, operation=operation)


class TeachingMaterialVersionStatusView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_material_version_status",
        request=None,
        responses={200: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str, status: str) -> Response:
        value = change_material_version_status(
            version_id=version_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")) or 0,
            status=status.upper(),
            context=_ctx(request),
        )
        return _wrapped(request, value, etag=etag_for_version(value.row_version))


class TeachingAnnouncementPublishView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_announcement_publish",
        request=None,
        responses={200: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, announcement_id: str) -> Response:
        value = publish_announcement(
            announcement_id=announcement_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")) or 0,
            context=_ctx(request),
        )
        return _wrapped(request, value, etag=etag_for_version(value.row_version))


class TeachingQuestionAnswerView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_question_answers_create",
        request=AnswerWriteSerializer,
        responses={201: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, question_id: str) -> Response:
        serializer = AnswerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            value = answer_question(
                question_id=question_id,
                actor=request.user,
                body=serializer.validated_data["body"],
                context=_ctx(request),
            )
            return StoredResponse(
                201, _body(request, _data(value)), {"ETag": etag_for_version(value.row_version)}
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TeachingQuestionModerateView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_question_moderate",
        request=StatusActionSerializer,
        responses={200: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, question_id: str) -> Response:
        serializer = StatusActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        value = moderate_question(
            question_id=question_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")) or 0,
            status=serializer.validated_data["status"],
            reason=serializer.validated_data.get("reason", ""),
            context=_ctx(request),
        )
        return _wrapped(request, value, etag=etag_for_version(value.row_version))


class TeachingInvitationView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_invitations_list",
        responses={200: CourseContentListResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_course_capability(course=course, actor=request.user, capability="MANAGE_ENROLLMENT")
        return _response(
            request,
            [
                {
                    "public_id": item.public_id,
                    "code": readable_invitation(item),
                    "recoverable": bool(item.code_encrypted),
                    "max_uses": item.max_uses,
                    "used_count": item.used_count,
                    "expires_at": item.expires_at,
                    "status": item.status,
                    "row_version": item.row_version,
                }
                for item in course.invitations.order_by("-created_at")
            ],
        )

    @extend_schema(
        operation_id="teaching_invitations_create",
        request=InvitationWriteSerializer,
        responses={201: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = InvitationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            invitation, raw = create_invitation(
                course_id=course_id,
                actor=request.user,
                max_uses=serializer.validated_data["max_uses"],
                expires_at=serializer.validated_data["expires_at"],
                context=_ctx(request),
            )
            payload = {
                "public_id": invitation.public_id,
                "code": raw,
                "expires_at": invitation.expires_at,
                "max_uses": invitation.max_uses,
                "warning": "请仅向需要加入本课程的学生分享",
            }
            return StoredResponse(
                201, _body(request, payload), {"ETag": etag_for_version(invitation.row_version)}
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TeachingImportView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_enrollment_import_precheck",
        request=None,
        responses={202: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        uploaded = request.FILES.get("file")
        filename = str(getattr(uploaded, "name", "enrollment.csv") or "enrollment.csv")
        if uploaded is not None and PurePosixPath(filename).suffix.casefold() != ".csv":
            from .errors import ContentStateConflict

            raise ContentStateConflict(detail={"file": "csv_extension_required"})
        if uploaded is not None and uploaded.size > 10 * 1024 * 1024:
            from .errors import ContentStateConflict

            raise ContentStateConflict(detail={"file": "too_large"})
        raw = uploaded.read().decode("utf-8-sig") if uploaded else str(request.data.get("csv", ""))
        job = create_import_job(
            course_id=course_id,
            actor=request.user,
            csv_payload=raw,
            filename=filename,
            context=_ctx(request),
        )
        transaction.on_commit(
            lambda: run_enrollment_import_precheck.delay(
                job.public_id, request.user.pk, str(getattr(request, "trace_id", ""))
            ),
            robust=True,
        )
        return _wrapped(request, job, status=202)


class TeachingImportDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_enrollment_import_retrieve",
        responses={200: CourseContentResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str, job_id: str) -> Response:
        try:
            job = (
                EnrollmentImportJob.objects
                .select_related("course")
                .prefetch_related("items__enrollment")
                .get(public_id=job_id, course__public_id=course_id)
            )
        except EnrollmentImportJob.DoesNotExist as exc:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound() from exc
        require_course_capability(
            course=job.course, actor=request.user, capability="MANAGE_ENROLLMENT"
        )
        return _wrapped(request, job)

    @extend_schema(
        operation_id="teaching_enrollment_import_execute",
        request=None,
        responses={202: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, job_id: str) -> Response:
        def operation() -> StoredResponse:
            try:
                job = EnrollmentImportJob.objects.select_related("course").get(
                    public_id=job_id, course__public_id=course_id
                )
            except EnrollmentImportJob.DoesNotExist as exc:
                from apps.core.errors import ResourceNotFound

                raise ResourceNotFound() from exc
            require_course_capability(
                course=job.course, actor=request.user, capability="MANAGE_ENROLLMENT"
            )
            transaction.on_commit(
                lambda: run_enrollment_import.delay(
                    job.public_id, request.user.pk, str(getattr(request, "trace_id", ""))
                ),
                robust=True,
            )
            return StoredResponse(202, _body(request, _data(job)), {})

        return _idempotent_response(request, payload={}, operation=operation)


class TeachingCopyJobView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_course_copy_jobs_create",
        request=CopyWriteSerializer,
        responses={202: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = CopyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            job = create_copy_job(
                course_id=course_id,
                actor=request.user,
                options=serializer.validated_data,
                context=_ctx(request),
            )
            transaction.on_commit(
                lambda: run_copy_job.delay(
                    job.public_id, request.user.pk, str(getattr(request, "trace_id", ""))
                ),
                robust=True,
            )
            return StoredResponse(202, _body(request, _data(job)), {})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TeachingCopyJobDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_course_copy_jobs_retrieve",
        responses={200: CourseContentResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str, job_id: str) -> Response:
        try:
            job = (
                CourseCopyJob.objects
                .select_related("source_course", "target_course")
                .prefetch_related("items")
                .get(public_id=job_id, source_course__public_id=course_id)
            )
        except CourseCopyJob.DoesNotExist as exc:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound() from exc
        require_course_capability(course=job.source_course, actor=request.user, capability="OWNER")
        return _wrapped(request, job)


class TeachingCopyJobExecuteView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_course_copy_jobs_execute",
        request=None,
        responses={202: CourseContentResponseSerializer},
    )
    def post(self, request: HttpRequest, course_id: str, job_id: str) -> Response:
        def operation() -> StoredResponse:
            try:
                job = CourseCopyJob.objects.select_related("source_course").get(
                    public_id=job_id, source_course__public_id=course_id
                )
            except CourseCopyJob.DoesNotExist as exc:
                from apps.core.errors import ResourceNotFound

                raise ResourceNotFound() from exc
            require_course_capability(
                course=job.source_course, actor=request.user, capability="OWNER"
            )
            transaction.on_commit(
                lambda: run_copy_job.delay(
                    job.public_id, request.user.pk, str(getattr(request, "trace_id", ""))
                ),
                robust=True,
            )
            return StoredResponse(202, _body(request, _data(job)), {})

        return _idempotent_response(request, payload={}, operation=operation)


class TeachingPrerequisiteView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_course_prerequisites_list",
        responses={200: CourseContentListResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_course_capability(course=course, actor=request.user, capability="OWNER")
        return _response(
            request,
            [
                {"course_id": row.prerequisite_course.public_id, "status": "NOT_EVALUABLE"}
                for row in course.prerequisites.select_related("prerequisite_course")
            ],
        )

    @extend_schema(
        operation_id="teaching_course_prerequisites_update",
        request=CourseContentResponseSerializer,
        responses={200: CourseContentListResponseSerializer},
    )
    def put(self, request: HttpRequest, course_id: str) -> Response:
        course = visible_course(actor=request.user, portal="TEACHING", course_id=course_id)
        require_course_capability(course=course, actor=request.user, capability="OWNER")
        ids = request.data.get("course_ids", [])
        values = [
            add_course_prerequisite(
                course_id=course_id,
                prerequisite_course_id=str(value),
                actor=request.user,
                context=_ctx(request),
            )
            for value in ids
        ]
        return _list(request, values)


class TeachingChapterPrerequisiteView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_chapter_prerequisites_list",
        responses={200: CourseContentListResponseSerializer},
    )
    def get(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        try:
            chapter = Chapter.objects.get(public_id=chapter_id, course__public_id=course_id)
        except Chapter.DoesNotExist as exc:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound() from exc
        require_course_capability(
            course=chapter.course, actor=request.user, capability="MANAGE_CONTENT"
        )
        return _response(
            request,
            [
                {"chapter_id": row.prerequisite_chapter.public_id, "status": "NOT_EVALUABLE"}
                for row in chapter.prerequisites.select_related("prerequisite_chapter")
            ],
        )

    @extend_schema(
        operation_id="teaching_chapter_prerequisites_update",
        request=CourseContentResponseSerializer,
        responses={200: CourseContentListResponseSerializer},
    )
    def put(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        ids = request.data.get("chapter_ids", [])
        values = [
            add_chapter_prerequisite(
                chapter_id=chapter_id,
                prerequisite_chapter_id=str(value),
                actor=request.user,
                context=_ctx(request),
            )
            for value in ids
        ]
        return _response(
            request, [{"chapter_id": value.prerequisite_chapter.public_id} for value in values]
        )
