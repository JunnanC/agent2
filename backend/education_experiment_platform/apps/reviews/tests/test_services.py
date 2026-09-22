from decimal import Decimal

from django.test import TestCase

from apps.courses.services import ActorContext
from apps.courses.tests.helpers import create_draft_course, create_teacher

from ..errors import RubricStateConflict, RubricValidationError
from ..models import RubricCriterion, RubricVersion
from ..services import (
    clone_rubric_version,
    create_rubric,
    create_rubric_version,
    publish_rubric_version,
    update_rubric_version,
)


def criterion(position: int, title: str, score: str, weight: int) -> dict[str, object]:
    return {
        "position": position,
        "title": title,
        "description": "",
        "guidance": "",
        "max_score": score,
        "weight_basis_points": weight,
    }


class RubricServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner = create_teacher(suffix="rubric-owner")
        self.course = create_draft_course(self.owner, code="RUBRIC-COURSE")
        self.context = ActorContext(self.owner.public_id, "TEACHING", "u" * 32)
        self.rubric = create_rubric(
            course_id=self.course.public_id,
            actor=self.owner,
            name="Lab Review",
            description="Frozen scoring definition",
            context=self.context,
        )

    def _version(self) -> RubricVersion:
        return create_rubric_version(
            course_id=self.course.public_id,
            rubric_id=self.rubric.public_id,
            actor=self.owner,
            title="Version 1",
            description="",
            total_score=Decimal("100.00"),
            criteria=[
                criterion(1, "Correctness", "60.00", 6000),
                criterion(2, "Quality", "40.00", 4000),
            ],
            context=self.context,
        )

    def test_publish_is_immutable_and_clone_returns_new_draft(self) -> None:
        version = self._version()
        published = publish_rubric_version(
            course_id=self.course.public_id,
            version_id=version.public_id,
            actor=self.owner,
            expected_version=version.row_version,
            context=self.context,
        )
        self.assertEqual(published.status, RubricVersion.Status.PUBLISHED)
        with self.assertRaises(RubricStateConflict):
            update_rubric_version(
                course_id=self.course.public_id,
                version_id=published.public_id,
                actor=self.owner,
                expected_version=published.row_version,
                title="Changed",
                description="",
                total_score=Decimal("100"),
                criteria=[criterion(1, "Only", "100", 10000)],
                context=self.context,
            )
        clone = clone_rubric_version(
            course_id=self.course.public_id,
            rubric_id=self.rubric.public_id,
            source_version_id=published.public_id,
            actor=self.owner,
            context=self.context,
        )
        self.assertEqual(clone.status, RubricVersion.Status.DRAFT)
        self.assertNotEqual(clone.public_id, published.public_id)
        self.assertEqual(clone.criteria.filter(is_active=True).count(), 2)

    def test_publish_rejects_weight_and_score_mismatch(self) -> None:
        version = create_rubric_version(
            course_id=self.course.public_id,
            rubric_id=self.rubric.public_id,
            actor=self.owner,
            title="Invalid",
            description="",
            total_score=Decimal("100"),
            criteria=[criterion(1, "Wrong weight", "90", 9000)],
            context=self.context,
        )
        with self.assertRaises(RubricValidationError):
            publish_rubric_version(
                course_id=self.course.public_id,
                version_id=version.public_id,
                actor=self.owner,
                expected_version=version.row_version,
                context=self.context,
            )

    def test_position_validation_and_history_preservation(self) -> None:
        with self.assertRaises(RubricValidationError):
            create_rubric_version(
                course_id=self.course.public_id,
                rubric_id=self.rubric.public_id,
                actor=self.owner,
                title="Duplicate",
                description="",
                total_score=Decimal("20"),
                criteria=[
                    criterion(1, "A", "10", 5000),
                    criterion(1, "B", "10", 5000),
                ],
                context=self.context,
            )
        version = self._version()
        first_ids = set(version.criteria.values_list("public_id", flat=True))
        changed = update_rubric_version(
            course_id=self.course.public_id,
            version_id=version.public_id,
            actor=self.owner,
            expected_version=version.row_version,
            title="Version 1 revised",
            description="",
            total_score=Decimal("100"),
            criteria=[criterion(1, "Single", "100", 10000)],
            context=self.context,
        )
        self.assertEqual(changed.criteria.filter(is_active=True).count(), 1)
        self.assertEqual(
            RubricCriterion.objects.filter(public_id__in=first_ids, is_active=False).count(), 2
        )
