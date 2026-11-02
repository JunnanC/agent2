import json

from django.core.management.base import BaseCommand

from apps.core.compensation import claim_compensations, run_compensation

from ...services import reconcile_archives, scan_due_tasks


class Command(BaseCommand):
    help = "Run the task-deadline, archive, runtime, and compensation reconciliation once."

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument("--trace-id", default="archive-maintenance")

    def handle(self, *args: object, **options: object) -> None:
        trace_id = str(options["trace_id"])
        due = scan_due_tasks(trace_id=trace_id)
        result = reconcile_archives(trace_id=trace_id)
        compensations = 0
        for task_id in claim_compensations():
            run_compensation(task_id)
            compensations += 1
        self.stdout.write(
            json.dumps(
                {"due_tasks": due, "compensations": compensations, **result},
                sort_keys=True,
            )
        )
