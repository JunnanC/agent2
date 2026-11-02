from django.core.management.base import BaseCommand

from apps.core.seed_names import rename_seed_labels


class Command(BaseCommand):
    help = "Replace phase numbers in disposable seed display names with business names."

    def handle(self, *args: object, **options: object) -> None:
        changed = rename_seed_labels()
        self.stdout.write(self.style.SUCCESS(f"Updated {changed} seed display names."))
