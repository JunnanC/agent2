"""Single current assessment attachment and publication-level report template."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from decimal import Decimal
from pathlib import PurePath
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.antivirus import ClamAVScanner
from apps.core.assets import register_asset, set_scan_result
from apps.core.compensation import create_compensation
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict, StateConflict
from apps.core.identifiers import new_ulid
from apps.core.models import ObjectAsset
from apps.core.object_storage import object_storage
from apps.core.tasks import run_compensations
from apps.courses.models import CourseStaffGrant
from apps.courses.selectors import require_course_capability
from apps.experiments.assessment import _task
from apps.experiments.assessment_parts import part_scores, session_for
from apps.experiments.models import ExperimentTask, TaskPublication

from .models import ReportSubmission
from .services import ALLOWED_FILES, _magic_matches, _safe_filename
from .word_review import asset_bytes, document_paragraphs, valid_docx

TEMPLATE_OWNER = "EXPERIMENT_REPORT_TEMPLATE"
REPORT_OWNER = "ASSESSMENT_REPORT"


@contextmanager
def _store(file: UploadedFile, *, owner: str, ref: str) -> Iterator[ObjectAsset]:
    name = _safe_filename(file.name or "")
    media_type = ALLOWED_FILES.get(PurePath(name).suffix.casefold())
    if not media_type or not 1 <= file.size <= settings.REPORT_ATTACHMENT_MAX_BYTES:
        raise StateConflict(detail={"file": "invalid_format_or_size"})
    if not _magic_matches(ObjectAsset(original_name=name), file):
        raise StateConflict(detail={"file": "invalid_format"})
    if not ClamAVScanner().scan(file.chunks()).clean:
        raise StateConflict(detail={"file": "scan_rejected"})
    digest = hashlib.sha256()
    for chunk in file.chunks():
        digest.update(chunk)
    file.seek(0)
    key = f"assessment-uploads/{owner}/{ref}/{new_ulid()}"
    storage = object_storage()
    bucket = settings.MINIO_BUCKET
    stored = storage.put_stream(bucket=bucket, object_key=key, stream=file, media_type=media_type)
    try:
        if not stored.version_id:
            raise StateConflict(detail={"file": "asset_version_not_pinned"})
        with transaction.atomic():
            asset = register_asset(
                bucket=bucket,
                object_key=key,
                object_version=stored.version_id,
                digest_sha256=digest.hexdigest(),
                size_bytes=file.size,
                media_type=media_type,
                owner_type=owner,
                owner_ref=ref,
                purpose=owner,
                original_name=name,
            )
            yield set_scan_result(
                asset_id=asset.pk,
                expected_version=asset.row_version,
                scan_status="CLEAN",
            )
    except Exception:
        with suppress(Exception):
            storage.delete_object(bucket=bucket, object_key=key, version_id=stored.version_id)
        raise


def _retire(asset: ObjectAsset) -> None:
    ObjectAsset.objects.filter(pk=asset.pk).update(status=ObjectAsset.Status.PURGE_PENDING)
    create_compensation(
        task_type="DELETE_REPORT_ASSET",
        subject_type="OBJECT_ASSET",
        subject_ref=asset.public_id,
        payload={"asset_id": asset.public_id},
        trace_id="assessment-report-replacement",
    )
    transaction.on_commit(
        lambda: run_compensations.delay(trace_id="assessment-report-replacement"),
        robust=True,
    )


def file_data(asset: ObjectAsset | None) -> dict[str, str] | None:
    return {"asset_id": asset.public_id, "file_name": asset.original_name} if asset else None


def report_data(task: ExperimentTask, *, teaching: bool = False) -> dict[str, Any]:
    part = next(
        (part for part in part_scores(task, student=not teaching) if part["kind"] == "REPORT"),
        None,
    )
    if part is None or not session_for(task):
        raise ResourceNotFound()
    publication = task.publication
    report = ReportSubmission.objects.select_related("asset").filter(task=task).first()
    visible = teaching or not publication.direct_assessment or bool(publication.grades_published_at)
    return {
        **part,
        "template": file_data(publication.assessment_report_template),
        "attachment": file_data(report.asset if report else None),
        "submitted_at": report.submitted_at if report else None,
        "row_version": report.row_version if report else None,
        "feedback": report.feedback if report and visible else "",
        "comments": report.comments if report and visible else [],
        "review_status": report.review_status if report and teaching else "",
        "ai_review": report.ai_review if report and teaching else {},
        "released_at": publication.grades_published_at,
        "signer": publication.grade_signer,
        "direct_assessment": publication.direct_assessment,
    }


@transaction.atomic
def submit_report(*, actor: User, task_id: str, file: UploadedFile) -> dict[str, Any]:
    task = _task(actor, task_id, write=True, part="REPORT")
    report_data(task)
    if task.publication.direct_assessment and (
        PurePath(file.name or "").suffix.casefold() != ".docx"
        or not 1 <= file.size <= settings.REPORT_ATTACHMENT_MAX_BYTES
        or not valid_docx(file)
    ):
        raise StateConflict(detail={"file": "valid_docx_required"})
    report = ReportSubmission.objects.filter(task=task).select_related("asset").first()
    with _store(file, owner=REPORT_OWNER, ref=task.public_id) as asset:
        from apps.experiments.assessment_parts import require_part_open

        require_part_open(task, "REPORT")
        fields = {
            "asset": asset,
            "submitted_at": timezone.now(),
            "status": "SUBMITTED",
            "score": None,
            "graded_by": None,
            "feedback": "",
            "review_status": "", "ai_review": {}, "comments": [],
        }
        if report is None:
            ReportSubmission.objects.create(task=task, **fields)
        else:
            compare_and_swap(
                ReportSubmission,
                pk=report.pk,
                expected_version=report.row_version,
                changes=fields,
            )
            _retire(report.asset)
    return report_data(task)


@transaction.atomic
def grade_report(
    *,
    task: ExperimentTask,
    actor: User,
    score: Decimal,
    feedback: str,
    expected_version: int,
    comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    publication = TaskPublication.objects.select_for_update().get(pk=task.publication_id)
    if publication.grades_published_at:
        raise StateConflict(detail={"publication": "grades_locked"})
    task = ExperimentTask.objects.select_for_update().get(pk=task.pk)
    task.publication = publication
    state = report_data(task, teaching=True)
    report = ReportSubmission.objects.select_related("asset").filter(task=task).first()
    if not report or report.status == "RETURNED" or task.publication.status == "WITHDRAWN":
        raise StateConflict(detail={"report": "submission_required"})
    if score > Decimal(state["max_score"]):
        raise StateConflict(detail={"score": "exceeds_report_maximum"})
    if comments is not None and publication.direct_assessment and comments:
        paragraphs = {row["paragraph"] for row in document_paragraphs(asset_bytes(report.asset))}
        if any(item["paragraph"] not in paragraphs for item in comments):
            raise StateConflict(detail={"comments": "invalid_paragraph"})
    compare_and_swap(
        ReportSubmission,
        pk=report.pk,
        expected_version=expected_version,
        changes={
            "status": "GRADED",
            "score": min(score, Decimal(str(state["score_cap"]))),
            "graded_by": actor,
            "feedback": feedback,
            **({"comments": comments} if comments is not None else {}),
        },
    )
    return report_data(task, teaching=True)


@transaction.atomic
def attach_template(
    *,
    publication: TaskPublication,
    file: UploadedFile,
    expected_version: int,
) -> TaskPublication:
    publication = TaskPublication.objects.select_for_update().get(pk=publication.pk)
    if publication.row_version != expected_version:
        raise RowVersionConflict()
    if publication.status not in {"DRAFT", "PUBLISH_FAILED"}:
        raise StateConflict(detail={"publication": "draft_required"})
    if publication.direct_assessment:
        if not publication.report_required:
            raise StateConflict(detail={"report": "not_required"})
        if (
            PurePath(file.name or "").suffix.casefold() != ".docx"
            or not 1 <= file.size <= settings.REPORT_ATTACHMENT_MAX_BYTES
            or not valid_docx(file)
        ):
            raise StateConflict(detail={"file": "valid_docx_required"})
    old = publication.report_template_asset
    with _store(file, owner=TEMPLATE_OWNER, ref=publication.public_id) as asset:
        publication = compare_and_swap(
            TaskPublication,
            pk=publication.pk,
            expected_version=expected_version,
            changes={"report_template_asset": asset, "report_required": True},
        )
        if old and not old.experiment_report_templates.exists():
            _retire(old)
    return publication


def authorize_assessment_download(asset: ObjectAsset, actor: User, portal: str) -> str:
    if asset.owner_type == TEMPLATE_OWNER:
        publications = TaskPublication.objects.filter(report_template_asset=asset)
        if portal == "USER":
            publications = publications.filter(
                status__in={"PUBLISHED", "CLOSED"},
                tasks__student=actor,
                tasks__enrollment__status="ACTIVE",
            )
        publication = publications.select_related("course").first()
        if publication is None:
            raise ResourceNotFound()
        course = publication.course
        if portal == "TEACHING":
            require_course_capability(
                course=course,
                actor=actor,
                capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT,
            )
        elif portal != "USER":
            raise ResourceNotFound()
    else:
        report = ReportSubmission.objects.filter(asset=asset).select_related("task__course").first()
        if report is None:
            raise ResourceNotFound()
        task = report.task
        course = task.course
        if portal == "USER":
            if task.student_id != actor.pk or task.enrollment.status != "ACTIVE":
                raise ResourceNotFound()
        elif portal == "TEACHING":
            require_course_capability(
                course=course,
                actor=actor,
                capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
            )
        else:
            raise ResourceNotFound()
    return course.public_id
