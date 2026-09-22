from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import PlatformAdminAssignmentEvent, TeacherQualificationEvent
from apps.core.errors import ImmutableRecordError

from .helpers import create_user, grant_admin, grant_teacher


class AccountModelTests(TestCase):
    def test_public_ids_are_ulids_and_user_has_no_global_role(self) -> None:
        user = create_user()

        self.assertEqual(len(user.public_id), 26)
        self.assertNotIn("role", {field.name for field in user._meta.fields})
        self.assertEqual(user.identity_verification.status, "DRAFT")

    def test_qualification_events_are_append_only(self) -> None:
        user = create_user()
        teacher = grant_teacher(user)
        admin = grant_admin(user)
        teacher_event = TeacherQualificationEvent.objects.create(
            qualification=teacher,
            to_status="ACTIVE",
            actor=user,
            reason="test",
            trace_id="a" * 32,
        )
        admin_event = PlatformAdminAssignmentEvent.objects.create(
            assignment=admin,
            to_status="ACTIVE",
            actor=user,
            reason="test",
            trace_id="b" * 32,
        )

        with self.assertRaises(ImmutableRecordError):
            TeacherQualificationEvent.objects.filter(pk=teacher_event.pk).update(reason="changed")
        with self.assertRaises(ImmutableRecordError):
            PlatformAdminAssignmentEvent.objects.filter(pk=admin_event.pk).delete()

    def test_account_status_database_constraint_matches_is_active(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_user(email="bad@example.edu", username="bad").__class__.objects.create(
                email="bad2@example.edu",
                username="bad2",
                display_name="Bad",
                password="encoded",
                account_status="DISABLED",
                is_active=True,
            )
