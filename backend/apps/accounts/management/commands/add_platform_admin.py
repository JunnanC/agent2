import os
import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import PlatformAdminAssignment, User
from apps.accounts.services import ActorContext, create_user, grant_platform_admin


class Command(BaseCommand):
    help = "Grant platform administrator access from the server console."

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument("--email", required=True)
        parser.add_argument("--username")
        parser.add_argument("--display-name")
        parser.add_argument("--reason", required=True)

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        email = str(options["email"]).strip().casefold()
        context = ActorContext(
            actor_ref="server-operator", portal="SYSTEM", trace_id=secrets.token_hex(16)
        )
        user = User.objects.filter(email=email).first()
        if user is None:
            password = os.getenv("PLATFORM_ADMIN_BOOTSTRAP_PASSWORD", "")
            if not password or not options["username"] or not options["display_name"]:
                raise CommandError(
                    "New accounts require --username, --display-name and "
                    "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD"
                )
            user = create_user(
                email=email,
                username=str(options["username"]),
                display_name=str(options["display_name"]),
                password=password,
                context=context,
            )
        if PlatformAdminAssignment.objects.filter(user=user, status="ACTIVE").exists():
            raise CommandError("This account already has platform administrator access")
        assignment = grant_platform_admin(
            user_public_id=user.public_id,
            reason=str(options["reason"]),
            expected_user_version=user.row_version,
            actor=None,
            context=context,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Granted platform administrator: {assignment.public_id}")
        )
