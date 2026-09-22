import secrets

from django.core.management.base import BaseCommand

from apps.governance.tasks import run_maintenance


class Command(BaseCommand):
    help = "Run one P04 maintenance pass without enabling a persistent beat scheduler."

    def handle(self, *args: object, **options: object) -> None:
        result = run_maintenance.run(trace_id=secrets.token_hex(16))
        self.stdout.write(self.style.SUCCESS(str(result)))
