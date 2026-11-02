from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0003_criterionscore_review_criterionscoreevent_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="autocheckrun",
            name="execution_rule_summary",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="autocheckrun",
            name="execution_rule_digest",
            field=models.CharField(
                blank=True,
                db_collation="ascii_bin",
                default="",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="autocheckrun",
            name="duration_ms",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="autocheckrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("QUEUED", "Queued"),
                    ("RUNNING", "Running"),
                    ("PASSED", "Passed"),
                    ("FAILED", "Failed"),
                    ("TIMEOUT", "Timeout"),
                    ("RESOURCE_EXCEEDED", "Resource Exceeded"),
                    ("REJECTED", "Rejected"),
                ],
                default="QUEUED",
                max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name="autocheckrun",
            constraint=models.CheckConstraint(
                condition=models.Q(duration_ms__isnull=True) | models.Q(duration_ms__gte=0),
                name="reviews_auto_run_duration_ck",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="autocheckrun",
            name="reviews_auto_run_status_ck",
        ),
        migrations.AddConstraint(
            model_name="autocheckrun",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "QUEUED",
                        "RUNNING",
                        "PASSED",
                        "FAILED",
                        "TIMEOUT",
                        "RESOURCE_EXCEEDED",
                        "REJECTED",
                    )
                ),
                name="reviews_auto_run_status_ck",
            ),
        ),
    ]
