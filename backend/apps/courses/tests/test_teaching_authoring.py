from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.tests.helpers import create_user
from apps.core.antivirus import AntivirusResult
from apps.core.models import ObjectAsset
from apps.courses.content_services import create_chapter, create_invitation
from apps.courses.models import Chapter, ChapterDraft, Course, Enrollment
from apps.courses.services import ActorContext, apply_for_course
from apps.courses.teaching_crypto import readable_invitation
from apps.courses.teaching_views import (
    TeachingChapterGenerateView,
    TeachingDirectInviteView,
    TeachingInvitationSummaryView,
    TeachingMaterialUploadView,
)

from .helpers import create_draft_course, create_teacher


class TeachingAuthoringTests(TestCase):
    def setUp(self):
        self.owner = create_teacher(suffix="author")
        self.course = create_draft_course(self.owner)
        Course.objects.filter(pk=self.course.pk).update(status="PUBLISHED")
        self.context = ActorContext(self.owner.public_id, "TEACHING", "a" * 32)
        self.student = create_user(email="learner@example.edu", username="learner")
        self.chapter = create_chapter(
            course_id=self.course.public_id,
            actor=self.owner,
            title="环境准备",
            summary="介绍",
            content="完整说明" * 1000,
            position=1,
            context=self.context,
        )

    def call(self, view, data=None, actor=None, method="post", if_match=None, **kwargs):
        factory = APIRequestFactory()
        req = getattr(factory, method)(
            "/api/v2/authoring-test",
            data or {},
            format="multipart" if data and "file" in data else "json",
        )
        req.portal = "TEACHING"
        req.trace_id = "a" * 32
        req.idempotency_key = str(uuid4())
        if if_match is not None:
            req.META["HTTP_IF_MATCH"] = f'"{if_match}"'
        force_authenticate(req, user=actor or self.owner)
        return view.as_view()(req, **kwargs)

    def test_direct_invite_is_active_and_repeat_does_not_duplicate(self):
        for _ in range(2):
            response = self.call(
                TeachingDirectInviteView,
                {"identity": self.student.email},
                course_id=self.course.public_id,
            )
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data["data"]["status"], "ACTIVE")
        self.assertEqual(
            Enrollment.objects.filter(course=self.course, student=self.student).count(), 1
        )

    def test_code_is_encrypted_and_only_owner_summary_reads_full_value(self):
        invitation, raw = create_invitation(
            course_id=self.course.public_id,
            actor=self.owner,
            max_uses=5,
            expires_at=timezone.now() + timedelta(days=1),
            context=self.context,
        )
        self.assertNotIn(raw, invitation.code_encrypted)
        self.assertEqual(readable_invitation(invitation), raw)
        response = self.call(TeachingInvitationSummaryView, method="get")
        self.assertEqual(response.data["data"][self.course.public_id]["code"], raw)
        other = create_teacher(suffix="other-author")
        response = self.call(TeachingInvitationSummaryView, actor=other, method="get")
        self.assertNotIn(self.course.public_id, response.data["data"])
        enrollment = apply_for_course(
            course_id=self.course.public_id,
            student=self.student,
            invitation_code=raw,
            application_message="",
            context=self.context,
        )
        self.assertEqual(enrollment.status, "PENDING")
        self.assertIsNone(enrollment.activated_at)

    @patch("apps.courses.chapter_ai.generate_chapter_content", return_value="生成的教学内容")
    def test_ai_creates_private_draft_without_publishing_chapter(self, generate):
        response = self.call(
            TeachingChapterGenerateView, {"title": "平台导览"}, course_id=self.course.public_id
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ChapterDraft.objects.get().content, "生成的教学内容")
        self.assertEqual(Chapter.objects.count(), 1)
        self.assertEqual(self.chapter.status, "DRAFT")

    @patch(
        "apps.courses.teaching_views.ClamAVScanner.scan", return_value=AntivirusResult(clean=True)
    )
    @patch("apps.courses.teaching_views.object_storage")
    def test_upload_creates_scanned_material_in_selected_chapter(self, storage, scan):
        storage.return_value.put_stream.return_value = SimpleNamespace(version_id="v1")
        response = self.call(
            TeachingMaterialUploadView,
            {
                "title": "准备指南",
                "file": SimpleUploadedFile("guide.txt", b"prepare", "text/plain"),
            },
            course_id=self.course.public_id,
            chapter_id=self.chapter.public_id,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["chapter_id"], self.chapter.public_id)
        self.assertEqual(response.data["data"]["version_status"], "DRAFT")
        self.assertEqual(ObjectAsset.objects.get().scan_status, "CLEAN")
        self.assertEqual(response.data["data"]["asset_name"], "guide.txt")
        self.assertEqual(response.data["data"]["size_bytes"], 7)

    @patch(
        "apps.courses.teaching_views.ClamAVScanner.scan", return_value=AntivirusResult(clean=False)
    )
    def test_rejected_file_never_creates_material_or_asset(self, scan):
        response = self.call(
            TeachingMaterialUploadView,
            {"title": "危险文件", "file": SimpleUploadedFile("guide.txt", b"bad", "text/plain")},
            course_id=self.course.public_id,
            chapter_id=self.chapter.public_id,
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ObjectAsset.objects.exists())
        self.assertFalse(self.course.materials.exists())

    def test_other_teacher_cannot_upload_to_course(self):
        other = create_teacher(suffix="unrelated")
        response = self.call(
            TeachingMaterialUploadView,
            {"title": "guide", "file": SimpleUploadedFile("guide.txt", b"x")},
            actor=other,
            course_id=self.course.public_id,
            chapter_id=self.chapter.public_id,
        )
        self.assertEqual(response.status_code, 403)

    def test_import_course_chapter_copies_into_template_chapter(self):
        from apps.courses.teaching_views import TeachingTemplateChapterImportView
        from apps.labtemplates.tests.helpers import create_template_version

        owner, course, template, version = create_template_version(suffix="chapter-import")
        source = create_chapter(
            course_id=course.public_id,
            actor=owner,
            title="课程章节",
            summary="摘要",
            content="完整教学内容",
            position=1,
            context=ActorContext(owner.public_id, "TEACHING", "a" * 32),
        )
        response = self.call(
            TeachingTemplateChapterImportView,
            {"chapter_id": source.public_id},
            actor=owner,
            course_id=course.public_id,
            version_id=version.public_id,
            if_match=version.row_version,
        )
        self.assertEqual(response.status_code, 201, response.data)
        copied = version.chapters.get(public_id=response.data["data"]["public_id"])
        self.assertEqual(copied.description, source.content)
        self.assertNotEqual(copied.public_id, source.public_id)

    def test_assign_published_experiment_preserves_template_snapshot(self):
        from apps.courses.teaching_views import TeachingExperimentChapterView
        from apps.experiments.tests.helpers import create_domain, create_draft_publication

        owner, course, version, rubric = create_domain(suffix="assign-published")
        source = create_chapter(
            course_id=course.public_id,
            actor=owner,
            title="第一章",
            summary="",
            position=1,
            context=ActorContext(owner.public_id, "TEACHING", "a" * 32),
        )
        publication = create_draft_publication(
            owner=owner,
            course=course,
            template_version=version,
            rubric_version=rubric,
        )
        publication.status = "PUBLISHED"
        publication.publication_digest = "a" * 64
        type(publication).objects.filter(pk=publication.pk).update(
            status="PUBLISHED", publication_digest="a" * 64
        )
        response = self.call(
            TeachingExperimentChapterView,
            {"chapter_id": source.public_id},
            method="patch",
            actor=owner,
            course_id=course.public_id,
            publication_id=publication.public_id,
            if_match=publication.row_version,
        )
        self.assertEqual(response.status_code, 200, response.data)
        publication.refresh_from_db()
        self.assertEqual(publication.course_chapter_id, source.pk)
        self.assertEqual(publication.publication_digest, "a" * 64)
        self.assertEqual(publication.status, "PUBLISHED")
