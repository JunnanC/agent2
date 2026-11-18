from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.accounts.selectors import user_by_login
from apps.accounts.services import ActorContext, authenticate_credentials
from apps.accounts.student_import_views import PlatformStudentImportView
from apps.accounts.student_imports import import_students
from apps.core.models import IdempotencyRecord

from .helpers import create_user, grant_admin

HEADER = "student_number,email,display_name,password\n"
PASSWORD = "Student-2026!abc"


class StudentImportTests(TestCase):
    def setUp(self):
        self.admin = create_user()
        grant_admin(self.admin)
        self.context = ActorContext(self.admin.public_id, "PLATFORM", "a" * 32)

    @patch("apps.accounts.services.enqueue_relay_after_commit")
    def test_mixed_batch_duplicate_password_and_login_compatibility(self, relay):
        rows = import_students(
            csv_payload=HEADER
            + (
                f"2026001,one@example.edu,One,{PASSWORD}\n"
                f"2026001,two@example.edu,Duplicate,{PASSWORD}\n"
                "2026002,two@example.edu,Weak,short\n"
                f"2026003,three@example.edu,Three,{PASSWORD}\n"
            ),
            context=self.context,
        )
        assert [row["status"] for row in rows] == ["CREATED", "FAILED", "FAILED", "CREATED"]
        assert rows[1]["error"] == "duplicate_identifier"
        assert PASSWORD not in str(rows)
        user = User.objects.get(student_number="2026001")
        for identifier in ("2026001", "one@example.edu"):
            assert authenticate_credentials(identifier, PASSWORD) == user
        assert user_by_login(self.admin.email) == self.admin
        assert user_by_login(self.admin.username) == self.admin
        assert not User.objects.filter(student_number="2026002").exists()

    def test_ambiguous_legacy_identity_fails_closed(self):
        other = create_user(email="other@example.edu", username="other")
        User.objects.filter(pk=other.pk).update(student_number=self.admin.username)
        assert user_by_login(self.admin.username) is None

    def test_api_permissions_and_idempotent_replay(self):
        factory = APIRequestFactory()
        payload = {"csv": HEADER + f"2026010,new@example.edu,New,{PASSWORD}\n"}

        def request(portal, key):
            req = factory.post("/api/v2/platform/student-imports", payload, format="json")
            req.portal = portal
            req.trace_id = "a" * 32
            req.idempotency_key = key
            force_authenticate(req, user=self.admin)
            return PlatformStudentImportView.as_view()(req)

        assert request("USER", "wrong-portal").status_code == 403
        with patch("apps.accounts.services.enqueue_relay_after_commit"):
            first = request("PLATFORM", "batch-1")
            second = request("PLATFORM", "batch-1")
        assert first.status_code == second.status_code == 200
        assert first.data == second.data
        assert User.objects.filter(student_number="2026010").count() == 1
        assert PASSWORD not in str(list(IdempotencyRecord.objects.values()))

    def test_bad_headers_and_size_reject_without_creating_accounts(self):
        from rest_framework.exceptions import ValidationError

        for csv in ("email,password\nx@y.edu,test", HEADER, HEADER + "x,y,z,p\n" * 501):
            with self.assertRaises(ValidationError):
                import_students(csv_payload=csv, context=self.context)
        assert User.objects.count() == 1
