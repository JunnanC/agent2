import django.db.models.deletion
from django.db import migrations, models

import apps.core.identifiers


class Migration(migrations.Migration):
    dependencies = [
        ("governance", "0003_resource_request_limits"),
        ("provisioning", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RuntimeCapacityReservation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1, editable=False)),
                (
                    "public_id",
                    models.CharField(
                        db_collation="ascii_bin",
                        default=apps.core.identifiers.new_ulid,
                        editable=False,
                        max_length=26,
                        unique=True,
                    ),
                ),
                ("cpu_millicores", models.PositiveBigIntegerField()),
                ("memory_mb", models.PositiveBigIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("ACTIVE", "Active"), ("RELEASED", "Released")],
                        default="ACTIVE",
                        max_length=16,
                    ),
                ),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                (
                    "reservation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="runtime_capacity_binding",
                        to="governance.quotareservation",
                    ),
                ),
                (
                    "runtime_adapter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="capacity_reservations",
                        to="governance.runtimeadapter",
                    ),
                ),
            ],
            options={"db_table": "provisioning_runtime_capacity_reservation"},
        ),
        migrations.AddConstraint(
            model_name="runtimecapacityreservation",
            constraint=models.CheckConstraint(
                condition=models.Q(cpu_millicores__gt=0) & models.Q(memory_mb__gt=0),
                name="prov_capacity_reservation_positive_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimecapacityreservation",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=("ACTIVE", "RELEASED")),
                name="prov_capacity_reservation_status_ck",
            ),
        ),
    ]
