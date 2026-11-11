from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0008_administrativeclass_administrativeclassmembership_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="administrativeclassmembership",
            name="courses_admin_member_active_uniq",
        ),
        migrations.AddConstraint(
            model_name="administrativeclassmembership",
            constraint=models.UniqueConstraint(
                fields=("student", "administrative_class", "active_slot"),
                name="courses_admin_member_active_uniq",
            ),
        ),
    ]
