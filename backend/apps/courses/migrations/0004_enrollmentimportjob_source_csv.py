from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("courses", "0003_enrollmentimportitem_row_version_and_more")]

    operations = [
        migrations.AddField(
            model_name="enrollmentimportjob",
            name="source_csv",
            field=models.TextField(blank=True, default=""),
        ),
    ]
