from django.db import migrations, models

from apps.core.identifiers import new_ulid


def replace_uuid_public_ids(apps, schema_editor) -> None:
    tables = ("core_object_asset", "core_compensation_task")
    with schema_editor.connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SELECT id FROM {table}")  # noqa: S608 - fixed table names
            for (row_id,) in cursor.fetchall():
                cursor.execute(
                    f"UPDATE {table} SET public_id = %s WHERE id = %s",  # noqa: S608
                    [new_ulid(), row_id],
                )


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.RunPython(replace_uuid_public_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="objectasset",
            name="public_id",
            field=models.CharField(
                db_collation="ascii_bin",
                default=new_ulid,
                editable=False,
                max_length=26,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="compensationtask",
            name="public_id",
            field=models.CharField(
                db_collation="ascii_bin",
                default=new_ulid,
                editable=False,
                max_length=26,
                unique=True,
            ),
        ),
    ]
