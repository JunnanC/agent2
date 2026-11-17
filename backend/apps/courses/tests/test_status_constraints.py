from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from ..models import Answer, CalendarEvent, CourseCopyItem, CourseCopyJob, Invitation, Question
from .helpers import create_draft_course, create_teacher


class ContentStatusConstraintTests(TestCase):
    def test_bulk_inserts_enforce_status_constraints(self) -> None:
        owner = create_teacher(suffix="status-constraints")
        course = create_draft_course(owner)
        question = Question.objects.create(
            course=course, author=owner, title="Question", body="Body",
        )
        job = CourseCopyJob.objects.create(source_course=course, created_by=owner)
        now = timezone.now()
        cases = [
            (CalendarEvent, {"course": course, "created_by": owner, "title": "Event",
                             "starts_at": now, "ends_at": now + timedelta(hours=1)},
             ("ACTIVE", "CANCELLED")),
            (Answer, {"question": question, "author": owner, "body": "Answer"},
             ("VISIBLE", "HIDDEN")),
            (Invitation, {"course": course, "created_by": owner, "expires_at": now,
                          "code_masked": "***"}, ("ACTIVE", "REVOKED")),
            (CourseCopyItem, {"job": job, "item_type": "CHAPTER", "source_ref": "source"},
             ("PENDING", "SUCCEEDED", "FAILED")),
        ]
        for model, fields, statuses in cases:
            for status in (*statuses, "INVALID"):
                with self.subTest(model=model.__name__, status=status):
                    values = {**fields, "status": status}
                    if model is Invitation:
                        values["code_digest"] = status
                    if status == "INVALID":
                        with self.assertRaises(IntegrityError), transaction.atomic():
                            model.objects.bulk_create([model(**values)])
                    else:
                        model.objects.bulk_create([model(**values)])
