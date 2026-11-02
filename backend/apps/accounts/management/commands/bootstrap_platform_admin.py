import os
import secrets

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import PlatformAdminAssignment, User
from apps.accounts.services import ActorContext, create_user, grant_platform_admin
from apps.core.concurrency import compare_and_swap


class Command(BaseCommand):
    help = "Create the first platform administrator without shipping default credentials."

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument("--email", required=True)
        parser.add_argument("--username", required=True)
        parser.add_argument("--display-name", required=True)

    def handle(self, *args: object, **options: object) -> None:
        existing = (
            PlatformAdminAssignment.objects.filter(status=PlatformAdminAssignment.Status.ACTIVE)
            .select_related("user")
            .first()
        )
        if existing:
            self.stdout.write(
                self.style.SUCCESS(
                    f"An active platform administrator already exists: {existing.user.public_id}"
                )
            )
            return
        password = os.getenv("PLATFORM_ADMIN_BOOTSTRAP_PASSWORD", "")
        if not password:
            raise CommandError("PLATFORM_ADMIN_BOOTSTRAP_PASSWORD is required")
        trace_id = secrets.token_hex(16)
        context = ActorContext(actor_ref="system", portal="SYSTEM", trace_id=trace_id)
        user = User.objects.filter(email=str(options["email"]).strip().casefold()).first()
        if user is None:
            user = create_user(
                email=str(options["email"]),
                username=str(options["username"]),
                display_name=str(options["display_name"]),
                password=password,
                context=context,
            )
        elif user.account_status != User.AccountStatus.ACTIVE:
            user = compare_and_swap(
                User,
                pk=user.pk,
                expected_version=user.row_version,
                changes={
                    "account_status": User.AccountStatus.ACTIVE,
                    "is_active": True,
                    "security_version": user.security_version + 1,
                },
            )  # type: ignore[assignment]
        assignment = grant_platform_admin(
            user_public_id=user.public_id,
            reason="Initial platform administrator bootstrap",
            expected_user_version=user.row_version,
            actor=user,
            context=context,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Bootstrapped platform administrator {user.public_id} ({assignment.public_id})"
            )
        )
