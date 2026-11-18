from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_pendingregistration_and_more")]
    operations = [
        migrations.AddField(
            model_name="user",
            name="student_number",
            field=models.CharField(max_length=32, unique=True, null=True, blank=True),
        )
    ]
