"""Teacher chapter authoring and course-scoped attachments."""

import hashlib
import io
from pathlib import PurePath

from django.conf import settings
from django.db import transaction
from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsTeachingPortal
from apps.core.antivirus import AntivirusUnavailable, ClamAVScanner
from apps.core.assets import register_asset, set_scan_result
from apps.core.concurrency import parse_if_match
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import StoredResponse
from apps.core.identifiers import new_ulid
from apps.core.object_storage import iter_chunks, object_storage

from .content_serializers import ContentWriteSerializer, CourseContentResponseSerializer
from .content_services import _staff_course, create_material, update_chapter
from .content_views import _data
from .models import Chapter, ChapterDraft, Enrollment, Invitation
from .serializers import enrollment_data
from .services import apply_for_course, review_enrollment
from .views import _body, _context, _idempotent_response


class TeachingInvitationSummaryView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=CourseContentResponseSerializer)
    def get(self, request):
        from django.utils import timezone

        from .teaching_crypto import readable_invitation
        from .views import _response

        # Only course owners receive full codes in this cross-course summary.
        values = (
            Invitation.objects
            .filter(
                course__owner=request.user,
                status="ACTIVE",
                expires_at__gt=timezone.now(),
                used_count__lt=F("max_uses"),
            )
            .select_related("course")
            .order_by("-created_at")
        )
        result = {}
        for item in values:
            if item.course.public_id not in result:
                result[item.course.public_id] = {
                    "code": readable_invitation(item),
                    "recoverable": bool(item.code_encrypted),
                    "expires_at": item.expires_at,
                }
        response = _response(request, result)
        response["Cache-Control"] = "private, no-store"
        return response


class DirectInviteSerializer(serializers.Serializer):
    identity = serializers.CharField(max_length=254)


class TeachingDirectInviteView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(request=DirectInviteSerializer, responses=CourseContentResponseSerializer)
    def post(self, request, course_id):
        serializer = DirectInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identity = serializer.validated_data["identity"].strip()

        def operation():
            course = _staff_course(course_id, request.user, "MANAGE_ENROLLMENT")
            user = User.objects.filter(email__iexact=identity).first()
            user = user or User.objects.filter(username__iexact=identity).first()
            if user is None or user.registration_role != User.RegistrationRole.STUDENT:
                raise ValidationError({"identity": "请输入有效学生的账号或邮箱"})
            existing = Enrollment.objects.filter(
                course=course,
                student=user,
                status__in=("ACTIVE", "PENDING"),
            ).first()
            if existing and existing.status == "PENDING":
                enrollment = review_enrollment(
                    course_id=course_id,
                    enrollment_id=existing.public_id,
                    decision="APPROVE",
                    note="教师直接邀请",
                    actor=request.user,
                    expected_version=existing.row_version,
                    context=_context(request),
                )
            elif existing:
                enrollment = existing
            else:
                enrollment = apply_for_course(
                    course_id=course_id,
                    student=user,
                    invited_by=request.user,
                    application_message="教师直接邀请",
                    context=_context(request),
                )
            return StoredResponse(201, _body(request, enrollment_data(enrollment)), {})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TeachingChapterDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(request=ContentWriteSerializer, responses=CourseContentResponseSerializer)
    def patch(self, request, course_id, chapter_id):
        course = _staff_course(course_id, request.user, "MANAGE_CONTENT")
        if not Chapter.objects.filter(public_id=chapter_id, course=course).exists():
            raise ResourceNotFound()
        serializer = ContentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation():
            item = update_chapter(
                chapter_id=chapter_id,
                actor=request.user,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                changes=serializer.validated_data,
                context=_context(request),
            )
            return StoredResponse(200, _body(request, _data(item)), {})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class MaterialUploadSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    file = serializers.FileField()


class TeachingMaterialUploadView(APIView):
    permission_classes = [IsTeachingPortal]
    parser_classes = [MultiPartParser]

    @extend_schema(request=MaterialUploadSerializer, responses=CourseContentResponseSerializer)
    def post(self, request, course_id, chapter_id):
        course = _staff_course(course_id, request.user, "MANAGE_CONTENT")
        if not Chapter.objects.filter(public_id=chapter_id, course=course).exists():
            raise ResourceNotFound()
        serializer = MaterialUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        if uploaded.size > 10 * 1024 * 1024:
            raise ValidationError({"file": "附件不能超过 10 MB"})
        suffix = PurePath(uploaded.name).suffix.lower()
        if suffix not in {
            ".pdf",
            ".docx",
            ".pptx",
            ".xlsx",
            ".txt",
            ".md",
            ".csv",
            ".png",
            ".jpg",
            ".jpeg",
        }:
            raise ValidationError({"file": "不支持此文件类型"})
        content = uploaded.read(10 * 1024 * 1024 + 1)
        digest = hashlib.sha256(content).hexdigest()

        def operation():
            try:
                result = ClamAVScanner().scan(iter_chunks(io.BytesIO(content)))
            except AntivirusUnavailable as exc:
                raise ValidationError({"file": "附件扫描暂不可用，请稍后重试"}) from exc
            if not result.clean:
                raise ValidationError({"file": "附件未通过安全扫描"})
            storage = object_storage()
            bucket = settings.MINIO_BUCKET
            key = f"course-materials/{course_id}/{new_ulid()}{suffix}"
            media = uploaded.content_type or "application/octet-stream"
            stored = storage.put_stream(
                bucket=bucket,
                object_key=key,
                stream=io.BytesIO(content),
                media_type=media,
            )
            try:
                with transaction.atomic():
                    asset = register_asset(
                        bucket=bucket,
                        object_key=key,
                        object_version=stored.version_id,
                        digest_sha256=digest,
                        size_bytes=len(content),
                        owner_type="COURSE_ATTACHMENT",
                        owner_ref=course.public_id,
                        purpose="MANUAL",
                        media_type=media,
                        original_name=uploaded.name,
                    )
                    set_scan_result(
                        asset_id=asset.pk, expected_version=asset.row_version, scan_status="CLEAN"
                    )
                    material = create_material(
                        course_id=course_id,
                        actor=request.user,
                        chapter_id=chapter_id,
                        title=serializer.validated_data["title"],
                        kind="FILE",
                        text_content="",
                        link_url="",
                        asset_id=asset.public_id,
                        context=_context(request),
                    )
            except Exception:
                storage.delete_object(bucket=bucket, object_key=key, version_id=stored.version_id)
                raise
            return StoredResponse(201, _body(request, _data(material)), {})

        return _idempotent_response(
            request,
            payload={
                "chapter_id": chapter_id,
                "title": serializer.validated_data["title"],
                "digest": digest,
            },
            operation=operation,
        )


class ChapterGenerateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)


class TeachingChapterGenerateView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(request=ChapterGenerateSerializer, responses=CourseContentResponseSerializer)
    def post(self, request, course_id):
        course = _staff_course(course_id, request.user, "MANAGE_CONTENT")
        serializer = ChapterGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation():
            from .chapter_ai import generate_chapter_content

            title = serializer.validated_data["title"]
            content = generate_chapter_content(course_title=course.title, title=title)
            draft = ChapterDraft.objects.create(
                course=course,
                created_by=request.user,
                title=title,
                content=content,
            )
            return StoredResponse(
                201,
                _body(
                    request,
                    {"public_id": draft.public_id, "title": title, "content": draft.content},
                ),
                {},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TemplateChapterImportSerializer(serializers.Serializer):
    chapter_id = serializers.CharField(max_length=26)


class TeachingExperimentChapterView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=TemplateChapterImportSerializer, responses=CourseContentResponseSerializer
    )
    def patch(self, request, course_id, publication_id):
        from apps.core.concurrency import compare_and_swap
        from apps.experiments.models import TaskPublication
        from apps.experiments.serializers import publication_data
        from apps.experiments.services import _audit

        course = _staff_course(course_id, request.user, "PUBLISH_EXPERIMENT")
        serializer = TemplateChapterImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation():
            try:
                publication = TaskPublication.objects.select_for_update().get(
                    public_id=publication_id,
                    course=course,
                )
                chapter = Chapter.objects.get(
                    public_id=serializer.validated_data["chapter_id"],
                    course=course,
                )
            except (TaskPublication.DoesNotExist, Chapter.DoesNotExist) as exc:
                raise ResourceNotFound() from exc
            changed = compare_and_swap(
                TaskPublication,
                pk=publication.pk,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                changes={"course_chapter": chapter},
            )
            _audit(
                context=_context(request),
                actor=request.user,
                action="experiment.chapter.assign",
                target_type="task_publication",
                target_ref=publication.public_id,
                course_ref=course_id,
                after={"course_chapter_id": chapter.public_id},
            )
            return StoredResponse(200, _body(request, publication_data(changed)), {})

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class TeachingTemplateChapterImportView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=TemplateChapterImportSerializer, responses=CourseContentResponseSerializer
    )
    def post(self, request, course_id, version_id):
        from apps.labtemplates.services import create_chapter

        course = _staff_course(course_id, request.user, "MANAGE_TEMPLATE")
        serializer = TemplateChapterImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation():
            try:
                chapter = Chapter.objects.get(
                    public_id=serializer.validated_data["chapter_id"], course=course
                )
            except Chapter.DoesNotExist as exc:
                raise ResourceNotFound() from exc
            item = create_chapter(
                course_id=course_id,
                actor=request.user,
                version_id=version_id,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                data={"title": chapter.title, "description": chapter.content or chapter.summary},
                context=_context(request),
            )
            return StoredResponse(
                201, _body(request, {"public_id": item.public_id, "title": item.title}), {}
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)
