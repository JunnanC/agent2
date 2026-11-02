from unittest.mock import patch

from django.test import TestCase

from apps.accounts.errors import LastPlatformAdminProtected, VerificationStateConflict
from apps.accounts.models import (
    IdentityVerification,
    PlatformAdminAssignment,
    PlatformAdminAssignmentEvent,
    TeacherQualificationEvent,
)
from apps.accounts.services import (
    ActorContext,
    grant_platform_admin,
    review_identity_verification,
    revoke_platform_admin,
    update_identity_verification,
)
from apps.core.models import AuditLog, OutboxEvent

from .helpers import create_user, grant_admin


class AccountServiceTests(TestCase):
    def setUp(self) -> None:
        self.admin = create_user(
            email="admin@example.edu",
            username="admin",
            display_name="Admin",
        )
        self.assignment = grant_admin(self.admin)
        self.context = ActorContext(
            actor_ref=self.admin.public_id,
            portal="PLATFORM",
            trace_id="a" * 32,
        )

    def test_identity_number_is_only_stored_as_hmac_and_mask(self) -> None:
        student = create_user(email="student@example.edu", username="student")
        raw_number = "110101200101011234"
        changed = update_identity_verification(
            user=student,
            identity_type="SCHOOL",
            organization_name="Example University",
            identity_number=raw_number,
            material_asset_id="",
            submit=True,
            expected_version=1,
            context=ActorContext(student.public_id, "USER", "b" * 32),
        )

        self.assertEqual(changed.status, IdentityVerification.Status.SUBMITTED)
        self.assertEqual(len(changed.identity_number_hmac), 64)
        self.assertNotEqual(changed.identity_number_hmac, raw_number)
        self.assertNotIn(raw_number, changed.identity_number_masked)
        self.assertNotIn(raw_number, str(AuditLog.objects.values_list("after_masked", flat=True)))
        self.assertNotIn(raw_number, str(OutboxEvent.objects.values_list("payload", flat=True)))

    def test_review_requires_submitted_state(self) -> None:
        student = create_user(email="student@example.edu", username="student")

        with self.assertRaises(VerificationStateConflict):
            review_identity_verification(
                verification_public_id=student.identity_verification.public_id,
                decision="APPROVE",
                reason="",
                expected_version=1,
                actor=self.admin,
                context=self.context,
            )

    def test_last_admin_is_protected_and_events_are_appended(self) -> None:
        with self.assertRaises(LastPlatformAdminProtected):
            revoke_platform_admin(
                assignment_public_id=self.assignment.public_id,
                reason="test",
                expected_version=1,
                actor=self.admin,
                context=self.context,
            )

        second = create_user(email="second@example.edu", username="second")
        granted = grant_platform_admin(
            user_public_id=second.public_id,
            reason="test",
            expected_user_version=1,
            actor=self.admin,
            context=self.context,
        )
        revoked = revoke_platform_admin(
            assignment_public_id=granted.public_id,
            reason="test",
            expected_version=1,
            actor=self.admin,
            context=self.context,
        )

        self.assertEqual(revoked.status, PlatformAdminAssignment.Status.REVOKED)
        self.assertEqual(PlatformAdminAssignmentEvent.objects.filter(assignment=granted).count(), 2)
        self.assertEqual(TeacherQualificationEvent.objects.count(), 0)

    @patch("apps.core.tasks.relay_outbox.apply_async")
    def test_outbox_enqueue_only_runs_after_commit(self, apply_async) -> None:  # type: ignore[no-untyped-def]
        second = create_user(email="second@example.edu", username="second")
        with self.captureOnCommitCallbacks(execute=True):
            grant_platform_admin(
                user_public_id=second.public_id,
                reason="test",
                expected_user_version=1,
                actor=self.admin,
                context=self.context,
            )
        apply_async.assert_called()
