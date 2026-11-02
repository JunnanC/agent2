from datetime import timedelta

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone

from apps.core.identifiers import new_ulid


def migration_current_term_default() -> int:
    from apps.courses.models import AcademicTerm

    return AcademicTerm.objects.only("pk").get(is_current=True).pk


def create_legacy_term(apps, schema_editor):
    AcademicTerm = apps.get_model("courses", "AcademicTerm")
    Course = apps.get_model("courses", "Course")
    now = timezone.now()
    legacy = AcademicTerm.objects.create(
        public_id=new_ulid(),
        code="LEGACY-CURRENT",
        name="Legacy Current Term",
        starts_at=now,
        ends_at=now + timedelta(days=365),
        status="CURRENT",
        is_current=True,
    )
    for course in Course.objects.all():
        start = course.teaching_start or (
            course.teaching_end - timedelta(days=365) if course.teaching_end else now
        )
        end = course.teaching_end or start + timedelta(days=365)
        is_current_window = (not course.teaching_start and not course.teaching_end) or (
            start <= now <= end
        )
        term = legacy
        if not is_current_window:
            code = f"LEGACY-{course.pk}"
            status = "UPCOMING" if start > now else "CLOSED" if end < now else "CURRENT"
            term, _ = AcademicTerm.objects.get_or_create(
                code=code,
                defaults={
                    "public_id": new_ulid(),
                    "name": code,
                    "starts_at": start,
                    "ends_at": end,
                    "status": status,
                    "is_current": False,
                },
            )
        Course.objects.filter(pk=course.pk).update(term_id=term.pk)


class Migration(migrations.Migration):
    dependencies = [("courses", "0004_enrollmentimportjob_source_csv")]

    operations = [
        migrations.CreateModel(
            name="AcademicTerm",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("row_version", models.PositiveBigIntegerField(default=1, editable=False)),
                (
                    "public_id",
                    models.CharField(
                        db_collation="ascii_bin",
                        default=new_ulid,
                        editable=False,
                        max_length=26,
                        unique=True,
                    ),
                ),
                ("code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("UPCOMING", "Upcoming"),
                            ("CURRENT", "Current"),
                            ("CLOSED", "Closed"),
                        ],
                        default="UPCOMING",
                        max_length=16,
                    ),
                ),
                ("is_current", models.BooleanField(default=False)),
            ],
            options={"db_table": "courses_academic_term"},
        ),
        migrations.AddField(
            model_name="course",
            name="term",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="courses",
                to="courses.academicterm",
            ),
        ),
        migrations.RunPython(create_legacy_term, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="course",
            name="term",
            field=models.ForeignKey(
                default=migration_current_term_default,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="courses",
                to="courses.academicterm",
            ),
        ),
        migrations.AddConstraint(
            model_name="academicterm",
            constraint=models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="courses_term_date_window_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="academicterm",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=("UPCOMING", "CURRENT", "CLOSED")),
                name="courses_term_status_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="academicterm",
            constraint=models.CheckConstraint(
                condition=models.Q(is_current=False) | models.Q(status="CURRENT"),
                name="courses_term_current_status_ck",
            ),
        ),
        migrations.AddConstraint(
            model_name="academicterm",
            constraint=models.UniqueConstraint(
                condition=models.Q(is_current=True),
                fields=("is_current",),
                name="courses_term_one_current_uniq",
            ),
        ),
    ]
