import json
import secrets
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.core.concurrency import compare_and_swap
from apps.courses.services import ActorContext
from apps.governance.models import QuotaReservation, RuntimeAdapter
from apps.governance.services import release_reservation

from ...adapters import runtime_for_driver
from ...models import ProvisioningInstance, ProvisioningJob
from ...ports import RuntimeInventoryItem
from ...services import release_runtime_capacity

TERMINAL_INSTANCE_STATUSES = frozenset(
    {
        ProvisioningInstance.Status.DESTROYED,
        ProvisioningInstance.Status.FAILED,
        ProvisioningInstance.Status.ORPHANED,
    }
)


class Command(BaseCommand):
    help = "Reconcile managed runtime resources with provisioning facts."

    def add_arguments(self, parser: object) -> None:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--adapter-code", default="")

    def handle(self, *args: object, **options: object) -> None:
        del args
        apply = bool(options["apply"])
        adapter_code = str(options.get("adapter_code") or "").strip()
        adapters = RuntimeAdapter.objects.order_by("code")
        if adapter_code:
            adapters = adapters.filter(code=adapter_code)
        adapter_rows = list(adapters)
        if adapter_code and not adapter_rows:
            raise CommandError(f"Runtime adapter not found: {adapter_code}")

        trace_id = secrets.token_hex(16)
        context = ActorContext("runtime-reconciler", "WORKER", trace_id)
        report: dict[str, Any] = {
            "apply": apply,
            "trace_id": trace_id,
            "adapters": [],
            "relinked": [],
            "orphaned": [],
            "unknown_resources": [],
            "ambiguous_resources": [],
            "reservations_released": [],
            "reservations_would_release": [],
            "errors": [],
        }
        released_reservations: set[str] = set()
        adapter_groups: dict[tuple[str, str], list[RuntimeAdapter]] = defaultdict(list)
        for adapter_row in adapter_rows:
            adapter_groups[(adapter_row.driver, adapter_row.config_ref)].append(adapter_row)

        for adapter_group in adapter_groups.values():
            adapter_row = adapter_group[0]
            try:
                adapter = runtime_for_driver(
                    adapter_row.driver,
                    config_ref=adapter_row.config_ref,
                )
                inventory = adapter.inventory()
            except Exception as exc:
                code = str(getattr(exc, "code", "RUNTIME_INVENTORY_FAILED"))
                report["errors"].append(
                    {
                        "adapter_codes": [row.code for row in adapter_group],
                        "driver": adapter_row.driver,
                        "config_ref": adapter_row.config_ref,
                        "code": code,
                        "action": "SKIPPED",
                    }
                )
                continue

            report["adapters"].append(
                {
                    "codes": [row.code for row in adapter_group],
                    "driver": adapter_row.driver,
                    "config_ref": adapter_row.config_ref,
                    "resource_count": len(inventory),
                }
            )
            instances = list(
                ProvisioningInstance.objects.select_related("task", "course")
                .filter(runtime_adapter_id__in=[row.pk for row in adapter_group])
            )
            self._reconcile_inventory(
                adapter=adapter,
                inventory=inventory,
                instances=instances,
                apply=apply,
                context=context,
                report=report,
            )
            matched_ids = {
                item["instance_id"]
                for item in report["relinked"] + report["orphaned"]
                if item.get("instance_id")
            }
            matched_ids.update(
                item["instance_id"]
                for item in report.get("matched", [])
                if item.get("instance_id")
            )
            for instance in instances:
                if instance.status in TERMINAL_INSTANCE_STATUSES:
                    self._release_reservation_if_terminal(
                        instance=instance,
                        apply=apply,
                        context=context,
                        report=report,
                        released_reservations=released_reservations,
                    )
                    continue
                if instance.public_id in matched_ids:
                    continue
                if not instance.external_id:
                    self._orphan_instance(
                        instance=instance,
                        apply=apply,
                        reason="RUNTIME_RESOURCE_MISSING",
                        report=report,
                    )
                    self._release_reservation_if_terminal(
                        instance=instance,
                        apply=apply,
                        context=context,
                        report=report,
                        released_reservations=released_reservations,
                    )
                    continue
                self._orphan_instance(
                    instance=instance,
                    apply=apply,
                    reason="RUNTIME_RESOURCE_NOT_FOUND",
                    report=report,
                )
                self._release_reservation_if_terminal(
                    instance=instance,
                    apply=apply,
                    context=context,
                    report=report,
                    released_reservations=released_reservations,
                )

        report["summary"] = {
            "relinked": len(report["relinked"]),
            "orphaned": len(report["orphaned"]),
            "unknown_resources": len(report["unknown_resources"]),
            "ambiguous_resources": len(report["ambiguous_resources"]),
            "reservations_released": len(report["reservations_released"]),
            "errors": len(report["errors"]),
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))

    def _reconcile_inventory(
        self,
        *,
        adapter: Any,
        inventory: Iterable[RuntimeInventoryItem],
        instances: list[ProvisioningInstance],
        apply: bool,
        context: ActorContext,
        report: dict[str, Any],
    ) -> None:
        by_external_id = {
            instance.external_id: instance
            for instance in instances
            if instance.external_id
        }
        by_instance_id = {instance.public_id: instance for instance in instances}
        by_task_id: dict[str, list[ProvisioningInstance]] = defaultdict(list)
        for instance in instances:
            by_task_id[instance.task.public_id].append(instance)
        matched: set[int] = set()

        for resource in inventory:
            metadata = dict(resource.metadata)
            instance = by_external_id.get(resource.external_id)
            match_kind = "external_id"
            if instance is None:
                instance_id = str(metadata.get("instance_id") or "")
                instance = by_instance_id.get(instance_id) if instance_id else None
                match_kind = "instance_id"
            if instance is None:
                task_id = str(metadata.get("task_id") or "")
                candidates = [
                    candidate
                    for candidate in by_task_id.get(task_id, [])
                    if id(candidate) not in matched
                ]
                if len(candidates) == 1:
                    instance = candidates[0]
                    match_kind = "task_id"
                elif len(candidates) > 1:
                    report["ambiguous_resources"].append(
                        {
                            "external_id": resource.external_id,
                            "task_id": task_id,
                            "candidate_instance_ids": [
                                candidate.public_id for candidate in candidates
                            ],
                        }
                    )
                    continue
            if instance is None:
                unknown = {
                    "external_id": resource.external_id,
                    "status": resource.status,
                    "metadata": metadata,
                }
                report["unknown_resources"].append(unknown)
                if apply:
                    try:
                        adapter.destroy(
                            resource.external_id,
                            f"reconcile:{context.trace_id}:{resource.external_id}",
                        )
                        unknown["action"] = "DESTROYED"
                    except Exception as exc:
                        unknown["action"] = "FAILED"
                        report["errors"].append(
                            {
                                "external_id": resource.external_id,
                                "code": str(
                                    getattr(exc, "code", "RUNTIME_DESTROY_FAILED")
                                ),
                            }
                        )
                else:
                    unknown["action"] = "WOULD_DESTROY"
                continue

            if id(instance) in matched:
                continue
            matched.add(id(instance))
            report.setdefault("matched", []).append(
                {
                    "instance_id": instance.public_id,
                    "external_id": resource.external_id,
                    "match": match_kind,
                }
            )
            if instance.external_id == resource.external_id:
                continue
            change = {
                "instance_id": instance.public_id,
                "old_external_id": instance.external_id,
                "external_id": resource.external_id,
                "match": match_kind,
            }
            report["relinked"].append(change)
            if apply:
                try:
                    compare_and_swap(
                        ProvisioningInstance,
                        pk=instance.pk,
                        expected_version=instance.row_version,
                        changes={"external_id": resource.external_id},
                    )
                    change["action"] = "RELINKED"
                except Exception as exc:
                    change["action"] = "FAILED"
                    report["errors"].append(
                        {
                            "instance_id": instance.public_id,
                            "code": str(getattr(exc, "code", "RUNTIME_RELINK_FAILED")),
                        }
                    )

    def _orphan_instance(
        self,
        *,
        instance: ProvisioningInstance,
        apply: bool,
        reason: str,
        report: dict[str, Any],
    ) -> None:
        if instance.status in TERMINAL_INSTANCE_STATUSES:
            return
        item = {
            "instance_id": instance.public_id,
            "external_id": instance.external_id,
            "previous_status": instance.status,
            "reason": reason,
        }
        report["orphaned"].append(item)
        if not apply:
            item["action"] = "WOULD_MARK_ORPHANED"
            instance.status = ProvisioningInstance.Status.ORPHANED
            return
        metadata = dict(instance.external_metadata or {})
        metadata["reconciliation"] = {"reason": reason}
        try:
            compare_and_swap(
                ProvisioningInstance,
                pk=instance.pk,
                expected_version=instance.row_version,
                changes={
                    "status": ProvisioningInstance.Status.ORPHANED,
                    "endpoint": "",
                    "external_metadata": metadata,
                },
            )
            item["action"] = "MARKED_ORPHANED"
            instance.status = ProvisioningInstance.Status.ORPHANED
        except Exception as exc:
            item["action"] = "FAILED"
            report["errors"].append(
                {
                    "instance_id": instance.public_id,
                    "code": str(getattr(exc, "code", "RUNTIME_ORPHAN_UPDATE_FAILED")),
                }
            )

    def _release_reservation_if_terminal(
        self,
        *,
        instance: ProvisioningInstance,
        apply: bool,
        context: ActorContext,
        report: dict[str, Any],
        released_reservations: set[str],
    ) -> None:
        if instance.status not in TERMINAL_INSTANCE_STATUSES:
            return
        job = (
            ProvisioningJob.objects.select_related("reservation")
            .filter(task=instance.task)
            .order_by("-attempt_no", "-created_at")
            .first()
        )
        reservation = job.reservation if job is not None else None
        if reservation is None:
            reservation = (
                QuotaReservation.objects.filter(
                    subject_type__in=("TASK", "EXPERIMENT_TASK"),
                    subject_ref=instance.task.public_id,
                    status=QuotaReservation.Status.ACTIVE,
                )
                .order_by("-created_at")
                .first()
            )
        if reservation is None or reservation.public_id in released_reservations:
            return
        released_reservations.add(reservation.public_id)
        if not apply:
            report["reservations_would_release"].append(
                {"instance_id": instance.public_id, "reservation_id": reservation.public_id}
            )
            return
        try:
            release_runtime_capacity(reservation_id=reservation.public_id)
            release_reservation(
                reservation_id=reservation.public_id,
                reason="runtime reconciliation terminal instance",
                context=context,
            )
            report["reservations_released"].append(
                {"instance_id": instance.public_id, "reservation_id": reservation.public_id}
            )
        except Exception as exc:
            report["errors"].append(
                {
                    "instance_id": instance.public_id,
                    "reservation_id": reservation.public_id,
                    "code": str(getattr(exc, "code", "QUOTA_RELEASE_FAILED")),
                }
            )
