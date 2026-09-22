import csv
import hashlib
import hmac
import secrets
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.models import ObjectAsset

from . import events
from .errors import (
    ActiveEnrollmentRequired,
    ContentStateConflict,
    CrossCourseReference,
    InvitationInvalid,
    MaterialAssetNotClean,
    PrerequisiteCycle,
)
from .models import (
    Announcement,
    Answer,
    CalendarEvent,
    Chapter,
    ChapterPrerequisite,
    Course,
    CourseCopyItem,
    CourseCopyJob,
    CoursePrerequisite,
    Enrollment,
    EnrollmentImportItem,
    EnrollmentImportJob,
    Invitation,
    Material,
    MaterialVersion,
    ModerationEvent,
    Question,
)
from .selectors import active_enrollment, require_course_capability, require_owner
from .services import ActorContext, _audit, _event, apply_for_course


def _course(course_id: str) -> Course:
    try:
        return Course.objects.get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def _staff_course(course_id: str, actor: User, capability: str) -> Course:
    course = _course(course_id)
    require_course_capability(course=course, actor=actor, capability=capability)
    return course


def _require_student(course: Course, actor: User) -> Enrollment:
    enrollment = active_enrollment(course=course, student=actor)
    if enrollment is None:
        raise ActiveEnrollmentRequired(detail={"course_id": course.public_id})
    return enrollment


@transaction.atomic
def create_chapter(
    *, course_id: str, actor: User, title: str, summary: str, position: int, context: ActorContext
) -> Chapter:
    course = _staff_course(course_id, actor, "MANAGE_CONTENT")
    if course.status == Course.Status.ARCHIVED or position < 1:
        raise ContentStateConflict(detail={"course_status": course.status})
    try:
        chapter = Chapter.objects.create(
            course=course, title=title.strip(), summary=summary.strip(), position=position
        )
    except IntegrityError as exc:
        raise ContentStateConflict(detail={"position": position}) from exc
    _audit(
        context,
        action="course.chapter.create",
        target_type="chapter",
        target_ref=chapter.public_id,
        course_ref=course.public_id,
        after={"title": chapter.title},
    )
    return chapter


@transaction.atomic
def update_chapter(
    *,
    chapter_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    context: ActorContext,
) -> Chapter:
    try:
        chapter = (
            Chapter.objects.select_for_update().select_related("course").get(public_id=chapter_id)
        )
    except Chapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _staff_course(chapter.course.public_id, actor, "MANAGE_CONTENT")
    if chapter.status != Chapter.Status.DRAFT:
        raise ContentStateConflict(detail={"status": chapter.status})
    allowed = {
        key: value for key, value in changes.items() if key in {"title", "summary", "position"}
    }
    if "title" in allowed:
        allowed["title"] = str(allowed["title"]).strip()
    try:
        changed = compare_and_swap(
            Chapter, pk=chapter.pk, expected_version=expected_version, changes=allowed
        )
    except IntegrityError as exc:
        raise ContentStateConflict(detail={"position": allowed.get("position")}) from exc
    return changed


@transaction.atomic
def change_chapter_status(
    *, chapter_id: str, actor: User, expected_version: int, status: str, context: ActorContext
) -> Chapter:
    try:
        chapter = (
            Chapter.objects.select_for_update().select_related("course").get(public_id=chapter_id)
        )
    except Chapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _staff_course(chapter.course.public_id, actor, "MANAGE_CONTENT")
    valid = {
        Chapter.Status.PUBLISHED: Chapter.Status.DRAFT,
        Chapter.Status.WITHDRAWN: Chapter.Status.PUBLISHED,
    }
    if status not in valid or chapter.status != valid[status]:
        raise ContentStateConflict(detail={"from": chapter.status, "to": status})
    now = timezone.now()
    changes = {
        "status": status,
        "published_at": now if status == Chapter.Status.PUBLISHED else chapter.published_at,
        "withdrawn_at": now if status == Chapter.Status.WITHDRAWN else None,
    }
    changed = compare_and_swap(
        Chapter, pk=chapter.pk, expected_version=expected_version, changes=changes
    )
    _audit(
        context,
        action="course.chapter.status",
        target_type="chapter",
        target_ref=chapter.public_id,
        course_ref=chapter.course.public_id,
        before={"status": chapter.status},
        after={"status": status},
    )
    _event(
        context,
        event_type=events.COURSE_CONTENT_PUBLISHED,
        aggregate_type="chapter",
        aggregate_ref=chapter.public_id,
        payload={"course_id": chapter.course.public_id, "status": status},
    )
    return changed


def _validate_material_payload(
    material: Material, *, kind: str, text_content: str, link_url: str, asset_id: str | None
) -> ObjectAsset | None:
    if kind != material.kind:
        raise ContentStateConflict(detail={"kind": material.kind})
    asset = None
    if kind == Material.Kind.TEXT and not text_content.strip():
        raise ContentStateConflict(detail={"text_content": "required"})
    if kind == Material.Kind.LINK and not link_url.strip():
        raise ContentStateConflict(detail={"link_url": "required"})
    if kind == Material.Kind.FILE:
        if not asset_id:
            raise ContentStateConflict(detail={"object_asset": "required"})
        try:
            asset = ObjectAsset.objects.get(
                public_id=asset_id,
                scan_status=ObjectAsset.ScanStatus.CLEAN,
                status=ObjectAsset.Status.ACTIVE,
            )
        except ObjectAsset.DoesNotExist as exc:
            raise MaterialAssetNotClean(detail={"object_asset": asset_id}) from exc
    return asset


@transaction.atomic
def create_material(
    *,
    course_id: str,
    actor: User,
    chapter_id: str,
    title: str,
    kind: str,
    text_content: str,
    link_url: str,
    asset_id: str | None,
    context: ActorContext,
) -> Material:
    course = _staff_course(course_id, actor, "MANAGE_CONTENT")
    try:
        chapter = Chapter.objects.get(public_id=chapter_id, course=course)
    except Chapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if chapter.status == Chapter.Status.WITHDRAWN:
        raise ContentStateConflict(detail={"chapter_status": chapter.status})
    material = Material.objects.create(
        course=course, chapter=chapter, title=title.strip(), kind=kind
    )
    asset = _validate_material_payload(
        material, kind=kind, text_content=text_content, link_url=link_url, asset_id=asset_id
    )
    version = MaterialVersion.objects.create(
        material=material,
        version_no=1,
        text_content=text_content,
        link_url=link_url,
        object_asset=asset,
        created_by=actor,
    )
    Material.objects.filter(pk=material.pk).update(current_version=version)
    material.current_version = version
    return material


@transaction.atomic
def create_material_version(
    *,
    material_id: str,
    actor: User,
    expected_version: int | None,
    text_content: str,
    link_url: str,
    asset_id: str | None,
    context: ActorContext,
) -> MaterialVersion:
    try:
        material = (
            Material.objects.select_for_update().select_related("course").get(public_id=material_id)
        )
    except Material.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _staff_course(material.course.public_id, actor, "MANAGE_CONTENT")
    current = material.current_version
    if (
        expected_version is not None
        and current is not None
        and current.row_version != expected_version
    ):
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": current.row_version,
            }
        )
    version_no = (
        MaterialVersion.objects.filter(material=material).aggregate(value=Max("version_no"))[
            "value"
        ]
        or 0
    )
    asset = _validate_material_payload(
        material,
        kind=material.kind,
        text_content=text_content,
        link_url=link_url,
        asset_id=asset_id,
    )
    return MaterialVersion.objects.create(
        material=material,
        version_no=version_no + 1,
        text_content=text_content,
        link_url=link_url,
        object_asset=asset,
        created_by=actor,
    )


@transaction.atomic
def change_material_version_status(
    *, version_id: str, actor: User, expected_version: int, status: str, context: ActorContext
) -> MaterialVersion:
    try:
        version = (
            MaterialVersion.objects.select_for_update()
            .select_related("material__course", "material__chapter")
            .get(public_id=version_id)
        )
    except MaterialVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    material = version.material
    _staff_course(material.course.public_id, actor, "MANAGE_CONTENT")
    if status == MaterialVersion.Status.PUBLISHED:
        if (
            version.status != MaterialVersion.Status.DRAFT
            or material.chapter.status != Chapter.Status.PUBLISHED
        ):
            raise ContentStateConflict(
                detail={"version_status": version.status, "chapter_status": material.chapter.status}
            )
        if material.kind == Material.Kind.FILE and (
            version.object_asset is None
            or version.object_asset.scan_status != ObjectAsset.ScanStatus.CLEAN
        ):
            raise MaterialAssetNotClean()
        now = timezone.now()
        changed = compare_and_swap(
            MaterialVersion,
            pk=version.pk,
            expected_version=expected_version,
            changes={"status": status, "published_at": now},
        )
        Material.objects.filter(pk=material.pk).update(current_version=changed)
    elif status == MaterialVersion.Status.WITHDRAWN:
        if version.status != MaterialVersion.Status.PUBLISHED:
            raise ContentStateConflict(detail={"version_status": version.status})
        changed = compare_and_swap(
            MaterialVersion,
            pk=version.pk,
            expected_version=expected_version,
            changes={"status": status},
        )
    else:
        raise ContentStateConflict(detail={"status": status})
    _audit(
        context,
        action="course.material_version.status",
        target_type="material_version",
        target_ref=version.public_id,
        course_ref=material.course.public_id,
        before={"status": version.status},
        after={"status": status},
    )
    _event(
        context,
        event_type=events.COURSE_CONTENT_PUBLISHED,
        aggregate_type="material_version",
        aggregate_ref=version.public_id,
        payload={
            "course_id": material.course.public_id,
            "material_id": material.public_id,
            "status": status,
        },
    )
    return changed


@transaction.atomic
def create_announcement(
    *, course_id: str, actor: User, title: str, body: str, pinned: bool, context: ActorContext
) -> Announcement:
    course = _staff_course(course_id, actor, "MANAGE_CONTENT")
    return Announcement.objects.create(
        course=course, title=title.strip(), body=body, pinned=pinned, created_by=actor
    )


@transaction.atomic
def publish_announcement(
    *, announcement_id: str, actor: User, expected_version: int, context: ActorContext
) -> Announcement:
    try:
        item = (
            Announcement.objects.select_for_update()
            .select_related("course")
            .get(public_id=announcement_id)
        )
    except Announcement.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _staff_course(item.course.public_id, actor, "MANAGE_CONTENT")
    if item.status != Announcement.Status.DRAFT:
        raise ContentStateConflict(detail={"status": item.status})
    changed = compare_and_swap(
        Announcement,
        pk=item.pk,
        expected_version=expected_version,
        changes={"status": Announcement.Status.PUBLISHED, "publish_at": timezone.now()},
    )
    _event(
        context,
        event_type=events.COURSE_ANNOUNCEMENT_PUBLISHED,
        aggregate_type="announcement",
        aggregate_ref=item.public_id,
        payload={"course_id": item.course.public_id},
    )
    return changed


@transaction.atomic
def create_calendar_event(
    *,
    course_id: str,
    actor: User,
    title: str,
    description: str,
    starts_at: Any,
    ends_at: Any,
    context: ActorContext,
) -> CalendarEvent:
    course = _staff_course(course_id, actor, "MANAGE_CONTENT")
    if ends_at <= starts_at:
        raise ContentStateConflict(detail={"ends_at": "must_be_after_starts_at"})
    return CalendarEvent.objects.create(
        course=course,
        title=title.strip(),
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        created_by=actor,
    )


@transaction.atomic
def create_question(
    *, course_id: str, actor: User, title: str, body: str, context: ActorContext
) -> Question:
    course = _course(course_id)
    _require_student(course, actor)
    question = Question.objects.create(course=course, author=actor, title=title.strip(), body=body)
    _event(
        context,
        event_type=events.COURSE_QUESTION_CHANGED,
        aggregate_type="question",
        aggregate_ref=question.public_id,
        payload={"course_id": course.public_id, "status": question.status},
    )
    return question


@transaction.atomic
def answer_question(*, question_id: str, actor: User, body: str, context: ActorContext) -> Answer:
    try:
        question = (
            Question.objects.select_for_update().select_related("course").get(public_id=question_id)
        )
    except Question.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if has_qa_permission(question.course, actor):
        pass
    else:
        _require_student(question.course, actor)
    if question.status in {Question.Status.HIDDEN, Question.Status.LOCKED}:
        raise ContentStateConflict(detail={"status": question.status})
    answer = Answer.objects.create(question=question, author=actor, body=body)
    if question.status == Question.Status.OPEN:
        Question.objects.filter(pk=question.pk).update(status=Question.Status.ANSWERED)
    _event(
        context,
        event_type=events.COURSE_QUESTION_CHANGED,
        aggregate_type="question",
        aggregate_ref=question.public_id,
        payload={"course_id": question.course.public_id, "status": Question.Status.ANSWERED},
    )
    return answer


def has_qa_permission(course: Course, actor: User) -> bool:
    try:
        require_course_capability(course=course, actor=actor, capability="MODERATE_QA")
    except Exception:
        return False
    return True


@transaction.atomic
def moderate_question(
    *,
    question_id: str,
    actor: User,
    expected_version: int,
    status: str,
    reason: str,
    context: ActorContext,
) -> Question:
    try:
        question = (
            Question.objects.select_for_update().select_related("course").get(public_id=question_id)
        )
    except Question.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_course_capability(course=question.course, actor=actor, capability="MODERATE_QA")
    if status not in {Question.Status.HIDDEN, Question.Status.OPEN, Question.Status.LOCKED}:
        raise ContentStateConflict(detail={"status": status})
    changed = compare_and_swap(
        Question, pk=question.pk, expected_version=expected_version, changes={"status": status}
    )
    ModerationEvent.objects.create(
        question=question,
        actor=actor,
        from_status=question.status,
        to_status=status,
        reason=reason.strip(),
        trace_id=context.trace_id,
    )
    return changed


def _course_graph(extra: tuple[str, str] | None = None) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for row in CoursePrerequisite.objects.select_related("course", "prerequisite_course"):
        graph[row.course.public_id].add(row.prerequisite_course.public_id)
    if extra:
        graph[extra[0]].add(extra[1])
    return graph


def _has_cycle(graph: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


@transaction.atomic
def add_course_prerequisite(
    *, course_id: str, prerequisite_course_id: str, actor: User, context: ActorContext
) -> CoursePrerequisite:
    course = _course(course_id)
    require_owner(course=course, actor=actor)
    try:
        prerequisite = Course.objects.get(public_id=prerequisite_course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if course.pk == prerequisite.pk:
        raise PrerequisiteCycle()
    if _has_cycle(_course_graph((course.public_id, prerequisite.public_id))):
        raise PrerequisiteCycle()
    try:
        return CoursePrerequisite.objects.create(
            course=course,
            prerequisite_course=prerequisite,
            created_by=actor,
            trace_id=context.trace_id,
        )
    except IntegrityError as exc:
        raise ContentStateConflict(detail={"prerequisite": prerequisite.public_id}) from exc


def prerequisite_status(*, course: Course, student: User) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in course.prerequisites.select_related("prerequisite_course"):
        result.append({
            "prerequisite_course_id": row.prerequisite_course.public_id,
            "status": "NOT_EVALUABLE",
            "reason": "COMPLETION_FACT_UNAVAILABLE",
        })
    return result


@transaction.atomic
def add_chapter_prerequisite(
    *,
    chapter_id: str,
    prerequisite_chapter_id: str,
    actor: User,
    context: ActorContext,
) -> ChapterPrerequisite:
    try:
        chapter = (
            Chapter.objects.select_for_update().select_related("course").get(public_id=chapter_id)
        )
        prerequisite = Chapter.objects.get(public_id=prerequisite_chapter_id)
    except Chapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if chapter.course_id != prerequisite.course_id or chapter.pk == prerequisite.pk:
        raise CrossCourseReference()
    _staff_course(chapter.course.public_id, actor, "MANAGE_CONTENT")
    graph: dict[int, set[int]] = defaultdict(set)
    for row in ChapterPrerequisite.objects.filter(chapter__course=chapter.course).values_list(
        "chapter_id", "prerequisite_chapter_id"
    ):
        graph[row[0]].add(row[1])
    graph[chapter.pk].add(prerequisite.pk)
    visiting: set[int] = set()
    visited: set[int] = set()

    def visit(node: int) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(visit(node) for node in graph):
        raise PrerequisiteCycle()
    try:
        return ChapterPrerequisite.objects.create(
            chapter=chapter,
            prerequisite_chapter=prerequisite,
            created_by=actor,
            trace_id=context.trace_id,
        )
    except IntegrityError as exc:
        raise ContentStateConflict(detail={"prerequisite": prerequisite.public_id}) from exc


def invitation_digest(code: str) -> str:
    return hmac.new(
        str(settings.COURSE_INVITATION_HMAC_KEY).encode(), code.encode(), hashlib.sha256
    ).hexdigest()


@transaction.atomic
def create_invitation(
    *, course_id: str, actor: User, max_uses: int, expires_at: Any, context: ActorContext
) -> tuple[Invitation, str]:
    course = _staff_course(course_id, actor, "MANAGE_ENROLLMENT")
    require_owner(course=course, actor=actor) if max_uses > 1000000 else None
    if expires_at <= timezone.now() or max_uses < 1:
        raise InvitationInvalid()
    raw = secrets.token_urlsafe(24)
    invitation = Invitation.objects.create(
        course=course,
        code_digest=invitation_digest(raw),
        code_masked=f"{raw[:4]}...{raw[-4:]}",
        max_uses=max_uses,
        expires_at=expires_at,
        created_by=actor,
    )
    return invitation, raw


def consume_invitation(*, course: Course, code: str) -> Invitation:
    digest = invitation_digest(code)
    try:
        invitation = Invitation.objects.select_for_update().get(
            course=course, code_digest=digest, status="ACTIVE"
        )
    except Invitation.DoesNotExist as exc:
        raise InvitationInvalid() from exc
    if invitation.expires_at <= timezone.now() or invitation.used_count >= invitation.max_uses:
        raise InvitationInvalid()
    Invitation.objects.filter(pk=invitation.pk).update(used_count=invitation.used_count + 1)
    return invitation


def _normalize_identity(value: str) -> str:
    return value.strip().casefold()


@transaction.atomic
def precheck_import(
    *, course_id: str, actor: User, rows: Iterable[str], filename: str, context: ActorContext
) -> EnrollmentImportJob:
    course = _staff_course(course_id, actor, "MANAGE_ENROLLMENT")
    job = EnrollmentImportJob.objects.create(
        course=course, created_by=actor, filename=filename[:255]
    )
    reader = csv.DictReader(rows)
    total = valid = 0
    for row_no, row in enumerate(reader, start=2):
        raw = str(row.get("email") or row.get("username") or "")
        identity = _normalize_identity(raw)
        error = ""
        if not identity:
            error = "IDENTITY_REQUIRED"
        elif (
            not User.objects.filter(email__iexact=identity).exists()
            and not User.objects.filter(username__iexact=identity).exists()
        ):
            error = "USER_NOT_FOUND"
        total += 1
        valid += not bool(error)
        EnrollmentImportItem.objects.create(
            job=job,
            row_no=row_no,
            normalized_identity=identity,
            status="READY" if not error else "ERROR",
            error_code=error,
        )
    EnrollmentImportJob.objects.filter(pk=job.pk).update(
        status=EnrollmentImportJob.Status.READY,
        summary={"total": total, "valid": valid, "errors": total - valid},
    )
    job.status = EnrollmentImportJob.Status.READY
    job.summary = {"total": total, "valid": valid, "errors": total - valid}
    return job


@transaction.atomic
def create_import_job(
    *, course_id: str, actor: User, csv_payload: str, filename: str, context: ActorContext
) -> EnrollmentImportJob:
    """Persist an upload before queueing precheck work.

    The payload is retained only for the bounded precheck window; row identities and
    validation results are materialized by ``precheck_import_job`` and the raw CSV is
    cleared when precheck completes.
    """
    course = _staff_course(course_id, actor, "MANAGE_ENROLLMENT")
    if len(csv_payload.encode("utf-8")) > 10 * 1024 * 1024:
        raise ContentStateConflict(detail={"file": "too_large"})
    return EnrollmentImportJob.objects.create(
        course=course,
        created_by=actor,
        filename=filename[:255],
        source_csv=csv_payload,
        status=EnrollmentImportJob.Status.PRECHECKING,
    )


@transaction.atomic
def precheck_import_job(*, job_id: str, actor: User, context: ActorContext) -> EnrollmentImportJob:
    try:
        job = (
            EnrollmentImportJob.objects.select_for_update()
            .select_related("course")
            .get(public_id=job_id)
        )
    except EnrollmentImportJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_course_capability(course=job.course, actor=actor, capability="MANAGE_ENROLLMENT")
    if job.status != EnrollmentImportJob.Status.PRECHECKING:
        return job
    reader = csv.DictReader(job.source_csv.splitlines())
    total = valid = 0
    for row_no, row in enumerate(reader, start=2):
        raw = str(row.get("email") or row.get("username") or "")
        identity = _normalize_identity(raw)
        error = ""
        if not identity:
            error = "IDENTITY_REQUIRED"
        elif (
            not User.objects.filter(email__iexact=identity).exists()
            and not User.objects.filter(username__iexact=identity).exists()
        ):
            error = "USER_NOT_FOUND"
        total += 1
        valid += not bool(error)
        EnrollmentImportItem.objects.create(
            job=job,
            row_no=row_no,
            normalized_identity=identity,
            status="READY" if not error else "ERROR",
            error_code=error,
        )
    summary = {"total": total, "valid": valid, "errors": total - valid}
    EnrollmentImportJob.objects.filter(pk=job.pk).update(
        status=EnrollmentImportJob.Status.READY,
        summary=summary,
        source_csv="",
    )
    job.status = EnrollmentImportJob.Status.READY
    job.summary = summary
    job.source_csv = ""
    return job


def execute_import(*, job_id: str, actor: User, context: ActorContext) -> EnrollmentImportJob:
    try:
        job = (
            EnrollmentImportJob.objects.select_for_update()
            .select_related("course")
            .get(public_id=job_id)
        )
    except EnrollmentImportJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_course_capability(course=job.course, actor=actor, capability="MANAGE_ENROLLMENT")
    with transaction.atomic():
        locked_job = EnrollmentImportJob.objects.select_for_update().get(pk=job.pk)
        if (
            locked_job.status == EnrollmentImportJob.Status.COMPLETED
            and not locked_job.items.exclude(status="SUCCEEDED").exists()
        ):
            return locked_job
        EnrollmentImportJob.objects.filter(pk=locked_job.pk).update(
            status=EnrollmentImportJob.Status.RUNNING
        )
        item_ids = list(
            locked_job.items.filter(status__in=("READY", "ERROR"))
            .order_by("row_no")
            .values_list("pk", flat=True)
        )

    # Each row has its own transaction so a worker retry preserves completed rows.
    for item_id in item_ids:
        with transaction.atomic():
            item = EnrollmentImportItem.objects.select_for_update().get(pk=item_id)
            if item.status == "SUCCEEDED":
                continue
            user = (
                User.objects.filter(email__iexact=item.normalized_identity).first()
                or User.objects.filter(username__iexact=item.normalized_identity).first()
            )
            if user is None:
                EnrollmentImportItem.objects.filter(pk=item.pk).update(
                    status="ERROR", error_code="USER_NOT_FOUND"
                )
                continue
            try:
                enrollment = apply_for_course(
                    course_id=job.course.public_id,
                    student=user,
                    application_message="CSV_IMPORT",
                    context=context,
                )
            except Exception as exc:
                EnrollmentImportItem.objects.filter(pk=item.pk).update(
                    status="ERROR", error_code=getattr(exc, "code", "ENROLLMENT_FAILED")
                )
            else:
                EnrollmentImportItem.objects.filter(pk=item.pk).update(
                    status="SUCCEEDED", enrollment=enrollment
                )

    with transaction.atomic():
        completed = EnrollmentImportJob.objects.select_for_update().get(pk=job.pk)
        counts = {
            "total": completed.items.count(),
            "succeeded": completed.items.filter(status="SUCCEEDED").count(),
            "failed": completed.items.exclude(status="SUCCEEDED").count(),
        }
        EnrollmentImportJob.objects.filter(pk=completed.pk).update(
            status=EnrollmentImportJob.Status.COMPLETED, summary=counts
        )
        completed.status = EnrollmentImportJob.Status.COMPLETED
        completed.summary = counts
        return completed


@transaction.atomic
def create_copy_job(
    *, course_id: str, actor: User, options: dict[str, Any], context: ActorContext
) -> CourseCopyJob:
    course = _course(course_id)
    require_owner(course=course, actor=actor)
    return CourseCopyJob.objects.create(source_course=course, created_by=actor, options=options)


@transaction.atomic
def execute_copy_job(*, job_id: str, actor: User, context: ActorContext) -> CourseCopyJob:
    try:
        job = (
            CourseCopyJob.objects.select_for_update()
            .select_related("source_course")
            .get(public_id=job_id)
        )
    except CourseCopyJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_owner(course=job.source_course, actor=actor)
    source = job.source_course
    if job.status == CourseCopyJob.Status.COMPLETED:
        return job
    CourseCopyJob.objects.filter(pk=job.pk).update(status=CourseCopyJob.Status.RUNNING)
    code = str(job.options.get("code") or f"{source.code}-COPY-{job.public_id[-6:]}")[:64]
    target = Course.objects.filter(code=code).first()
    if target is None:
        target = Course.objects.create(
            code=code,
            title=str(job.options.get("title") or f"{source.title}（副本）"),
            summary=source.summary,
            description=source.description,
            owner=actor,
            visibility=source.visibility,
            enrollment_mode=source.enrollment_mode,
            capacity=source.capacity,
            enrollment_start=source.enrollment_start,
            enrollment_end=source.enrollment_end,
            teaching_start=source.teaching_start,
            teaching_end=source.teaching_end,
        )
        from .services import _staff_event

        staff = target.staff.create(
            user=actor,
            role="OWNER",
            status="ACTIVE",
            appointed_by=actor,
            appointed_at=timezone.now(),
        )
        _staff_event(
            staff=staff,
            from_role="",
            from_status="",
            actor=actor,
            reason="COURSE_COPY",
            context=context,
        )
        for chapter in source.chapters.all().order_by("position"):
            new_chapter = Chapter.objects.create(
                course=target,
                title=chapter.title,
                summary=chapter.summary,
                position=chapter.position,
                status=Chapter.Status.DRAFT,
            )
            CourseCopyItem.objects.create(
                job=job,
                item_type="CHAPTER",
                source_ref=chapter.public_id,
                target_ref=new_chapter.public_id,
                status="SUCCEEDED",
            )
            for material in chapter.materials.all():
                new_material = Material.objects.create(
                    course=target, chapter=new_chapter, title=material.title, kind=material.kind
                )
                copied_current = None
                for version in material.versions.all().order_by("version_no"):
                    new_version = MaterialVersion.objects.create(
                        material=new_material,
                        version_no=version.version_no,
                        status=MaterialVersion.Status.DRAFT,
                        text_content=version.text_content,
                        link_url=version.link_url,
                        object_asset=version.object_asset,
                        digest_sha256=version.digest_sha256,
                        created_by=actor,
                    )
                    if material.current_version_id == version.pk:
                        copied_current = new_version
                    CourseCopyItem.objects.create(
                        job=job,
                        item_type="MATERIAL_VERSION",
                        source_ref=version.public_id,
                        target_ref=new_version.public_id,
                        status="SUCCEEDED",
                    )
                if copied_current is not None:
                    Material.objects.filter(pk=new_material.pk).update(
                        current_version=copied_current
                    )
                    new_material.current_version = copied_current
        if job.options.get("include_announcements", True):
            for announcement in source.announcements.all():
                Announcement.objects.create(
                    course=target,
                    title=announcement.title,
                    body=announcement.body,
                    pinned=announcement.pinned,
                    status=Announcement.Status.DRAFT,
                    created_by=actor,
                )
        if job.options.get("include_calendar", True):
            for event in source.calendar_events.all():
                CalendarEvent.objects.create(
                    course=target,
                    title=event.title,
                    description=event.description,
                    starts_at=event.starts_at,
                    ends_at=event.ends_at,
                    created_by=actor,
                )
        from .ports import run_course_copy_handlers

        run_course_copy_handlers(
            job=job,
            source=source,
            target=target,
            actor=actor,
            context=context,
        )
    CourseCopyJob.objects.filter(pk=job.pk).update(
        status=CourseCopyJob.Status.COMPLETED, target_course=target
    )
    job.status = CourseCopyJob.Status.COMPLETED
    job.target_course = target
    return job
