from django.core.management.base import BaseCommand

from apps.reviews.services import purge_expired_similarity_evidence


class Command(BaseCommand):
    help = "Redact expired review similarity evidence while preserving run facts."

    def handle(self, *args: object, **options: object) -> None:
        self.stdout.write(str(purge_expired_similarity_evidence()))
