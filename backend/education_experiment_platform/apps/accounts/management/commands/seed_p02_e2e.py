import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import PlatformAdminAssignment, TeacherQualification, User
from apps.accounts.services import ActorContext, create_user, grant_teacher_qualification


class Command(BaseCommand):
    help = "Create disposable P02 browser-test identities in a local/integration environment."

    def handle(self, *args: object, **options: object) -> None:
        if os.getenv("APP_ENV", "") not in {"local", "integration", "test"} and not settings.DEBUG:
            raise CommandError("P02 E2E identities are restricted to disposable environments")
        password = os.getenv("P02_E2E_PASSWORD", "")
        if not password:
            raise CommandError("P02_E2E_PASSWORD is required")
        admin_assignment = (
            PlatformAdminAssignment.objects.select_related("user")
            .filter(status=PlatformAdminAssignment.Status.ACTIVE)
            .first()
        )
        if admin_assignment is None:
            raise CommandError("Bootstrap a platform administrator before creating E2E identities")
        actor = admin_assignment.user
        context = ActorContext(actor.public_id, "PLATFORM", secrets.token_hex(16))
        for email, username, display_name in (
            ("student.integration@example.edu", "integration-student", "Integration Student"),
            ("teacher.integration@example.edu", "integration-teacher", "Integration Teacher"),
        ):
            if not User.objects.filter(email=email).exists():
                create_user(
                    email=email,
                    username=username,
                    display_name=display_name,
                    password=password,
                    context=context,
                )
        teacher = User.objects.get(email="teacher.integration@example.edu")
        if not TeacherQualification.objects.filter(
            user=teacher, status=TeacherQualification.Status.ACTIVE
        ).exists():
            grant_teacher_qualification(
                user_public_id=teacher.public_id,
                reason="P02 disposable E2E seed",
                expected_user_version=teacher.row_version,
                actor=actor,
                context=context,
            )
        self.stdout.write(self.style.SUCCESS("P02 disposable E2E identities are ready."))
