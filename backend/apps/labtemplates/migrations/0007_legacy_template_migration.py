import django.db.models.deletion
from django.db import migrations, models

from apps.core.identifiers import new_ulid


class Migration(migrations.Migration):
    dependencies = [
        ("labtemplates", "0006_experimentimage_build_args_sealed"),
    ]

    operations = [
        migrations.CreateModel(
            name="LegacyTemplateMigration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1, editable=False)),
                (
                    "public_id",
                    models.CharField(
                        db_collation="ascii_bin",
                        default=new_ulid,
                        editable=False,
                        max_length=26,
                        unique=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("MIGRATED", "Migrated"),
                            ("SKIPPED", "Skipped"),
                            ("MIGRATION_REQUIRED", "Migration Required"),
                            ("FAILED", "Failed"),
                        ],
                        max_length=24,
                    ),
                ),
                ("error_code", models.CharField(blank=True, default="", max_length=64)),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "chapter",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="legacy_migrations",
                        to="labtemplates.templatechapter",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="legacy_migrations",
                        to="labtemplates.templatetask",
                    ),
                ),
                (
                    "template_version",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="legacy_migration",
                        to="labtemplates.templateversion",
                    ),
                ),
            ],
            options={
                "db_table": "labtemplates_legacy_template_migration",
                "indexes": [
                    models.Index(
                        fields=["status", "processed_at"],
                        name="lab_legacy_mig_status_idx",
                    )
                ],
            },
        ),
    ]
