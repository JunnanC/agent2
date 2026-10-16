import json

from django.core.management.base import BaseCommand

from apps.labtemplates.image_services import validate_experiment_image
from apps.labtemplates.models import ExperimentImage


class Command(BaseCommand):
    help = "Report experiment images whose governed digest is not locally revalidated."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument("--image-id", default="")

    def handle(self, *args: object, **options: object) -> None:
        image_id = str(options.get("image_id") or "").strip()
        queryset = ExperimentImage.objects.order_by("id")
        if image_id:
            queryset = queryset.filter(public_id=image_id)
        valid = 0
        invalid = 0
        rows: list[dict[str, object]] = []
        for image in queryset.iterator():
            try:
                is_valid = validate_experiment_image(image_id=image.public_id)
            except ExperimentImage.DoesNotExist:
                is_valid = False
            if is_valid:
                valid += 1
            else:
                invalid += 1
            rows.append(
                {
                    "image_id": image.public_id,
                    "status": image.status,
                    "resolved_digest": image.resolved_digest,
                    "valid": is_valid,
                }
            )
        self.stdout.write(
            json.dumps(
                {"valid": valid, "invalid": invalid, "images": rows},
                ensure_ascii=False,
            )
        )
