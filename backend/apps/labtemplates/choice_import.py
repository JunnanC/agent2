"""Fixed XLSX choice-question import: preview, signed confirmation, atomic append."""

import hashlib
import io
import zipfile
from decimal import Decimal
from typing import Any

from django.core import signing
from django.db import transaction
from openpyxl import Workbook, load_workbook

from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import request_digest

from .errors import TemplateValidationError
from .models import TemplateChapter, TemplateTask, TemplateVersion
from .questions import invalid, normalize_question
from .services import _content_guard, _course

HEADERS = ["题型", "题干", *[f"选项{letter}" for letter in "ABCDEF"], "正确答案", "分值", "解析"]
SALT = "assessment-choice-import-v1"


def download_template() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "选择题"
    sheet.append(HEADERS)
    sheet.append([
        "单选",
        "下列哪个是栈的特征？",
        "先进先出",
        "后进先出",
        "随机访问",
        "按值排序",
        "",
        "",
        "B",
        5,
        "栈遵循后进先出",
    ])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def parse_choices(content: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not content or len(content) > 10 * 1024 * 1024:
        invalid("file", "xlsx_size_limit")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if "word/document.xml" in names:
                from .word_choices import parse_word_choices

                return parse_word_choices(content)
            if (
                len(names) > 1000
                or sum(info.file_size for info in archive.infolist()) > 50 * 1024 * 1024
                or any(
                    "vbaproject" in name.lower() or "externallinks/" in name.lower()
                    for name in names
                )
            ):
                invalid("file", "unsafe_workbook")
        workbook = load_workbook(
            io.BytesIO(content),
            read_only=True,
            data_only=False,
            keep_links=False,
        )
    except ValueError, OSError, zipfile.BadZipFile, KeyError:
        invalid("file", "invalid_xlsx")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        if len(workbook.worksheets) != 1:
            invalid("file", "single_sheet_required")
        sheet = workbook.worksheets[0]
        if sheet.max_row > 5001 or sheet.max_column != len(HEADERS):
            invalid("file", "invalid_rows_or_columns")
        iterator = sheet.iter_rows()
        header = next(iterator)
        if [cell.value for cell in header] != HEADERS:
            invalid("file", "template_headers_required")
        for index, cells in enumerate(iterator, 2):
            values = [cell.value for cell in cells]
            if all(value is None for value in values):
                continue
            if any(cell.data_type == "f" for cell in cells):
                errors.append({"row": index, "error": "formula_not_allowed"})
                continue
            try:
                kind = {"单选": "SINGLE_CHOICE", "多选": "MULTIPLE_CHOICE"}.get(values[0])
                if not kind or not isinstance(values[1], str) or not values[1].strip():
                    invalid("question", "type_and_stem_required")
                options = [
                    {"id": letter, "text": str(value)}
                    for letter, value in zip("ABCDEF", values[2:8], strict=True)
                    if value is not None and str(value).strip()
                ]
                answers = str(values[8] or "").replace("，", ",").upper().split(",")
                public, private, score = normalize_question(
                    task_type=kind,
                    public={"options": options},
                    max_score=values[9],
                    marking={
                        "correct_option_ids": [answer.strip() for answer in answers],
                        "explanation": str(values[10] or ""),
                    },
                )
                rows.append({
                    "title": values[1][:160],
                    "description": values[1],
                    "task_type": kind,
                    "question_spec": public,
                    "marking_spec": private,
                    "max_score": str(score),
                })
            except (ValueError, TypeError, ArithmeticError) as exc:
                errors.append({"row": index, "error": type(exc).__name__})
            except TemplateValidationError as exc:
                errors.append({"row": index, "error": exc.detail})
    finally:
        workbook.close()
    if not rows and not errors:
        invalid("file", "questions_required")
    return rows, errors


def preview_choices(
    *,
    actor: Any,
    course_id: str,
    chapter_id: str,
    content: bytes,
) -> dict[str, Any]:
    from apps.courses.models import CourseStaffGrant

    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        chapter = TemplateChapter.objects.select_related("template_version").get(
            public_id=chapter_id,
            template_version__template__course=course,
        )
    except TemplateChapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    rows, errors = parse_choices(content)
    digest = hashlib.sha256(content).hexdigest()
    token = signing.dumps(
        {
            "actor": actor.public_id,
            "chapter": chapter.public_id,
            "version": chapter.template_version.row_version,
            "digest": digest,
        },
        salt=SALT,
    )
    return {
        "rows": rows,
        "errors": errors,
        "token": token if not errors else None,
        "count": len(rows),
        "total_score": str(sum((Decimal(row["max_score"]) for row in rows), Decimal(0))),
    }


@transaction.atomic
def confirm_choices(
    *,
    actor: Any,
    course_id: str,
    chapter_id: str,
    content: bytes,
    token: str,
    context: Any,
) -> dict[str, Any]:
    from apps.courses.models import CourseStaffGrant

    try:
        preview = signing.loads(token, salt=SALT, max_age=1800)
    except signing.BadSignature as exc:
        raise TemplateValidationError(detail={"token": "expired_or_invalid"}) from exc
    if preview.get("actor") != actor.public_id or preview.get("chapter") != chapter_id:
        invalid("token", "scope_mismatch")
    if preview.get("digest") != hashlib.sha256(content).hexdigest():
        invalid("file", "preview_content_changed")
    course = _course(course_id, actor, CourseStaffGrant.Capability.MANAGE_TEMPLATE)
    try:
        chapter = TemplateChapter.objects.select_related("template_version").get(
            public_id=chapter_id,
            template_version__template__course=course,
        )
    except TemplateChapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    version = TemplateVersion.objects.select_for_update().get(pk=chapter.template_version_id)
    version = _content_guard(version, preview["version"], context)
    rows, errors = parse_choices(content)
    if errors:
        invalid("file", "invalid_rows")
    start = chapter.tasks.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
    TemplateTask.objects.bulk_create([
        TemplateTask(chapter=chapter, sort_order=start + index, **row)
        for index, row in enumerate(rows, 1)
    ])
    changed = compare_and_swap(
        TemplateVersion,
        pk=version.pk,
        expected_version=version.row_version,
        changes={},
    )
    return {"count": len(rows), "row_version": changed.row_version, "digest": request_digest(rows)}
