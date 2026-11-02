from django.core.management.base import BaseCommand

from apps.core.outbox import claim_deliveries, deliver_claimed


class Command(BaseCommand):
    help = "Relay pending MySQL outbox deliveries to the configured Redis Stream."

    def handle(self, *args: object, **options: object) -> None:
        delivered = 0
        for delivery_id in claim_deliveries():
            deliver_claimed(delivery_id)
            delivered += 1
        self.stdout.write(self.style.SUCCESS(f"Relayed {delivered} outbox deliveries."))
