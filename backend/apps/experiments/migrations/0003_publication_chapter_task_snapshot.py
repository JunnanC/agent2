import django.db.models.deletion
from django.db import migrations, models

import apps.core.identifiers


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0002_task_runtime_snapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskpublication",
            name="template_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", max_length=64, null=True
            ),
        ),
        migrations.AddField(
            model_name="taskpublication",
            name="publication_digest",
            field=models.CharField(
                blank=True, db_collation="ascii_bin", max_length=64, null=True
            ),
        ),
        migrations.CreateModel(
            name="PublicationChapter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "public_id",
                    models.CharField(
                        db_collation="ascii_bin",
                        default=apps.core.identifiers.new_ulid,
                        editable=False,
                        max_length=26,
                        unique=True,
                    ),
                ),
                ("source_chapter_id", models.CharField(db_collation="ascii_bin", max_length=26)),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("learning_objectives", models.JSONField(blank=True, default=list)),
                ("sort_order", models.PositiveIntegerField()),
                ("snapshot", models.JSONField(blank=True, default=dict)),
                (
                    "publication",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="chapter_snapshots",
                        to="experiments.taskpublication",
                    ),
                ),
            ],
            options={
                "db_table": "experiments_publication_chapter",
                "indexes": [
                    models.Index(
                        fields=["publication", "sort_order"],
                        name="exp_pub_chapter_order_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PublicationTask",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "public_id",
                    models.CharField(
                        db_collation="ascii_bin",
                        default=apps.core.identifiers.new_ulid,
                        editable=False,
                        max_length=26,
                        unique=True,
                    ),
                ),
                ("source_task_id", models.CharField(db_collation="ascii_bin", max_length=26)),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("instructions", models.TextField(blank=True, default="")),
                ("task_type", models.CharField(max_length=64)),
                ("sort_order", models.PositiveIntegerField()),
                ("image_digest", models.CharField(db_collation="ascii_bin", max_length=71)),
                ("resource_profile_snapshot", models.JSONField(blank=True, default=dict)),
                ("execution_snapshot", models.JSONField(blank=True, default=dict)),
                ("submission_policy", models.JSONField(blank=True, default=dict)),
                ("grading_policy", models.JSONField(blank=True, default=dict)),
                (
                    "publication_chapter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="task_snapshots",
                        to="experiments.publicationchapter",
                    ),
                ),
            ],
            options={
                "db_table": "experiments_publication_task",
                "indexes": [
                    models.Index(
                        fields=["publication_chapter", "sort_order"],
                        name="experiments_pub_task_order_idx",
                    )
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="publicationchapter",
            constraint=models.UniqueConstraint(
                fields=("publication", "source_chapter_id"),
                name="experiments_pub_chapter_source_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="publicationchapter",
            constraint=models.UniqueConstraint(
                fields=("publication", "sort_order"),
                name="experiments_pub_chapter_order_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="publicationchapter",
            constraint=models.CheckConstraint(
                condition=models.Q(sort_order__gte=1),
                name="experiments_pub_chapter_order_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="publicationtask",
            constraint=models.UniqueConstraint(
                fields=("publication_chapter", "source_task_id"),
                name="experiments_pub_task_source_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="publicationtask",
            constraint=models.UniqueConstraint(
                fields=("publication_chapter", "sort_order"),
                name="experiments_pub_task_order_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="publicationtask",
            constraint=models.CheckConstraint(
                condition=models.Q(sort_order__gte=1),
                name="experiments_pub_task_order_ck",
            ),
        ),
    ]
