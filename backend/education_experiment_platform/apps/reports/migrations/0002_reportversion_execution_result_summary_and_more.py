import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_filedownloadgrant"),
        ("reports", "0001_initial"),
        ("workspaces", "0003_alter_workspaceexecutionrun_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportversion",
            name="execution_result_summary",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_rule_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", default="", max_length=64
            ),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_rule_summary",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="report_versions",
                to="workspaces.workspaceexecutionrun",
            ),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="execution_report_versions",
                to="workspaces.workspacesnapshot",
            ),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_snapshot_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", default="", max_length=64
            ),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_status",
            field=models.CharField(blank=True, default="", max_length=24),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_stderr_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="report_execution_stderr_versions",
                to="core.objectasset",
            ),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_stdout_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="report_execution_stdout_versions",
                to="core.objectasset",
            ),
        ),
        migrations.AddField(
            model_name="reportversion",
            name="execution_test_report_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="report_execution_test_report_versions",
                to="core.objectasset",
            ),
        ),
    ]
