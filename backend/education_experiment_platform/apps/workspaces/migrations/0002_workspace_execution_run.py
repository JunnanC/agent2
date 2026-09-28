import django.db.models.deletion
from django.db import migrations, models

import apps.core.identifiers


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_objectasset_failure_code_objectasset_original_name_and_more"),
        ("experiments", "0002_task_runtime_snapshot"),
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceExecutionRun",
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
                        default=apps.core.identifiers.new_ulid,
                        editable=False,
                        max_length=26,
                        unique=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("QUEUED", "Queued"),
                            ("RUNNING", "Running"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("TIMEOUT", "Timeout"),
                            ("RESOURCE_EXCEEDED", "Resource exceeded"),
                            ("REJECTED", "Rejected"),
                        ],
                        default="QUEUED",
                        max_length=24,
                    ),
                ),
                ("execution_rule_summary", models.JSONField(default=dict)),
                (
                    "execution_rule_digest",
                    models.CharField(db_collation="ascii_bin", max_length=64),
                ),
                (
                    "idempotency_key",
                    models.CharField(
                        db_collation="ascii_bin", max_length=128, unique=True
                    ),
                ),
                ("error_code", models.CharField(blank=True, default="", max_length=64)),
                (
                    "result_summary",
                    models.CharField(blank=True, default="", max_length=500),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("duration_ms", models.PositiveBigIntegerField(blank=True, null=True)),
                ("trace_id", models.CharField(max_length=32)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_runs",
                        to="workspaces.workspacesession",
                    ),
                ),
                (
                    "snapshot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_runs",
                        to="workspaces.workspacesnapshot",
                    ),
                ),
                (
                    "stdout_asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_stdout_runs",
                        to="core.objectasset",
                    ),
                ),
                (
                    "stderr_asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_stderr_runs",
                        to="core.objectasset",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workspace_execution_runs",
                        to="experiments.experimenttask",
                    ),
                ),
                (
                    "test_report_asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_test_report_runs",
                        to="core.objectasset",
                    ),
                ),
            ],
            options={"db_table": "workspaces_execution_run"},
        ),
        migrations.AddIndex(
            model_name="workspaceexecutionrun",
            index=models.Index(
                fields=["task", "created_at", "id"], name="workspace_exec_task_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="workspaceexecutionrun",
            index=models.Index(fields=["session", "created_at"], name="workspace_exec_session_idx"),
        ),
        migrations.AddIndex(
            model_name="workspaceexecutionrun",
            index=models.Index(fields=["status", "created_at"], name="workspace_exec_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="workspaceexecutionrun",
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
                name="workspace_execution_status_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="workspaceexecutionrun",
            constraint=models.CheckConstraint(
                condition=models.Q(duration_ms__isnull=True) | models.Q(duration_ms__gte=0),
                name="workspace_execution_duration_ck",
            ),
        ),
    ]
