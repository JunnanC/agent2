from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0004_workspace_storage_job"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspacestoragejob",
            name="last_dispatched_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="workspacestoragejob",
            index=models.Index(
                fields=["status", "last_dispatched_at"],
                name="workspace_storage_dispatch_idx",
            ),
        ),
    ]
