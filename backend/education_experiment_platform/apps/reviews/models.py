from django.db import models

from apps.accounts.models import User
from apps.core.identifiers import new_ulid
from apps.core.models import VersionedModel
from apps.courses.models import Course


def public_id_field() -> models.CharField:
    return models.CharField(
        max_length=26,
        default=new_ulid,
        unique=True,
        editable=False,
        db_collation="ascii_bin",
    )


class Rubric(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"

    public_id = public_id_field()
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="rubrics")
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="owned_rubrics")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    current_version = models.ForeignKey(
        "RubricVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="current_for_rubrics",
    )

    class Meta:
        db_table = "reviews_rubric"
        constraints = [
            models.UniqueConstraint(
                fields=("course", "name"), name="reviews_rubric_course_name_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "PUBLISHED")),
                name="reviews_rubric_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("course", "status"), name="reviews_rubric_course_idx")]


class RubricVersion(VersionedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        PUBLISHED = "PUBLISHED"

    public_id = public_id_field()
    rubric = models.ForeignKey(Rubric, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveIntegerField()
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    total_score = models.DecimalField(max_digits=9, decimal_places=2)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_rubric_versions"
    )
    published_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_rubric_versions",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reviews_rubric_version"
        constraints = [
            models.UniqueConstraint(
                fields=("rubric", "version_no"), name="reviews_rubric_ver_no_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(total_score__gt=0), name="reviews_rubric_total_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=("DRAFT", "PUBLISHED")),
                name="reviews_rubric_ver_status_ck",
            ),
        ]
        indexes = [models.Index(fields=("rubric", "status"), name="reviews_rubric_ver_idx")]


class RubricCriterion(VersionedModel):
    public_id = public_id_field()
    rubric_version = models.ForeignKey(
        RubricVersion, on_delete=models.PROTECT, related_name="criteria"
    )
    position = models.PositiveIntegerField()
    position_key = models.CharField(max_length=64, default="")
    is_active = models.BooleanField(default=True)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    guidance = models.TextField(blank=True, default="")
    max_score = models.DecimalField(max_digits=9, decimal_places=2)
    weight_basis_points = models.PositiveIntegerField()

    class Meta:
        db_table = "reviews_rubric_criterion"
        constraints = [
            models.UniqueConstraint(
                fields=("rubric_version", "position_key"),
                name="reviews_criterion_position_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1), name="reviews_criterion_position_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(max_score__gt=0), name="reviews_criterion_score_ck"
            ),
            models.CheckConstraint(
                condition=models.Q(weight_basis_points__gte=1)
                & models.Q(weight_basis_points__lte=10000),
                name="reviews_criterion_weight_ck",
            ),
        ]
        indexes = [
            models.Index(fields=("rubric_version", "position"), name="reviews_criterion_order_idx")
        ]
