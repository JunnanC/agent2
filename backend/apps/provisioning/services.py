"""Transactional admission and release for short-lived assessment execution."""
from django.db import transaction
from django.utils import timezone

from apps.core.concurrency import compare_and_swap
from apps.governance.errors import QuotaExceeded
from apps.governance.models import QuotaReservation
from apps.governance.models import RuntimeAdapter as RuntimeAdapterConfig

from .errors import ProvisioningConfigurationError, ProvisioningStateConflict
from .models import RuntimeCapacityReservation


@transaction.atomic
def reserve_runtime_capacity(
    *,
    reservation_id: str | QuotaReservation,
    runtime_adapter_id: str,
    cpu_millicores: int,
    memory_mb: int,
) -> RuntimeCapacityReservation | None:
    """Atomically admit a quota reservation against adapter capacity."""
    if cpu_millicores <= 0 or memory_mb <= 0:
        raise ProvisioningConfigurationError(
            detail={"capacity": "cpu_and_memory_must_be_positive"}
        )
    reservation: QuotaReservation
    if isinstance(reservation_id, str):
        reservation = QuotaReservation.objects.select_for_update().get(public_id=reservation_id)
    else:
        reservation = QuotaReservation.objects.select_for_update().get(pk=reservation_id.pk)
    runtime = RuntimeAdapterConfig.objects.select_for_update().get(public_id=runtime_adapter_id)
    if reservation.status != QuotaReservation.Status.ACTIVE:
        raise ProvisioningStateConflict(detail={"reservation": reservation.status})
    existing = RuntimeCapacityReservation.objects.select_for_update().filter(
        reservation=reservation
    ).first()
    if existing is not None:
        if existing.status != RuntimeCapacityReservation.Status.ACTIVE:
            raise ProvisioningStateConflict(detail={"reservation": "capacity_already_released"})
        if (existing.cpu_millicores, existing.memory_mb) != (cpu_millicores, memory_mb):
            raise ProvisioningStateConflict(detail={"reservation": "capacity_binding_mismatch"})
        if existing.runtime_adapter_id != runtime.pk:
            raise ProvisioningStateConflict(detail={"reservation": "runtime_binding_mismatch"})
        return existing
    # Zero-valued capacity is the historical "not reported" marker.
    if (
        runtime.capacity_cpu_millicores
        and runtime.available_cpu_millicores < cpu_millicores
    ) or (
        runtime.capacity_memory_mb
        and runtime.available_memory_mb < memory_mb
    ):
        raise QuotaExceeded(
            detail={
                "dimension": "runtime_capacity",
                "available_cpu_millicores": runtime.available_cpu_millicores,
                "available_memory_mb": runtime.available_memory_mb,
                "requested_cpu_millicores": cpu_millicores,
                "requested_memory_mb": memory_mb,
            }
        )
    if runtime.capacity_cpu_millicores or runtime.capacity_memory_mb:
        changed = compare_and_swap(
            RuntimeAdapterConfig,
            pk=runtime.pk,
            expected_version=runtime.row_version,
            changes={
                "available_cpu_millicores": (
                    runtime.available_cpu_millicores - cpu_millicores
                    if runtime.capacity_cpu_millicores
                    else runtime.available_cpu_millicores
                ),
                "available_memory_mb": (
                    runtime.available_memory_mb - memory_mb
                    if runtime.capacity_memory_mb
                    else runtime.available_memory_mb
                ),
            },
        )
        del changed
    return RuntimeCapacityReservation.objects.create(
        reservation=reservation,
        runtime_adapter=runtime,
        cpu_millicores=cpu_millicores,
        memory_mb=memory_mb,
    )


@transaction.atomic
def release_runtime_capacity(
    *, reservation_id: str | QuotaReservation
) -> RuntimeCapacityReservation | None:
    """Release a runtime binding once; repeated calls are no-ops."""
    reservation: QuotaReservation
    if isinstance(reservation_id, str):
        reservation = QuotaReservation.objects.select_for_update().get(public_id=reservation_id)
    else:
        reservation = QuotaReservation.objects.select_for_update().get(pk=reservation_id.pk)
    binding = RuntimeCapacityReservation.objects.select_for_update().filter(
        reservation=reservation
    ).first()
    if binding is None or binding.status != RuntimeCapacityReservation.Status.ACTIVE:
        return binding
    runtime = RuntimeAdapterConfig.objects.select_for_update().get(pk=binding.runtime_adapter_id)
    changes: dict[str, int] = {}
    if runtime.capacity_cpu_millicores:
        changes["available_cpu_millicores"] = min(
            runtime.capacity_cpu_millicores,
            runtime.available_cpu_millicores + binding.cpu_millicores,
        )
    if runtime.capacity_memory_mb:
        changes["available_memory_mb"] = min(
            runtime.capacity_memory_mb,
            runtime.available_memory_mb + binding.memory_mb,
        )
    if changes:
        compare_and_swap(
            RuntimeAdapterConfig,
            pk=runtime.pk,
            expected_version=runtime.row_version,
            changes=changes,
        )
    return compare_and_swap(
        RuntimeCapacityReservation,
        pk=binding.pk,
        expected_version=binding.row_version,
        changes={
            "status": RuntimeCapacityReservation.Status.RELEASED,
            "released_at": timezone.now(),
        },
    )
