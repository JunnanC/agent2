"""Bounded platform-only batch provisioning; passwords never enter results or audit."""

import csv
import io
import re

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.core.errors import CoreError

from .models import User
from .serializers import UserCreateSerializer
from .services import ActorContext, create_user


def import_students(*, csv_payload: str, context: ActorContext) -> list[dict]:
    if len(csv_payload.encode("utf-8")) > 1024 * 1024:
        raise ValidationError({"csv": "最多 1 MiB"})
    reader = csv.DictReader(io.StringIO(csv_payload.lstrip("\ufeff")), strict=True)
    required = {"student_number", "email", "display_name", "password"}
    try:
        if (
            not reader.fieldnames
            or set(reader.fieldnames) != required
            or len(reader.fieldnames) != 4
        ):
            raise ValidationError({"csv": "表头必须为 student_number,email,display_name,password"})
        rows = list(reader)
    except csv.Error as exc:
        raise ValidationError({"csv": "CSV 格式无效"}) from exc
    if not rows or len(rows) > 500 or any(None in row or None in row.values() for row in rows):
        raise ValidationError({"csv": "需要 1–500 行且每行字段完整"})
    results = []
    for row_number, row in enumerate(rows, 2):
        number = row["student_number"].strip().casefold()
        result = {"row_number": row_number, "student_number": number, "status": "FAILED"}
        try:
            with transaction.atomic():
                if not re.fullmatch(r"[a-z0-9._-]{3,32}", number):
                    raise ValidationError("invalid_student_number")
                if User.objects.filter(Q(student_number=number) | Q(username=number)).exists():
                    result["error"] = "duplicate_identifier"
                else:
                    serializer = UserCreateSerializer(
                        data={
                            "username": number,
                            "email": row["email"],
                            "display_name": row["display_name"],
                            "password": row["password"],
                        }
                    )
                    serializer.is_valid(raise_exception=True)
                    user = create_user(context=context, **serializer.validated_data)
                    User.objects.filter(pk=user.pk).update(student_number=number)
                    result.update(status="CREATED", user_id=user.public_id)
        except (CoreError, ValidationError, IntegrityError) as exc:
            # Return codes only: validation details may contain supplied credentials.
            result["error"] = getattr(exc, "code", "invalid_row")
        results.append(result)
    return results
