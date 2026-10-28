from django.db import migrations, models


def remove_legacy_current_constraint(apps, schema_editor):
    AcademicTerm = apps.get_model("courses", "AcademicTerm")
    constraint = models.UniqueConstraint(
        fields=("is_current",),
        condition=models.Q(is_current=True),
        name="courses_term_one_current_uniq",
    )
    table_name = AcademicTerm._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(cursor, table_name)
    if constraint.name in constraints:
        schema_editor.remove_constraint(AcademicTerm, constraint)


class Migration(migrations.Migration):
    dependencies = [("courses", "0005_academicterm_course_term")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(remove_legacy_current_constraint, migrations.RunPython.noop)
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="academicterm",
                    name="courses_term_one_current_uniq",
                )
            ],
        ),
        migrations.AddField(
            model_name="academicterm",
            name="current_slot",
            field=models.GeneratedField(
                db_persist=True,
                expression=models.Case(
                    models.When(is_current=True, then=models.Value(1)),
                    default=models.Value(None),
                ),
                output_field=models.PositiveSmallIntegerField(null=True),
            ),
        ),
        migrations.AddConstraint(
            model_name="academicterm",
            constraint=models.UniqueConstraint(
                fields=("current_slot",),
                name="courses_term_one_current_uniq",
            ),
        ),
    ]
