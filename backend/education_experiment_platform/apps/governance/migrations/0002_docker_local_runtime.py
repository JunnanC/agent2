# Generated manually for the local Docker runtime governance extension.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("governance", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="runtimeadapter",
            name="driver",
            field=models.CharField(
                choices=[
                    ("DOCKER_SWARM", "Docker Swarm"),
                    ("DOCKER_LOCAL", "Docker Local"),
                    ("LIBVIRT", "Libvirt"),
                    ("FAKE", "Fake"),
                ],
                max_length=32,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="runtimeadapter",
            name="gov_runtime_driver_ck",
        ),
        migrations.AddConstraint(
            model_name="runtimeadapter",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    driver__in=("DOCKER_SWARM", "DOCKER_LOCAL", "LIBVIRT", "FAKE")
                ),
                name="gov_runtime_driver_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeadapter",
            constraint=models.CheckConstraint(
                condition=models.Q(driver="DOCKER_LOCAL", runtime_type="CONTAINER")
                | ~models.Q(driver="DOCKER_LOCAL"),
                name="gov_runtime_local_container_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeadapter",
            constraint=models.CheckConstraint(
                condition=models.Q(driver="DOCKER_LOCAL", config_ref__gt="")
                | ~models.Q(driver="DOCKER_LOCAL"),
                name="gov_runtime_local_config_ck",
            ),
        ),
    ]
