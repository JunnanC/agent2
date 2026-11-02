from django.db import migrations, models
from django.db.models import F


def copy_legacy_values(apps, schema_editor):
    ResourceProfile = apps.get_model("governance", "ResourceProfile")
    ResourceProfile.objects.filter(cpu_request_millicores__isnull=True).update(
        cpu_request_millicores=F("cpu_millicores"),
        cpu_limit_millicores=F("cpu_millicores"),
        memory_request_mb=F("memory_mb"),
        memory_limit_mb=F("memory_mb"),
    )


class Migration(migrations.Migration):
    dependencies = [("governance", "0002_docker_local_runtime")]

    operations = [
        migrations.AddField(
            model_name="resourceprofile",
            name="cpu_request_millicores",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="resourceprofile",
            name="cpu_limit_millicores",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="resourceprofile",
            name="memory_request_mb",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="resourceprofile",
            name="memory_limit_mb",
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.RunPython(copy_legacy_values, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="resourceprofile",
            name="cpu_request_millicores",
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name="resourceprofile",
            name="cpu_limit_millicores",
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name="resourceprofile",
            name="memory_request_mb",
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name="resourceprofile",
            name="memory_limit_mb",
            field=models.PositiveIntegerField(),
        ),
        migrations.AddConstraint(
            model_name="resourceprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(cpu_request_millicores__gt=0)
                & models.Q(cpu_limit_millicores__gte=F("cpu_request_millicores")),
                name="gov_profile_cpu_request_limit_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="resourceprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(memory_request_mb__gt=0)
                & models.Q(memory_limit_mb__gte=F("memory_request_mb")),
                name="gov_profile_memory_request_limit_ck",
            ),
        ),
    ]
