from django.db import migrations, models
import django.db.models.deletion
from apps.core.identifiers import new_ulid


class Migration(migrations.Migration):
    dependencies = [("labtemplates", "0003_execution_spec")]

    operations = [
        migrations.CreateModel(
            name="TemplateChapter",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1, editable=False)),
                ("public_id", models.CharField(db_collation="ascii_bin", default=new_ulid, editable=False, max_length=26, unique=True)),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("learning_objectives", models.JSONField(default=list)),
                ("sort_order", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("PUBLISHED", "Published")], default="DRAFT", max_length=16)),
                ("resource_profile", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="template_chapters", to="governance.resourceprofile")),
                ("template_version", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="chapters", to="labtemplates.templateversion")),
            ],
            options={"db_table": "labtemplates_template_chapter"},
        ),
        migrations.CreateModel(
            name="TemplateTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1, editable=False)),
                ("public_id", models.CharField(db_collation="ascii_bin", default=new_ulid, editable=False, max_length=26, unique=True)),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("instructions", models.TextField(blank=True, default="")),
                ("task_type", models.CharField(max_length=64)),
                ("sort_order", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("PUBLISHED", "Published")], default="DRAFT", max_length=16)),
                ("execution_spec", models.JSONField(default=dict)),
                ("submission_policy", models.JSONField(default=dict)),
                ("grading_policy", models.JSONField(default=dict)),
                ("chapter", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tasks", to="labtemplates.templatechapter")),
                ("resource_profile", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="template_tasks", to="governance.resourceprofile")),
            ],
            options={"db_table": "labtemplates_template_task"},
        ),
        migrations.AddConstraint(model_name="templatechapter", constraint=models.UniqueConstraint(fields=("template_version", "sort_order"), name="lab_chapter_order_uniq")),
        migrations.AddConstraint(model_name="templatechapter", constraint=models.CheckConstraint(condition=models.Q(sort_order__gte=1), name="lab_chapter_order_ck")),
        migrations.AddConstraint(model_name="templatechapter", constraint=models.CheckConstraint(condition=models.Q(status__in=("DRAFT", "PUBLISHED")), name="lab_chapter_status_ck")),
        migrations.AddIndex(model_name="templatechapter", index=models.Index(fields=("template_version", "sort_order"), name="lab_chapter_order_idx")),
        migrations.AddConstraint(model_name="templatetask", constraint=models.UniqueConstraint(fields=("chapter", "sort_order"), name="lab_task_order_uniq")),
        migrations.AddConstraint(model_name="templatetask", constraint=models.CheckConstraint(condition=models.Q(sort_order__gte=1), name="lab_task_order_ck")),
        migrations.AddConstraint(model_name="templatetask", constraint=models.CheckConstraint(condition=models.Q(status__in=("DRAFT", "PUBLISHED")), name="lab_task_status_ck")),
        migrations.AddIndex(model_name="templatetask", index=models.Index(fields=("chapter", "sort_order"), name="lab_task_order_idx")),
    ]
