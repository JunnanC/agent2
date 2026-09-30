from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("core", "0004_filedownloadgrant"),
        ("experiments", "0002_task_runtime_snapshot"),
        ("reports", "0002_reportversion_execution_result_summary_and_more"),
        ("workspaces", "0003_alter_workspaceexecutionrun_status"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="reportversion",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("execution_run__isnull", True),
                    (
                        "execution_status__in",
                        (
                            "PASSED",
                            "FAILED",
                            "TIMEOUT",
                            "RESOURCE_EXCEEDED",
                            "REJECTED",
                        ),
                    ),
                    _connector="OR",
                ),
                name="reports_version_exec_status_ck",
            ),
        ),
    ]
