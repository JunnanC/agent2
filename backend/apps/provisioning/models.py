from django.db import models

from apps.core.identifiers import new_ulid
from apps.core.models import VersionedModel
from apps.governance.models import QuotaReservation, RuntimeAdapter


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class RuntimeCapacityReservation(VersionedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RELEASED = "RELEASED"

    public_id = public_id_field()
    reservation = models.OneToOneField(
        QuotaReservation, on_delete=models.PROTECT, related_name="runtime_capacity_binding"
    )
    runtime_adapter = models.ForeignKey(
        RuntimeAdapter, on_delete=models.PROTECT, related_name="capacity_reservations"
    )
    cpu_millicores = models.PositiveBigIntegerField()
    memory_mb = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "provisioning_runtime_capacity_reservation"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cpu_millicores__gt=0) & models.Q(memory_mb__gt=0),
                name="prov_capacity_reservation_positive_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RELEASED")),
                name="prov_capacity_reservation_status_ck",
            ),
        ]
