from django.test import TestCase

from apps.courses.content_services import create_chapter
from apps.courses.tests.helpers import create_draft_course

from ..errors import PublicationValidationError
from ..serializers import publication_data
from ..services import update_publication
from .helpers import context, create_domain, create_draft_publication


class ExperimentCourseChapterTests(TestCase):
    def test_course_chapter_is_separate_from_template_chapters_and_roundtrips(self):
        owner, course, version, rubric = create_domain(suffix="chapter-association")
        chapter = create_chapter(
            course_id=course.public_id,
            actor=owner,
            title="课程第一章",
            summary="介绍",
            position=1,
            context=context(owner),
        )
        publication = create_draft_publication(
            owner=owner,
            course=course,
            template_version=version,
            rubric_version=rubric,
        )
        changed = update_publication(
            course_id=course.public_id,
            publication_id=publication.public_id,
            actor=owner,
            expected_version=publication.row_version,
            data={"course_chapter_id": chapter.public_id},
            context=context(owner),
        )
        self.assertEqual(publication_data(changed)["course_chapter_id"], chapter.public_id)
        self.assertNotEqual(version.chapters.first().public_id, chapter.public_id)

    def test_cross_course_chapter_is_rejected(self):
        owner, course, version, rubric = create_domain(suffix="chapter-reject")
        other = create_draft_course(owner, code="OTHER-CHAPTER-COURSE")
        chapter = create_chapter(
            course_id=other.public_id,
            actor=owner,
            title="其他课程",
            summary="",
            position=1,
            context=context(owner),
        )
        publication = create_draft_publication(
            owner=owner,
            course=course,
            template_version=version,
            rubric_version=rubric,
        )
        with self.assertRaises(PublicationValidationError):
            update_publication(
                course_id=course.public_id,
                publication_id=publication.public_id,
                actor=owner,
                expected_version=publication.row_version,
                data={"course_chapter_id": chapter.public_id},
                context=context(owner),
            )
        publication.refresh_from_db()
        self.assertIsNone(publication.course_chapter_id)
