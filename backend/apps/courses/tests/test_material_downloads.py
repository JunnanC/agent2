from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user
from apps.core.downloads import create_download_grant
from apps.core.errors import DownloadScopeDenied
from apps.core.models import ObjectAsset

from ..content_services import (
    change_chapter_status,
    change_material_version_status,
    create_chapter,
    create_material,
)
from ..models import Enrollment, MaterialVersion
from ..services import ActorContext
from .helpers import create_draft_course, create_teacher


class CourseMaterialDownloadTests(TestCase):
    def test_only_active_students_can_download_current_published_materials(self) -> None:
        teacher = create_teacher(suffix="material-download")
        course = create_draft_course(teacher)
        student = create_user(email="material-student@example.edu", username="material-student")
        enrollment = Enrollment.objects.create(
            course=course, student=student, cycle_no=1,
            status=Enrollment.Status.ACTIVE, applied_at=timezone.now(),
        )
        context = ActorContext(teacher.public_id, "TEACHING", "a" * 32)
        chapter = create_chapter(
            course_id=course.public_id, actor=teacher, title="资料", summary="",
            position=1, context=context,
        )
        change_chapter_status(
            chapter_id=chapter.public_id, actor=teacher,
            expected_version=chapter.row_version, status="PUBLISHED", context=context,
        )
        asset = ObjectAsset.objects.create(
            bucket="test", object_key="template-assets/manual.pdf", digest_sha256="a" * 64,
            size_bytes=10, owner_type="TEMPLATE_VERSION", owner_ref="template-version",
            purpose="MANUAL", scan_status="CLEAN",
        )
        material = create_material(
            course_id=course.public_id, actor=teacher, chapter_id=chapter.public_id,
            title="报告模板", kind="FILE", text_content="", link_url="",
            asset_id=asset.public_id, context=context,
        )
        with self.assertRaises(DownloadScopeDenied):
            create_download_grant(
                asset_id=asset.public_id, actor=student, portal="USER", trace_id="a" * 32,
            )
        change_material_version_status(
            version_id=material.current_version.public_id, actor=teacher,
            expected_version=material.current_version.row_version,
            status="PUBLISHED", context=context,
        )
        grant, token = create_download_grant(
            asset_id=asset.public_id, actor=student, portal="USER", trace_id="a" * 32,
        )
        self.assertEqual(grant.course_ref, course.public_id)
        self.assertTrue(token)
        Enrollment.objects.filter(pk=enrollment.pk).update(status="DROPPED")
        with self.assertRaises(DownloadScopeDenied):
            create_download_grant(
                asset_id=asset.public_id, actor=student, portal="USER", trace_id="a" * 32,
            )
        Enrollment.objects.filter(pk=enrollment.pk).update(status="ACTIVE")
        MaterialVersion.objects.filter(pk=material.current_version.pk).update(status="WITHDRAWN")
        with self.assertRaises(DownloadScopeDenied):
            create_download_grant(
                asset_id=asset.public_id, actor=student, portal="USER", trace_id="a" * 32,
            )
