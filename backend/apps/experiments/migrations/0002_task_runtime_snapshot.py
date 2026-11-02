import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0001_initial"),
        ("governance", "0002_docker_local_runtime"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskpublication",
            name="template_spec_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", max_length=64, null=True
            ),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="execution_spec",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="runtime_adapter_driver",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="runtime_adapter_config_ref",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="image_registry",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="image_repository",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="image_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", default="", max_length=71
            ),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="resource_profile_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="runtime_adapter",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="experiment_task_publication_snapshots",
                to="governance.runtimeadapter",
            ),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="image",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="experiment_task_publication_snapshots",
                to="governance.imageasset",
            ),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="resource_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="experiment_task_publication_snapshots",
                to="governance.resourceprofile",
            ),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="template_spec_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", max_length=64, null=True
            ),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="execution_spec",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="runtime_adapter_driver",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="runtime_adapter_config_ref",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="image_registry",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="image_repository",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="image_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", default="", max_length=71
            ),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="resource_profile_snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="runtime_adapter",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="experiment_task_runtime_snapshots",
                to="governance.runtimeadapter",
            ),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="image",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="experiment_task_runtime_snapshots",
                to="governance.imageasset",
            ),
        ),
        migrations.AddField(
            model_name="experimenttask",
            name="resource_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="experiment_task_runtime_snapshots",
                to="governance.resourceprofile",
            ),
        ),
    ]
