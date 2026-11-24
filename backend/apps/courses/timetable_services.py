import hashlib
import json
import re
import zipfile
from contextlib import closing
from io import BytesIO
from typing import Any

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, StateConflict

from .errors import ContentStateConflict
from .models import (
    AcademicTerm,
    AdministrativeClass,
    AdministrativeClassMembership,
    Course,
    CourseSchedule,
    StudentScheduleEntry,
    TimetableImportJob,
)
from .services import ActorContext, create_course, publish_course

TIMETABLE_FIELDS = {
    "course_code": "教务教学班编号",
    "course_title": "课程名称",
    "weekday": "星期",
    "start_period": "开始节次",
    "end_period": "结束节次",
    "week_start": "开始周",
    "week_end": "结束周",
    "classroom": "教室",
    "instructor_name": "教师",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_WORKBOOK_XML_BYTES = 50 * 1024 * 1024
MAX_TIMETABLE_ROWS = 5000
MAX_TIMETABLE_COLUMNS = 50


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _read_workbook(content: bytes, filename: str) -> tuple[list[str], list[dict[str, Any]]]:
    if not filename.casefold().endswith(".xlsx"):
        raise ContentStateConflict(detail={"file": "xlsx_extension_required"})
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ContentStateConflict(detail={"file": "empty_or_too_large"})
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_WORKBOOK_XML_BYTES:
                raise ContentStateConflict(detail={"file": "expanded_content_too_large"})
        with closing(load_workbook(BytesIO(content), read_only=True, data_only=True)) as workbook:
            sheet = workbook.active
            if (sheet.max_column or 0) > MAX_TIMETABLE_COLUMNS:
                raise ContentStateConflict(detail={"file": "too_many_columns"})
            iterator = sheet.iter_rows(values_only=True, max_row=MAX_TIMETABLE_ROWS + 2)
            header_row = next(iterator, None)
            if not header_row:
                raise ContentStateConflict(detail={"file": "header_row_required"})
            if len(header_row) > MAX_TIMETABLE_COLUMNS:
                raise ContentStateConflict(detail={"file": "too_many_columns"})
            headers = [_cell_text(value) for value in header_row]
            while headers and not headers[-1]:
                headers.pop()
            if (
                not headers
                or any(not value for value in headers)
                or len(set(headers)) != len(headers)
            ):
                raise ContentStateConflict(detail={"file": "headers_must_be_nonempty_and_unique"})
            rows: list[dict[str, Any]] = []
            for row_no, values in enumerate(iterator, start=2):
                if row_no > MAX_TIMETABLE_ROWS + 1:
                    raise ContentStateConflict(detail={"file": "too_many_rows"})
                if len(values) > MAX_TIMETABLE_COLUMNS:
                    raise ContentStateConflict(detail={"file": "too_many_columns"})
                cells = [_cell_text(value) for value in values[: len(headers)]]
                if any(cells):
                    rows.append({
                        "row_no": row_no,
                        "cells": dict(zip(headers, cells, strict=False)),
                    })
        if not rows:
            raise ContentStateConflict(detail={"file": "no_timetable_rows"})
        return headers, rows
    except ContentStateConflict:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ContentStateConflict(detail={"file": "invalid_xlsx"}) from exc


@transaction.atomic
def create_timetable_import_job(
    *, actor: User, kind: str, filename: str, content: bytes, term_id: str = ""
) -> TimetableImportJob:
    headers, rows = _read_workbook(content, filename)
    if term_id:
        try:
            term = AcademicTerm.objects.get(public_id=term_id)
        except AcademicTerm.DoesNotExist as exc:
            raise ResourceNotFound() from exc
    else:
        try:
            term = AcademicTerm.objects.get(is_current=True)
        except AcademicTerm.DoesNotExist as exc:
            raise StateConflict(detail={"academic_term": "current_term_required"}) from exc
    if kind not in TimetableImportJob.Kind.values:
        raise ValueError("invalid timetable import kind")
    return TimetableImportJob.objects.create(
        owner=actor,
        kind=kind,
        term=term,
        filename=filename[:255],
        headers=headers,
        source_rows=rows,
    )


def _integer(value: str, *, part: str = "first") -> int:
    text = value.strip()
    match = re.search(r"(\d+)\s*[-–—~～至]\s*(\d+)", text)
    if match:
        return int(match.group(1 if part == "first" else 2))
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    raise ValueError("integer_required")


def _weekday(value: str) -> int:
    text = value.strip().casefold()
    day_names = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "日": 7,
        "天": 7,
        "mon": 1,
        "tue": 2,
        "wed": 3,
        "thu": 4,
        "fri": 5,
        "sat": 6,
        "sun": 7,
    }
    match = re.fullmatch(r"(?:星期|礼拜|周)?\s*([一二三四五六日天1-7])", text)
    if not match:
        for prefix, number in day_names.items():
            if len(prefix) == 3 and text.startswith(prefix):
                return number
        raise ValueError("weekday_required")
    day = match.group(1)
    weekday_number = int(day) if day.isdigit() else day_names.get(day)
    if weekday_number is None:
        raise ValueError("weekday_required")
    return weekday_number


def _mapped_schedule(row: dict[str, Any], mapping: dict[str, str], kind: str) -> dict[str, Any]:
    cells = row["cells"]
    raw = {field: str(cells.get(header, "")) for field, header in mapping.items()}
    title = raw.get("course_title", "").strip()
    code = raw.get("course_code", "").strip().upper()
    if not title:
        raise ValueError("course_title_required")
    if kind == TimetableImportJob.Kind.TEACHER and not code:
        raise ValueError("course_code_required")
    try:
        weekday = _weekday(raw.get("weekday", ""))
        start_period = _integer(raw.get("start_period", ""))
        end_period = _integer(raw.get("end_period", ""), part="second")
        week_start = _integer(raw["week_start"]) if raw.get("week_start") else 0
        week_end = _integer(raw["week_end"], part="second") if raw.get("week_end") else 0
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not 1 <= start_period <= end_period <= 32767 or not (
        week_start == week_end == 0 or 1 <= week_start <= week_end <= 32767
    ):
        raise ValueError("invalid_period_or_week_range")
    if len(code) > 64:
        raise ValueError("course_code_too_long")
    week_text = raw.get("week_start", "") + raw.get("week_end", "")
    if "单" in week_text and "双" in week_text:
        raise ValueError("conflicting_week_parity")
    week_parity = "ODD" if "单" in week_text else "EVEN" if "双" in week_text else "ALL"
    if week_parity != "ALL" and not any(
        week % 2 == (week_parity == "ODD")
        for week in range(week_start, min(week_end, week_start + 1) + 1)
    ):
        raise ValueError("week_parity_outside_range")
    return {
        "row_no": row["row_no"],
        "course_code": code,
        "course_title": title[:160],
        "weekday": weekday,
        "start_period": start_period,
        "end_period": end_period,
        "week_start": week_start,
        "week_end": week_end,
        "week_parity": week_parity,
        "classroom": raw.get("classroom", "")[:128],
        "instructor_name": raw.get("instructor_name", "")[:128],
    }


def _validate_rows(
    job: TimetableImportJob, mapping: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    required = {"course_title", "weekday", "start_period", "end_period"}
    if job.kind == TimetableImportJob.Kind.TEACHER:
        required.add("course_code")
    if not required.issubset(mapping):
        raise ContentStateConflict(detail={"mapping": {"required": sorted(required)}})
    if set(mapping) - set(TIMETABLE_FIELDS) or any(
        value not in job.headers for value in mapping.values()
    ):
        raise ContentStateConflict(detail={"mapping": "unknown_field_or_header"})
    normalized: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    titles: dict[str, str] = {}
    slots: set[tuple[Any, ...]] = set()
    course_codes: set[str] = set()
    for row in job.source_rows:
        try:
            item = _mapped_schedule(row, mapping, job.kind)
            key = (
                item["course_code"] or item["course_title"],
                item["weekday"],
                item["start_period"],
                item["end_period"],
                item["week_start"],
                item["week_end"],
                item["week_parity"],
            )
            if item["course_code"]:
                course_codes.add(item["course_code"])
                prior_title = titles.setdefault(item["course_code"], item["course_title"])
                if prior_title != item["course_title"]:
                    raise ValueError("course_title_conflicts_for_code")
            if key in slots:
                raise ValueError("duplicate_schedule_row")
            slots.add(key)
            normalized.append(item)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"row_no": row["row_no"], "code": str(exc) or "invalid_row"})
    if job.kind == TimetableImportJob.Kind.TEACHER and course_codes:
        existing = Course.objects.filter(
            owner_id=job.owner_id, term_id=job.term_id, timetable_code__in=course_codes
        )
        existing_by_code = {item.timetable_code: item for item in existing}
        for item in normalized:
            course = existing_by_code.get(item["course_code"])
            if course and course.title != item["course_title"]:
                errors.append({"row_no": item["row_no"], "code": "course_code_conflict"})
    return normalized, errors


@transaction.atomic
def update_timetable_import_mapping(
    *, job_id: str, actor: User, kind: str, mapping: dict[str, str]
) -> TimetableImportJob:
    try:
        job = TimetableImportJob.objects.select_for_update().get(
            public_id=job_id, owner=actor, kind=kind
        )
    except TimetableImportJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if job.status not in {
        TimetableImportJob.Status.MAPPING_REQUIRED,
        TimetableImportJob.Status.READY,
    }:
        raise ContentStateConflict(detail={"status": job.status})
    _, errors = _validate_rows(job, mapping)
    return compare_and_swap(
        TimetableImportJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={
            "mapping": mapping,
            "row_errors": errors,
            "summary": {
                "total": len(job.source_rows),
                "valid": len(job.source_rows) - len(errors),
                "errors": len(errors),
            },
            "status": TimetableImportJob.Status.READY,
        },
    )  # type: ignore[return-value]


def timetable_import_data(job: TimetableImportJob) -> dict[str, Any]:
    return {
        "public_id": job.public_id,
        "kind": job.kind,
        "status": job.status,
        "filename": job.filename,
        "term_id": job.term.public_id,
        "headers": job.headers,
        "fields": [{"key": key, "label": label} for key, label in TIMETABLE_FIELDS.items()],
        "mapping": job.mapping,
        "summary": job.summary,
        "row_errors": job.row_errors,
        "row_version": job.row_version,
    }


def _schedule_digest(item: dict[str, Any]) -> str:
    value = {
        key: item[key]
        for key in (
            "course_code",
            "course_title",
            "weekday",
            "start_period",
            "end_period",
            "week_start",
            "week_end",
            "classroom",
            "instructor_name",
        )
    }
    digest_input = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(digest_input).hexdigest()


@transaction.atomic
def execute_timetable_import(
    *, job_id: str, actor: User, kind: str, context: ActorContext
) -> TimetableImportJob:
    try:
        job = (
            TimetableImportJob.objects.select_for_update()
            .select_related("term")
            .get(public_id=job_id, owner=actor, kind=kind)
        )
    except TimetableImportJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if job.status == TimetableImportJob.Status.COMPLETED:
        return job
    if job.status != TimetableImportJob.Status.RUNNING:
        raise ContentStateConflict(detail={"status": job.status})
    if kind == TimetableImportJob.Kind.TEACHER:
        User.objects.select_for_update().get(pk=actor.pk)
    normalized, errors = _validate_rows(job, job.mapping)
    if errors:
        raise ContentStateConflict(detail={"row_errors": errors})
    courses: dict[str, Course] = {}
    schedule_count = 0
    for item in normalized:
        if kind == TimetableImportJob.Kind.STUDENT:
            course = None
            if item["course_code"]:
                course = Course.objects.filter(code=item["course_code"], term=job.term).first()
            _, created = StudentScheduleEntry.objects.get_or_create(
                student=actor,
                term=job.term,
                schedule_digest=_schedule_digest(item),
                defaults={
                    "course": course,
                    "course_code": item["course_code"],
                    "course_title": item["course_title"],
                    "instructor_name": item["instructor_name"],
                    "classroom": item["classroom"],
                    "weekday": item["weekday"],
                    "start_period": item["start_period"],
                    "end_period": item["end_period"],
                    "week_start": item["week_start"],
                    "week_end": item["week_end"],
                },
            )
            schedule_count += int(created)
            continue
        code = item["course_code"]
        course = courses.get(code)
        if course is None:
            course = Course.objects.filter(timetable_code=code, owner=actor, term=job.term).first()
            if course is None:
                # Old imports used the external number as Course.code. Only adopt an exact
                # owner/term/title match with an existing matching slot.
                course = Course.objects.filter(
                    timetable_code__isnull=True,
                    code=code,
                    owner=actor,
                    term=job.term,
                    title=item["course_title"],
                    weekly_schedules__weekday=item["weekday"],
                    weekly_schedules__start_period=item["start_period"],
                    weekly_schedules__end_period=item["end_period"],
                    weekly_schedules__week_start=item["week_start"],
                    weekly_schedules__week_end=item["week_end"],
                ).first()
                if course:
                    course = compare_and_swap(
                        Course,
                        pk=course.pk,
                        expected_version=course.row_version,
                        changes={"timetable_code": code},
                    )
                    assert isinstance(course, Course)
            if course is None:
                course = create_course(
                    actor=actor,
                    code="",
                    timetable_code=code,
                    title=item["course_title"],
                    summary="",
                    description="",
                    visibility=Course.Visibility.UNLISTED,
                    enrollment_mode=Course.EnrollmentMode.APPROVAL,
                    capacity=None,
                    enrollment_start=None,
                    enrollment_end=None,
                    teaching_start=None,
                    teaching_end=None,
                    context=context,
                    term=job.term,
                )
            if course.status == Course.Status.DRAFT:
                course = publish_course(
                    course_id=course.public_id,
                    actor=actor,
                    expected_version=course.row_version,
                    context=context,
                )
            courses[code] = course
        _, created = CourseSchedule.objects.get_or_create(
            course=course,
            weekday=item["weekday"],
            start_period=item["start_period"],
            end_period=item["end_period"],
            week_start=item["week_start"],
            week_end=item["week_end"],
            week_parity=item["week_parity"],
            defaults={"classroom": item["classroom"], "instructor_name": item["instructor_name"]},
        )
        schedule_count += int(created)
    return compare_and_swap(
        TimetableImportJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={
            "status": TimetableImportJob.Status.COMPLETED,
            "summary": {
                "total": len(normalized),
                "courses": len(courses),
                "schedules": schedule_count,
                "errors": 0,
            },
            "source_rows": [],
        },
    )  # type: ignore[return-value]


@transaction.atomic
def start_timetable_import(*, job_id: str, actor: User, kind: str) -> TimetableImportJob:
    try:
        job = TimetableImportJob.objects.select_for_update().get(
            public_id=job_id, owner=actor, kind=kind
        )
    except TimetableImportJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if job.status != TimetableImportJob.Status.READY or job.row_errors:
        raise ContentStateConflict(detail={"status": job.status, "row_errors": job.row_errors})
    return compare_and_swap(
        TimetableImportJob,
        pk=job.pk,
        expected_version=job.row_version,
        changes={"status": TimetableImportJob.Status.RUNNING},
    )  # type: ignore[return-value]


@transaction.atomic
def create_administrative_class(
    *,
    actor: User,
    code: str,
    name: str,
    department: str,
    year_of_entry: int | None,
) -> AdministrativeClass:
    return AdministrativeClass.objects.create(
        code=code.strip().upper(),
        name=name.strip(),
        department=department.strip(),
        year_of_entry=year_of_entry,
        created_by=actor,
    )


@transaction.atomic
def assign_administrative_class_member(
    *, actor: User, class_id: str, student_id: str
) -> AdministrativeClassMembership:
    try:
        administrative_class = AdministrativeClass.objects.select_for_update().get(
            public_id=class_id, status=AdministrativeClass.Status.ACTIVE
        )
        student = User.objects.get(public_id=student_id, account_status=User.AccountStatus.ACTIVE)
    except (AdministrativeClass.DoesNotExist, User.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    current = (
        AdministrativeClassMembership.objects.select_for_update()
        .filter(student=student, administrative_class=administrative_class, ends_on__isnull=True)
        .first()
    )
    today = timezone.localdate()
    if current:
        return current
    return AdministrativeClassMembership.objects.create(
        administrative_class=administrative_class,
        student=student,
        starts_on=today,
        assigned_by=actor,
    )


@transaction.atomic
def end_administrative_class_membership(
    *, class_id: str, student_id: str
) -> AdministrativeClassMembership:
    try:
        membership = AdministrativeClassMembership.objects.select_for_update().get(
            administrative_class__public_id=class_id,
            student__public_id=student_id,
            ends_on__isnull=True,
        )
    except AdministrativeClassMembership.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    return compare_and_swap(
        AdministrativeClassMembership,
        pk=membership.pk,
        expected_version=membership.row_version,
        changes={"ends_on": timezone.localdate()},
    )  # type: ignore[return-value]
