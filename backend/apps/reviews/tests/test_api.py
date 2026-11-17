from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.courses.services import ActorContext
from apps.courses.tests.helpers import create_draft_course, create_teacher

from ..models import RubricCriterion, RubricVersion
from ..services import create_rubric
from ..views import RubricVersionListView


class RubricIdempotencyTests(TestCase):
    def test_version_bulk_create_replays_without_duplicate_criteria(self) -> None:
        owner = create_teacher(suffix="rubric-idempotency")
        course = create_draft_course(owner, code="RUBRIC-IDEMPOTENCY")
        rubric = create_rubric(
            course_id=course.public_id, actor=owner, name="Rubric", description="",
            context=ActorContext(owner.public_id, "TEACHING", "r" * 32),
        )
        url = f"/api/v2/teaching/courses/{course.public_id}/rubrics/{rubric.public_id}/versions"
        payload = {
            "title": "Version", "total_score": "100.00",
            "criteria": [{"position": 1, "title": "Correctness", "max_score": "100.00",
                          "weight_basis_points": 10000}],
        }

        def post(data):
            request = APIRequestFactory().post(url, data, format="json")
            force_authenticate(request, user=owner)
            request.portal = "TEACHING"
            request.trace_id = "r" * 32
            request.idempotency_key = "rubric-version-replay"
            return RubricVersionListView.as_view()(
                request, course_id=course.public_id, rubric_id=rubric.public_id,
            )

        first = post(payload)
        self.assertEqual(first.status_code, 201, first.data)
        replay = post(payload)
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(replay["X-Idempotent-Replayed"], "true")
        self.assertEqual(first.data, replay.data)
        self.assertEqual(RubricVersion.objects.count(), 1)
        self.assertEqual(RubricCriterion.objects.count(), 1)
        conflict = post({**payload, "title": "Different version"})
        self.assertEqual(conflict.status_code, 422, conflict.data)
        self.assertEqual(conflict.data["error"]["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(RubricCriterion.objects.count(), 1)
