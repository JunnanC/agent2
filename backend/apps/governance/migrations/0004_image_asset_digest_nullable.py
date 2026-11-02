from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("governance", "0003_resource_request_limits")]

    operations = [
        migrations.AlterField(
            model_name="imageasset",
            name="digest",
            field=models.CharField(
                blank=True,
                db_collation="ascii_bin",
                max_length=71,
                null=True,
                unique=True,
            ),
        ),
    ]
