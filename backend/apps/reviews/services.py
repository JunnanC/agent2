import hashlib
import json
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from apps.accounts.errors import PortalAccessDenied
from apps.accounts.models import User
from apps.core.audit import append_audit, append_failure, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.models import Course, CourseCopyItem, CourseCopyJob, CourseStaffGrant
from apps.courses.selectors import require_course_capability, visible_course
from apps.courses.services import ActorContext
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.experiments.services import transition_task
from apps.labtemplates.models import AutoCheckRule
from apps.labtemplates.services import build_execution_command
from apps.reports.models import (
    ReportDraft,
    ReportVersion,
    ReportVersionAttachment,
    SystemArtifact,
)

from . import events
from .checkers import (
    AUTO_CHECK_TERMINAL_STATUSES,
    AutoCheckRejected,
    auto_check_executor,
    submitted_execution_contract,
)
from .errors import (
    AutoCheckPending,
    ReviewStateConflict,
    ReviewValidationError,
    RubricStateConflict,
    RubricValidationError,
    SimilarityUnavailable,
)
from .metrics import AUTO_CHECK_RUNS_TOTAL, REVIEW_DECISIONS_TOTAL, SIMILARITY_RUNS_TOTAL
from .models import (
    AIScoreBatch,
    AIScoreSuggestion,
    AnnotationRevision,
    AutoCheckRun,
    CriterionScore,
    CriterionScoreEvent,
    Review,
    ReviewAnnotation,
    ReviewDecision,
    Rubric,
    RubricCriterion,
    RubricVersion,
    SimilarityMatch,
    SimilarityRun,
)


def _course(course_id: str, actor: User) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
    )
    return course


def _audit(
    context: ActorContext,
    *,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    after: Any,
) -> None:
    append_audit(
        actor_ref=context.actor_ref,
        actor_portal=context.portal,
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
        after=after,
        result="SUCCEEDED",
        trace_id=context.trace_id,
        client_ip_hash=hash_client_ip(context.client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=context.user_agent,
    )


def _event(
    context: ActorContext,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=payload,
        trace_id=context.trace_id,
    )
    enqueue_relay_after_commit(trace_id=context.trace_id)


def _expected(actual: int, expected: int) -> None:
    if actual != expected:
        raise RowVersionConflict(
            detail={"expected_row_version": expected, "actual_row_version": actual}
        )


@transaction.atomic
def create_rubric(
    *, course_id: str, actor: User, name: str, description: str, context: ActorContext
) -> Rubric:
    course = _course(course_id, actor)
    try:
        rubric = Rubric.objects.create(
            course=course,
            name=name.strip(),
            description=description.strip(),
            owner=actor,
        )
    except IntegrityError as exc:
        raise RubricStateConflict(detail={"name": "already_exists"}) from exc
    _audit(
        context,
        action="rubric.create",
        target_type="rubric",
        target_ref=rubric.public_id,
        course_ref=course.public_id,
        after={"name": rubric.name},
    )
    _event(
        context,
        event_type=events.RUBRIC_CREATED,
        aggregate_type="rubric",
        aggregate_ref=rubric.public_id,
        payload={"course_id": course.public_id},
    )
    return rubric


def _criteria_payload(criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positions = [int(item.get("position", 0)) for item in criteria]
    if (
        not criteria
        or any(position < 1 for position in positions)
        or len(positions) != len(set(positions))
    ):
        raise RubricValidationError(detail={"position": "unique_positive_required"})
    result: list[dict[str, Any]] = []
    for item in criteria:
        max_score = Decimal(str(item.get("max_score", 0)))
        weight = int(item.get("weight_basis_points", 0))
        title = str(item.get("title", "")).strip()
        if not title or max_score <= 0 or not 1 <= weight <= 10000:
            raise RubricValidationError(detail={"criterion": "positive_score_and_weight_required"})
        result.append({
            "position": int(item["position"]),
            "position_key": str(item["position"]),
            "title": title,
            "description": str(item.get("description", "")).strip(),
            "guidance": str(item.get("guidance", "")).strip(),
            "max_score": max_score,
            "weight_basis_points": weight,
        })
    return result


@transaction.atomic
def create_rubric_version(
    *,
    course_id: str,
    rubric_id: str,
    actor: User,
    title: str,
    description: str,
    total_score: Decimal,
    criteria: list[dict[str, Any]],
    context: ActorContext,
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        rubric = Rubric.objects.select_for_update().get(public_id=rubric_id, course=course)
    except Rubric.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    latest = rubric.versions.order_by("-version_no").first()
    version = RubricVersion.objects.create(
        rubric=rubric,
        version_no=(latest.version_no if latest else 0) + 1,
        title=title.strip(),
        description=description.strip(),
        total_score=total_score,
        created_by=actor,
    )
    RubricCriterion.objects.bulk_create([
        RubricCriterion(rubric_version=version, **item) for item in _criteria_payload(criteria)
    ])
    _audit(
        context,
        action="rubric.version.create",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"version_no": version.version_no},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_CREATED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id, "rubric_id": rubric.public_id},
    )
    return version


@transaction.atomic
def clone_rubric_version(
    *,
    course_id: str,
    rubric_id: str,
    source_version_id: str,
    actor: User,
    context: ActorContext,
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        rubric = Rubric.objects.select_for_update().get(public_id=rubric_id, course=course)
        source = (
            RubricVersion.objects.select_related("rubric")
            .prefetch_related("criteria")
            .get(public_id=source_version_id, rubric=rubric)
        )
    except (Rubric.DoesNotExist, RubricVersion.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    latest = rubric.versions.order_by("-version_no").first()
    version = RubricVersion.objects.create(
        rubric=rubric,
        version_no=(latest.version_no if latest else 0) + 1,
        title=source.title,
        description=source.description,
        total_score=source.total_score,
        created_by=actor,
    )
    RubricCriterion.objects.bulk_create([
        RubricCriterion(
            rubric_version=version,
            position=item.position,
            position_key=str(item.position),
            title=item.title,
            description=item.description,
            guidance=item.guidance,
            max_score=item.max_score,
            weight_basis_points=item.weight_basis_points,
        )
        for item in source.criteria.filter(is_active=True)
    ])
    _audit(
        context,
        action="rubric.version.clone",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"source_version_id": source.public_id, "version_no": version.version_no},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_CREATED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={
            "course_id": course.public_id,
            "rubric_id": rubric.public_id,
            "source_version_id": source.public_id,
        },
    )
    return version


@transaction.atomic
def update_rubric_version(
    *,
    course_id: str,
    version_id: str,
    actor: User,
    expected_version: int,
    title: str,
    description: str,
    total_score: Decimal,
    criteria: list[dict[str, Any]],
    context: ActorContext,
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        version = RubricVersion.objects.select_for_update().get(
            public_id=version_id, rubric__course=course
        )
    except RubricVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(version.row_version, expected_version)
    if version.status != RubricVersion.Status.DRAFT:
        raise RubricStateConflict(detail={"status": version.status})
    payload = _criteria_payload(criteria)
    for criterion in RubricCriterion.objects.select_for_update().filter(
        rubric_version=version, is_active=True
    ):
        compare_and_swap(
            RubricCriterion,
            pk=criterion.pk,
            expected_version=criterion.row_version,
            changes={
                "is_active": False,
                "position_key": f"removed:{criterion.public_id}",
            },
        )
    RubricCriterion.objects.bulk_create([
        RubricCriterion(rubric_version=version, **item) for item in payload
    ])
    changed = compare_and_swap(
        RubricVersion,
        pk=version.pk,
        expected_version=expected_version,
        changes={
            "title": title.strip(),
            "description": description.strip(),
            "total_score": total_score,
        },
    )
    _audit(
        context,
        action="rubric.version.update",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"criteria_count": len(payload)},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_UPDATED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def publish_rubric_version(
    *, course_id: str, version_id: str, actor: User, expected_version: int, context: ActorContext
) -> RubricVersion:
    course = _course(course_id, actor)
    try:
        version = (
            RubricVersion.objects.select_for_update()
            .select_related("rubric")
            .prefetch_related("criteria")
            .get(public_id=version_id, rubric__course=course)
        )
    except RubricVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    _expected(version.row_version, expected_version)
    if version.status != RubricVersion.Status.DRAFT:
        raise RubricStateConflict(detail={"status": version.status})
    criteria = list(version.criteria.filter(is_active=True))
    if not criteria or sum(item.weight_basis_points for item in criteria) != 10000:
        raise RubricValidationError(detail={"weight_basis_points": "must_total_10000"})
    if sum((item.max_score for item in criteria), Decimal("0")) != version.total_score:
        raise RubricValidationError(detail={"total_score": "criterion_sum_mismatch"})
    changed = compare_and_swap(
        RubricVersion,
        pk=version.pk,
        expected_version=expected_version,
        changes={
            "status": RubricVersion.Status.PUBLISHED,
            "published_by": actor,
            "published_at": timezone.now(),
        },
    )
    Rubric.objects.filter(pk=version.rubric_id).update(
        status=Rubric.Status.PUBLISHED,
        current_version_id=version.pk,
        row_version=F("row_version") + 1,
    )
    _audit(
        context,
        action="rubric.version.publish",
        target_type="rubric_version",
        target_ref=version.public_id,
        course_ref=course.public_id,
        after={"status": "PUBLISHED"},
    )
    _event(
        context,
        event_type=events.RUBRIC_VERSION_PUBLISHED,
        aggregate_type="rubric_version",
        aggregate_ref=version.public_id,
        payload={"course_id": course.public_id},
    )
    return changed  # type: ignore[return-value]


def copy_rubrics(
    job: CourseCopyJob, source: Course, target: Course, actor: User, context: ActorContext
) -> None:
    if not job.options.get("include_rubrics", True):
        return
    for source_rubric in Rubric.objects.filter(course=source).select_related("current_version"):
        target_rubric = Rubric.objects.create(
            course=target,
            name=source_rubric.name,
            description=source_rubric.description,
            owner=actor,
        )
        CourseCopyItem.objects.create(
            job=job,
            item_type="RUBRIC",
            source_ref=source_rubric.public_id,
            target_ref=target_rubric.public_id,
            status="SUCCEEDED",
        )
        current = source_rubric.current_version
        if current is None:
            continue
        clone = RubricVersion.objects.create(
            rubric=target_rubric,
            version_no=1,
            title=current.title,
            description=current.description,
            total_score=current.total_score,
            created_by=actor,
        )
        RubricCriterion.objects.bulk_create([
            RubricCriterion(
                rubric_version=clone,
                position=item.position,
                position_key=str(item.position),
                title=item.title,
                description=item.description,
                guidance=item.guidance,
                max_score=item.max_score,
                weight_basis_points=item.weight_basis_points,
            )
            for item in current.criteria.filter(is_active=True)
        ])
        CourseCopyItem.objects.create(
            job=job,
            item_type="RUBRIC_VERSION",
            source_ref=current.public_id,
            target_ref=clone.public_id,
            status="SUCCEEDED",
        )


def _require_teaching(context: ActorContext) -> None:
    if context.portal != "TEACHING":
        raise PortalAccessDenied(detail={"required_portal": "TEACHING"})


def _locked_review_course(
    *, course_id: str, actor: User, context: ActorContext
) -> tuple[Course, Any]:
    _require_teaching(context)
    visible = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    course = Course.objects.select_for_update().get(pk=visible.pk)
    staff = require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
    )
    return course, staff


def _review_for_update(*, course: Course, review_id: str) -> Review:
    try:
        # MySQL applies FOR UPDATE to joined rows too. Keep immutable submission
        # tables outside the locking query so the runtime account only needs
        # SELECT on frozen report and artifact facts.
        return Review.objects.select_for_update().get(public_id=review_id, course=course)
    except Review.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def _assert_review_version(review: Review, expected_version: int) -> None:
    if review.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": review.row_version,
            }
        )


def _enqueue_auto_check_runs(run_ids: list[str]) -> None:
    if not run_ids:
        return

    def enqueue() -> None:
        from .tasks import run_auto_check

        for run_id in run_ids:
            run_auto_check.apply_async(kwargs={"run_id": run_id})

    transaction.on_commit(enqueue)


def _frozen_execution_contract(
    *, task: ExperimentTask, report_version: ReportVersion | None
) -> tuple[dict[str, Any], str]:
    """Return the exact execution contract used by both student and judge runs."""
    spec = dict(task.execution_spec or task.template_version.execution_spec or {})
    summary: dict[str, Any] = {
        "language": spec.get("language", ""),
        "entrypoint": spec.get("entrypoint", ""),
        "timeout_seconds": spec.get("timeout_seconds", 0),
        "memory_mb": spec.get("memory_mb", 0),
        "cpu_millicores": spec.get("cpu_millicores", 0),
        "comparator": spec.get("comparator", "token"),
        "network_mode": spec.get("network_mode", "DENY_ALL"),
        "tests_asset": spec.get("tests_asset", ""),
        "command": [],
    }
    try:
        summary["command"] = list(build_execution_command(spec))
    except Exception:  # noqa: BLE001 - legacy FakeRuntime tasks have no spec
        summary["command"] = []
    digest = hashlib.sha256(
        json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    # ReportVersion is itself server-created, but keep the task snapshot as
    # the authority if a stale or malformed report fact is ever replayed.
    if report_version is not None and report_version.execution_rule_summary:
        report_summary = dict(report_version.execution_rule_summary)
        report_digest = str(report_version.execution_rule_digest or "")
        if report_digest == digest and report_summary == summary:
            return report_summary, report_digest
    return summary, digest


@transaction.atomic
def create_review_for_submission(
    *,
    task: ExperimentTask,
    context: ActorContext,
    report_version: ReportVersion | None = None,
    system_artifact: SystemArtifact | None = None,
) -> Review:
    if (report_version is None) == (system_artifact is None):
        raise ReviewValidationError(detail={"target": "exactly_one_required"})
    locked_task = (
        ExperimentTask.objects.select_for_update()
        .select_related("course", "publication__rubric_version", "template_version", "student")
        .get(pk=task.pk)
    )
    if report_version is not None and report_version.task_id != locked_task.pk:
        raise ReviewValidationError(detail={"report_version": "task_mismatch"})
    if system_artifact is not None and system_artifact.task_id != locked_task.pk:
        raise ReviewValidationError(detail={"system_artifact": "task_mismatch"})
    latest_round = (
        Review.objects.filter(task=locked_task).aggregate(value=Max("round_no"))["value"] or 0
    )
    review = Review.objects.create(
        course=locked_task.course,
        task=locked_task,
        round_no=latest_round + 1,
        rubric_version=locked_task.publication.rubric_version,
        report_version=report_version,
        system_artifact=system_artifact,
    )
    run_ids: list[str] = []
    if locked_task.publication.review_mode == "MANUAL_WITH_AUTO_CHECK":
        asset = (
            report_version.workspace_snapshot.asset
            if report_version is not None
            else system_artifact.asset  # type: ignore[union-attr]
        )
        artifact_digest = (
            report_version.snapshot_digest
            if report_version is not None
            else system_artifact.digest_sha256  # type: ignore[union-attr]
        )
        if (locked_task.execution_spec or {}).get("schema_version") == 2:
            execution_summary, execution_digest = submitted_execution_contract(locked_task, review)
        else:
            execution_summary, execution_digest = _frozen_execution_contract(
                task=locked_task, report_version=report_version
            )
        for rule in AutoCheckRule.objects.filter(
            template_version=locked_task.template_version, is_active=True
        ).order_by("position"):
            run = AutoCheckRun.objects.create(
                review=review,
                rule=rule,
                input_asset=asset,
                checker_type=rule.checker_type,
                rule_digest=rule.rule_digest,
                artifact_digest=artifact_digest,
                execution_rule_summary=execution_summary,
                execution_rule_digest=execution_digest,
                trace_id=context.trace_id,
            )
            run_ids.append(run.public_id)
    _audit(
        context,
        action="review.create",
        target_type="review",
        target_ref=review.public_id,
        course_ref=locked_task.course.public_id,
        after={"task_id": locked_task.public_id, "round_no": review.round_no},
    )
    _event(
        context,
        event_type=events.REVIEW_CREATED,
        aggregate_type="review",
        aggregate_ref=review.public_id,
        payload={
            "course_id": locked_task.course.public_id,
            "task_id": locked_task.public_id,
            "user_id": locked_task.student.public_id,
            "round_no": review.round_no,
        },
    )
    _enqueue_auto_check_runs(run_ids)
    return review


@transaction.atomic
def score_review_criteria(
    *,
    course_id: str,
    review_id: str,
    actor: User,
    expected_version: int,
    scores: list[dict[str, Any]],
    context: ActorContext,
) -> Review:
    course, _staff = _locked_review_course(course_id=course_id, actor=actor, context=context)
    review = _review_for_update(course=course, review_id=review_id)
    _assert_review_version(review, expected_version)
    if review.status == Review.Status.DECIDED:
        raise ReviewStateConflict(detail={"status": review.status})
    if not scores:
        raise ReviewValidationError(detail={"scores": "non_empty_required"})
    criteria = {
        item.public_id: item
        for item in RubricCriterion.objects.filter(
            rubric_version=review.rubric_version, is_active=True
        )
    }
    seen: set[str] = set()
    changed_count = 0
    for item in scores:
        criterion_id = str(item.get("criterion_id", ""))
        if criterion_id in seen or criterion_id not in criteria:
            raise ReviewValidationError(detail={"criterion_id": criterion_id})
        seen.add(criterion_id)
        criterion = criteria[criterion_id]
        value = Decimal(str(item.get("score", "0")))
        note = str(item.get("note", "")).strip()
        if value < 0 or value > criterion.max_score:
            raise ReviewValidationError(
                detail={"criterion_id": criterion_id, "max_score": str(criterion.max_score)}
            )
        projection = (
            CriterionScore.objects.select_for_update()
            .filter(review=review, criterion=criterion)
            .first()
        )
        if projection is None:
            projection = CriterionScore.objects.create(
                review=review,
                criterion=criterion,
                score=value,
                note=note,
                revision_no=1,
                updated_by=actor,
            )
        elif projection.score == value and projection.note == note:
            continue
        else:
            projection = compare_and_swap(
                CriterionScore,
                pk=projection.pk,
                expected_version=projection.row_version,
                changes={
                    "score": value,
                    "note": note,
                    "revision_no": projection.revision_no + 1,
                    "updated_by": actor,
                },
            )  # type: ignore[assignment]
        CriterionScoreEvent.objects.create(
            score_projection=projection,
            review=review,
            criterion=criterion,
            revision_no=projection.revision_no,
            score=value,
            note=note,
            actor=actor,
            trace_id=context.trace_id,
        )
        changed_count += 1
    if changed_count == 0:
        return review
    changed = compare_and_swap(
        Review,
        pk=review.pk,
        expected_version=expected_version,
        changes={"status": Review.Status.IN_REVIEW},
    )
    _audit(
        context,
        action="review.score",
        target_type="review",
        target_ref=review.public_id,
        course_ref=course.public_id,
        after={"changed_criteria": changed_count},
    )
    _event(
        context,
        event_type=events.REVIEW_SCORED,
        aggregate_type="review",
        aggregate_ref=review.public_id,
        payload={"course_id": course.public_id, "task_id": review.task.public_id},
    )
    return changed  # type: ignore[return-value]


def _refresh_ai_score_batch_status(batch_id: int) -> AIScoreBatch:
    batch = AIScoreBatch.objects.select_for_update().get(pk=batch_id)
    statuses = list(batch.suggestions.values_list("status", flat=True))
    if any(
        status in (AIScoreSuggestion.Status.QUEUED, AIScoreSuggestion.Status.RUNNING)
        for status in statuses
    ):
        target = AIScoreBatch.Status.RUNNING
    elif AIScoreSuggestion.Status.READY in statuses:
        target = AIScoreBatch.Status.REVIEW_REQUIRED
    elif AIScoreSuggestion.Status.FAILED in statuses:
        target = (
            AIScoreBatch.Status.COMPLETED_WITH_ERRORS
            if AIScoreSuggestion.Status.ACCEPTED in statuses
            else AIScoreBatch.Status.FAILED
        )
    else:
        target = AIScoreBatch.Status.COMPLETED
    if batch.status == target:
        return batch
    return compare_and_swap(
        AIScoreBatch,
        pk=batch.pk,
        expected_version=batch.row_version,
        changes={"status": target},
    )  # type: ignore[return-value]


@transaction.atomic
def start_ai_score_batch(
    *, course_id: str, publication_id: str, actor: User, context: ActorContext
) -> AIScoreBatch:
    course = _course(course_id, actor)
    try:
        publication = TaskPublication.objects.get(public_id=publication_id, course=course)
    except TaskPublication.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if (
        publication.status != TaskPublication.Status.CLOSED
        and publication.window_end > timezone.now()
    ):
        raise ReviewStateConflict(detail={"publication": "experiment_not_ended"})
    reviews = list(
        Review.objects.filter(
            course=course,
            task__publication=publication,
            task__status=ExperimentTask.Status.UNDER_REVIEW,
        )
        .exclude(status=Review.Status.DECIDED)
        .filter(Q(report_version__isnull=False) | Q(system_artifact__isnull=False))
        .order_by("id")
    )
    if not reviews:
        raise ReviewValidationError(detail={"publication_id": "no_submissions_ready_for_review"})
    batch = AIScoreBatch.objects.create(
        course=course,
        publication=publication,
        created_by=actor,
        entry_count=len(reviews),
    )
    suggestions = AIScoreSuggestion.objects.bulk_create(
        [
            AIScoreSuggestion(
                batch=batch,
                review=review,
                review_row_version=review.row_version,
            )
            for review in reviews
        ]
    )
    _audit(
        context,
        action="review.ai_score_batch.create",
        target_type="ai_score_batch",
        target_ref=batch.public_id,
        course_ref=course.public_id,
        after={"publication_id": publication.public_id, "entry_count": len(suggestions)},
    )

    def enqueue() -> None:
        from .tasks import run_ai_score_suggestion

        for suggestion in suggestions:
            run_ai_score_suggestion.apply_async(
                kwargs={"suggestion_id": suggestion.public_id, "trace_id": context.trace_id}
            )

    transaction.on_commit(enqueue, robust=True)
    return batch


def submitted_project_files(review: Review) -> dict[str, bytes]:
    """Read only the immutable student submission, never private teacher assets."""
    from apps.core.project_archive import unpack

    from .checkers import _read_asset

    asset = (
        review.report_version.workspace_snapshot.asset
        if review.report_version_id else review.system_artifact.asset
    )
    limit = min(settings.WORKSPACE_SNAPSHOT_MAX_BYTES, 20 * 1024 * 1024)
    value = _read_asset(asset, limit=limit)
    return (
        {"main.py": value} if asset.media_type.startswith("text/")
        else unpack(value, max_bytes=limit, require_manifest=True)
    )


def execute_ai_score_suggestion(*, suggestion_id: str) -> AIScoreSuggestion:
    with transaction.atomic():
        try:
            suggestion = AIScoreSuggestion.objects.select_for_update().get(public_id=suggestion_id)
        except AIScoreSuggestion.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        if suggestion.status in (
            AIScoreSuggestion.Status.READY,
            AIScoreSuggestion.Status.ACCEPTED,
            AIScoreSuggestion.Status.FAILED,
        ):
            return suggestion
        if suggestion.status == AIScoreSuggestion.Status.QUEUED:
            suggestion = compare_and_swap(
                AIScoreSuggestion,
                pk=suggestion.pk,
                expected_version=suggestion.row_version,
                changes={"status": AIScoreSuggestion.Status.RUNNING},
            )  # type: ignore[assignment]

    try:
        from apps.agents.rubric_agent import (
            RubricAgentConfigurationError,
            assess_submission,
        )

        review = suggestion.review
        from apps.core.redaction import redact

        files = submitted_project_files(review)
        submission = (
            review.report_version.body_markdown[:100_000] if review.report_version_id else ""
        )
        for name, content in sorted(files.items()):
            if len(submission) >= 100_000:
                break
            submission += (f"\n\nFILE: {name}\n" + content.decode("utf-8"))[
                :100_000 - len(submission)
            ]
        submission = redact(submission)[:100_000]
        criteria = list(
            RubricCriterion.objects.filter(
                rubric_version=review.rubric_version, is_active=True
            ).order_by("position")
        )
        if not criteria:
            raise ReviewValidationError(detail={"rubric": "criteria_required"})
        rubric = [
            {
                "criterion_id": item.public_id,
                "title": item.title,
                "description": item.description,
                "guidance": item.guidance,
                "max_score": str(item.max_score),
            }
            for item in criteria
        ]
        assessment = assess_submission(report=submission, rubric=rubric)
        by_id = {item.public_id: item for item in criteria}
        values: dict[str, dict[str, str]] = {}
        for item in assessment.criteria:
            criterion = by_id.get(item.criterion_id)
            if criterion is None or item.criterion_id in values:
                raise ReviewValidationError(detail={"ai_criteria": "invalid_criterion_ids"})
            score = item.score.quantize(Decimal("0.01"))
            if score < 0 or score > criterion.max_score:
                raise ReviewValidationError(detail={"ai_score": "outside_criterion_range"})
            values[item.criterion_id] = {
                "criterion_id": item.criterion_id,
                "score": str(score),
                "rationale": item.rationale.strip()[:2000],
                "evidence": item.evidence.strip()[:2000],
            }
        if set(values) != set(by_id):
            raise ReviewValidationError(detail={"ai_criteria": "criteria_incomplete"})
        total = sum((Decimal(item["score"]) for item in values.values()), Decimal("0"))
        changes = {
            "status": AIScoreSuggestion.Status.READY,
            "criteria": [values[item.public_id] for item in criteria],
            "total_score": total,
            "model_name": settings.RUBRIC_AI_MODEL_NAME,
            "error_code": "",
        }
    except Exception as exc:
        from apps.agents.rubric_agent import RubricAgentConfigurationError

        changes = {
            "status": AIScoreSuggestion.Status.FAILED,
            "error_code": (
                "AI_PROVIDER_NOT_CONFIGURED"
                if isinstance(exc, RubricAgentConfigurationError)
                else "AI_SCORE_FAILED"
            ),
        }

    with transaction.atomic():
        suggestion.refresh_from_db()
        suggestion = compare_and_swap(
            AIScoreSuggestion,
            pk=suggestion.pk,
            expected_version=suggestion.row_version,
            changes=changes,
        )  # type: ignore[assignment]
        _refresh_ai_score_batch_status(suggestion.batch_id)
        append_audit(
            actor_ref="SYSTEM", actor_portal="WORKER", actor_context={},
            action="review.ai_score.generate", target_type="ai_score_suggestion",
            target_ref=suggestion.public_id, course_ref=suggestion.review.course.public_id,
            after={
                "status": suggestion.status,
                "review_id": suggestion.review.public_id,
                "review_row_version": suggestion.review_row_version,
                "rubric_version_id": suggestion.review.rubric_version.public_id,
                "submission_id": (
                    suggestion.review.report_version.public_id
                    if suggestion.review.report_version_id
                    else suggestion.review.system_artifact.public_id
                ),
            },
            result="SUCCEEDED" if suggestion.status == AIScoreSuggestion.Status.READY else "FAILED",
            error_code=suggestion.error_code, trace_id=suggestion.public_id,
        )
    return suggestion


@transaction.atomic
def accept_ai_score_suggestion(
    *, course_id: str, review_id: str, suggestion_id: str, actor: User,
    expected_review_version: int, context: ActorContext,
) -> AIScoreSuggestion:
    course = _course(course_id, actor)
    try:
        suggestion = AIScoreSuggestion.objects.select_for_update().get(
            public_id=suggestion_id, review__public_id=review_id, batch__course=course
        )
    except AIScoreSuggestion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if suggestion.status != AIScoreSuggestion.Status.READY:
        raise ReviewStateConflict(detail={"suggestion": suggestion.status})
    if suggestion.review_row_version != expected_review_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": suggestion.review_row_version,
                "actual_row_version": expected_review_version,
            }
        )
    score_review_criteria(
        course_id=course.public_id,
        review_id=suggestion.review.public_id,
        actor=actor,
        expected_version=expected_review_version,
        scores=[
            {
                "criterion_id": item["criterion_id"],
                "score": item["score"],
                "note": item["rationale"],
            }
            for item in suggestion.criteria
        ],
        context=context,
    )
    suggestion = compare_and_swap(
        AIScoreSuggestion,
        pk=suggestion.pk,
        expected_version=suggestion.row_version,
        changes={
            "status": AIScoreSuggestion.Status.ACCEPTED,
            "accepted_by": actor,
            "accepted_at": timezone.now(),
        },
    )  # type: ignore[assignment]
    _audit(
        context,
        action="review.ai_score.accept",
        target_type="ai_score_suggestion",
        target_ref=suggestion.public_id,
        course_ref=course.public_id,
        after={"review_id": suggestion.review.public_id},
    )
    _refresh_ai_score_batch_status(suggestion.batch_id)
    return suggestion


@transaction.atomic
def accept_ai_score_batch(
    *, course_id: str, batch_id: str, actor: User, expected_batch_version: int,
    context: ActorContext,
) -> AIScoreBatch:
    course = _course(course_id, actor)
    try:
        batch = AIScoreBatch.objects.get(public_id=batch_id, course=course)
    except AIScoreBatch.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    suggestions = list(batch.suggestions.select_for_update().order_by("id"))
    batch = AIScoreBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.row_version != expected_batch_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_batch_version,
                "actual_row_version": batch.row_version,
            }
        )
    if any(
        item.status in (AIScoreSuggestion.Status.QUEUED, AIScoreSuggestion.Status.RUNNING)
        for item in suggestions
    ):
        raise ReviewStateConflict(detail={"batch": "scoring_in_progress"})
    ready = [item for item in suggestions if item.status == AIScoreSuggestion.Status.READY]
    if not ready:
        raise ReviewStateConflict(detail={"batch": "no_scores_ready"})
    for suggestion in ready:
        accept_ai_score_suggestion(
            course_id=course.public_id,
            review_id=suggestion.review.public_id,
            suggestion_id=suggestion.public_id,
            actor=actor,
            expected_review_version=suggestion.review_row_version,
            context=context,
        )
    batch = _refresh_ai_score_batch_status(batch.pk)
    _audit(
        context,
        action="review.ai_score_batch.accept",
        target_type="ai_score_batch",
        target_ref=batch.public_id,
        course_ref=course.public_id,
        after={"accepted_count": len(ready)},
    )
    return batch


def _validated_annotation_target(
    *, review: Review, target_type: str, target_ref: str, anchor: dict[str, Any]
) -> tuple[ReportVersion | None, Any, str, dict[str, Any]]:
    if len(json.dumps(anchor, ensure_ascii=False)) > 2048:
        raise ReviewValidationError(detail={"anchor": "too_large"})
    report_version: ReportVersion | None = None
    asset = None
    digest = ""
    if target_type == ReviewAnnotation.TargetType.REPORT_TEXT:
        report_version = review.report_version
        if report_version is None or report_version.public_id != target_ref:
            raise ReviewValidationError(detail={"target_ref": "report_mismatch"})
        if anchor.get("kind") != "TEXT_RANGE":
            raise ReviewValidationError(detail={"anchor": "text_range_required"})
        start = anchor.get("start")
        end = anchor.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end:
            raise ReviewValidationError(detail={"anchor": "invalid_range"})
        if end > len(report_version.body_markdown):
            raise ReviewValidationError(detail={"anchor": "range_outside_report"})
        digest = report_version.body_digest
    elif target_type == ReviewAnnotation.TargetType.ATTACHMENT:
        if review.report_version is None or anchor.get("kind") != "FILE_LOCATION":
            raise ReviewValidationError(detail={"anchor": "file_location_required"})
        try:
            link = ReportVersionAttachment.objects.select_related("attachment__asset").get(
                version=review.report_version, attachment__asset__public_id=target_ref
            )
        except ReportVersionAttachment.DoesNotExist as exc:
            raise ReviewValidationError(detail={"target_ref": "attachment_mismatch"}) from exc
        asset = link.attachment.asset
        digest = link.asset_digest
    elif target_type == ReviewAnnotation.TargetType.WORKSPACE_SNAPSHOT:
        if review.report_version is None or anchor.get("kind") != "OBJECT":
            raise ReviewValidationError(detail={"anchor": "object_required"})
        asset = review.report_version.workspace_snapshot.asset
        if asset.public_id != target_ref:
            raise ReviewValidationError(detail={"target_ref": "snapshot_mismatch"})
        digest = review.report_version.snapshot_digest
    elif target_type == ReviewAnnotation.TargetType.SYSTEM_ARTIFACT:
        if review.system_artifact is None or anchor.get("kind") != "OBJECT":
            raise ReviewValidationError(detail={"anchor": "object_required"})
        asset = review.system_artifact.asset
        if asset.public_id != target_ref:
            raise ReviewValidationError(detail={"target_ref": "artifact_mismatch"})
        digest = review.system_artifact.digest_sha256
    else:
        raise ReviewValidationError(detail={"target_type": target_type})
    return report_version, asset, digest, anchor


@transaction.atomic
def add_review_annotation(
    *,
    course_id: str,
    review_id: str,
    actor: User,
    expected_version: int,
    target_type: str,
    target_ref: str,
    anchor: dict[str, Any],
    body: str,
    context: ActorContext,
) -> tuple[ReviewAnnotation, Review]:
    course, _staff = _locked_review_course(course_id=course_id, actor=actor, context=context)
    review = _review_for_update(course=course, review_id=review_id)
    _assert_review_version(review, expected_version)
    if review.status == Review.Status.DECIDED:
        raise ReviewStateConflict(detail={"status": review.status})
    clean_body = body.strip()
    if not clean_body or len(clean_body) > 8000:
        raise ReviewValidationError(detail={"body": "required_and_bounded"})
    report_version, asset, digest, clean_anchor = _validated_annotation_target(
        review=review, target_type=target_type, target_ref=target_ref, anchor=anchor
    )
    annotation = ReviewAnnotation.objects.create(
        review=review,
        author=actor,
        target_type=target_type,
        report_version=report_version,
        asset=asset,
        object_digest=digest,
        anchor=clean_anchor,
    )
    AnnotationRevision.objects.create(
        annotation=annotation,
        revision_no=1,
        action=AnnotationRevision.Action.UPSERT,
        body=clean_body,
        actor=actor,
        trace_id=context.trace_id,
    )
    changed_review = compare_and_swap(
        Review,
        pk=review.pk,
        expected_version=expected_version,
        changes={"status": Review.Status.IN_REVIEW},
    )
    _audit(
        context,
        action="review.annotation.create",
        target_type="review_annotation",
        target_ref=annotation.public_id,
        course_ref=course.public_id,
        after={"review_id": review.public_id, "target_type": target_type},
    )
    _event(
        context,
        event_type=events.REVIEW_ANNOTATION_CHANGED,
        aggregate_type="review",
        aggregate_ref=review.public_id,
        payload={"course_id": course.public_id, "task_id": review.task.public_id},
    )
    return annotation, changed_review  # type: ignore[return-value]


@transaction.atomic
def revise_review_annotation(
    *,
    course_id: str,
    review_id: str,
    annotation_id: str,
    actor: User,
    expected_version: int,
    body: str,
    revoke: bool,
    context: ActorContext,
) -> ReviewAnnotation:
    course, _staff = _locked_review_course(course_id=course_id, actor=actor, context=context)
    review = _review_for_update(course=course, review_id=review_id)
    if review.status == Review.Status.DECIDED:
        raise ReviewStateConflict(detail={"status": review.status})
    try:
        annotation = ReviewAnnotation.objects.select_for_update().get(
            public_id=annotation_id, review=review
        )
    except ReviewAnnotation.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if annotation.author_id != actor.pk:
        raise ResourceNotFound()
    if annotation.row_version != expected_version:
        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": annotation.row_version,
            }
        )
    if annotation.status == ReviewAnnotation.Status.REVOKED:
        raise ReviewStateConflict(detail={"annotation_status": annotation.status})
    clean_body = body.strip()
    if not revoke and (not clean_body or len(clean_body) > 8000):
        raise ReviewValidationError(detail={"body": "required_and_bounded"})
    revision_no = annotation.current_revision_no + 1
    changed = compare_and_swap(
        ReviewAnnotation,
        pk=annotation.pk,
        expected_version=expected_version,
        changes={
            "current_revision_no": revision_no,
            "status": ReviewAnnotation.Status.REVOKED if revoke else annotation.status,
        },
    )
    AnnotationRevision.objects.create(
        annotation=annotation,
        revision_no=revision_no,
        action=AnnotationRevision.Action.REVOKE if revoke else AnnotationRevision.Action.UPSERT,
        body="" if revoke else clean_body,
        actor=actor,
        trace_id=context.trace_id,
    )
    _audit(
        context,
        action="review.annotation.revoke" if revoke else "review.annotation.revise",
        target_type="review_annotation",
        target_ref=annotation.public_id,
        course_ref=course.public_id,
        after={"revision_no": revision_no},
    )
    _event(
        context,
        event_type=events.REVIEW_ANNOTATION_CHANGED,
        aggregate_type="review",
        aggregate_ref=review.public_id,
        payload={"course_id": course.public_id, "task_id": review.task.public_id},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def decide_review(
    *,
    course_id: str,
    review_id: str,
    actor: User,
    expected_version: int,
    decision: str,
    requested_score: Decimal | None,
    feedback: str,
    context: ActorContext,
) -> tuple[ReviewDecision, Review, ExperimentTask]:
    course, staff = _locked_review_course(course_id=course_id, actor=actor, context=context)
    try:
        task = ExperimentTask.objects.select_for_update().get(
            reviews__public_id=review_id, course=course
        )
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    review = _review_for_update(course=course, review_id=review_id)
    _assert_review_version(review, expected_version)
    if review.status == Review.Status.DECIDED or hasattr(review, "decision"):
        raise ReviewStateConflict(detail={"status": review.status})
    if task.status != ExperimentTask.Status.UNDER_REVIEW:
        raise ReviewStateConflict(detail={"task_status": task.status})
    if decision not in ReviewDecision.Decision.values:
        raise ReviewValidationError(detail={"decision": decision})
    pending_checks = review.auto_check_runs.filter(
        status__in=(AutoCheckRun.Status.QUEUED, AutoCheckRun.Status.RUNNING)
    ).count()
    if pending_checks:
        raise AutoCheckPending(detail={"pending_runs": pending_checks})
    criteria = list(
        RubricCriterion.objects.filter(
            rubric_version=review.rubric_version, is_active=True
        ).order_by("position")
    )
    projections = {
        item.criterion_id: item
        for item in CriterionScore.objects.select_for_update().filter(review=review)
    }
    if len(projections) != len(criteria) or any(item.pk not in projections for item in criteria):
        raise ReviewValidationError(detail={"scores": "all_criteria_required"})
    total = sum((projections[item.pk].score for item in criteria), Decimal("0"))
    if requested_score is not None and requested_score != total:
        raise ReviewValidationError(
            detail={"score": "must_match_criterion_total", "calculated": str(total)}
        )
    snapshot = [
        {
            "criterion_id": item.public_id,
            "title": item.title,
            "score": str(projections[item.pk].score),
            "max_score": str(item.max_score),
            "note": projections[item.pk].note,
            "revision_no": projections[item.pk].revision_no,
        }
        for item in criteria
    ]
    decision_row = ReviewDecision.objects.create(
        review=review,
        decision=decision,
        score=total,
        feedback=feedback.strip(),
        decided_by=actor,
        decided_by_staff=staff,
        actor_portal=context.portal,
        criterion_snapshot=snapshot,
        trace_id=context.trace_id,
    )
    changed_review = compare_and_swap(
        Review,
        pk=review.pk,
        expected_version=expected_version,
        changes={"status": Review.Status.DECIDED, "assigned_to": actor},
    )
    target_status = (
        ExperimentTask.Status.APPROVED
        if decision == ReviewDecision.Decision.APPROVE
        else ExperimentTask.Status.REJECTED
    )
    changed_task = transition_task(
        task_id=task.public_id,
        to_status=target_status,
        actor=actor,
        expected_version=task.row_version,
        trigger="REVIEW_DECIDED",
        reason=feedback.strip()[:255],
        context=context,
        detail={"review_id": review.public_id, "decision": decision, "score": str(total)},
    )
    if decision == ReviewDecision.Decision.APPROVE:
        from apps.experiments.ports import request_task_terminal

        request_task_terminal(
            task_id=changed_task.public_id,
            terminal_target=ExperimentTask.TerminalTarget.COMPLETED,
            trigger="REVIEW_APPROVED",
            context=context,
            actor=actor,
        )
    if decision == ReviewDecision.Decision.REJECT:
        if review.report_version_id:
            try:
                draft = ReportDraft.objects.select_for_update().get(task=task)
            except ReportDraft.DoesNotExist as exc:
                raise ReviewStateConflict(detail={"draft": "missing"}) from exc
            compare_and_swap(
                ReportDraft,
                pk=draft.pk,
                expected_version=draft.row_version,
                changes={"status": ReportDraft.Status.DRAFT, "submitted_at": None},
            )
            reopen_status = ExperimentTask.Status.REPORT_DRAFT
        else:
            reopen_status = ExperimentTask.Status.IN_PROGRESS
        changed_task = transition_task(
            task_id=task.public_id,
            to_status=reopen_status,
            actor=actor,
            expected_version=changed_task.row_version,
            trigger="REVIEW_REVISION_REQUESTED",
            reason="review rejected; submission reopened",
            context=context,
            detail={"review_id": review.public_id},
        )
    _audit(
        context,
        action="review.decide",
        target_type="review",
        target_ref=review.public_id,
        course_ref=course.public_id,
        after={"decision": decision, "score": str(total)},
    )
    _event(
        context,
        event_type=events.REVIEW_DECIDED,
        aggregate_type="review",
        aggregate_ref=review.public_id,
        payload={
            "course_id": course.public_id,
            "task_id": task.public_id,
            "user_id": task.student.public_id,
            "decision": decision,
            "round_no": review.round_no,
        },
    )
    transaction.on_commit(lambda: REVIEW_DECISIONS_TOTAL.labels(decision=decision).inc())
    return decision_row, changed_review, changed_task  # type: ignore[return-value]


def execute_auto_check(*, run_id: str) -> AutoCheckRun:
    with transaction.atomic():
        try:
            run = (
                AutoCheckRun.objects.select_for_update()
                .select_related("review__course", "review__task__student", "rule", "input_asset")
                .get(public_id=run_id)
            )
        except AutoCheckRun.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        if run.status in AUTO_CHECK_TERMINAL_STATUSES:
            return run
        if run.status == AutoCheckRun.Status.RUNNING:
            return run
        run = compare_and_swap(
            AutoCheckRun,
            pk=run.pk,
            expected_version=run.row_version,
            changes={
                "status": AutoCheckRun.Status.RUNNING,
                "attempt_count": run.attempt_count + 1,
                "started_at": timezone.now(),
            },
        )  # type: ignore[assignment]
    try:
        result = auto_check_executor().execute(run)
        final_status = result.status
        if final_status not in AUTO_CHECK_TERMINAL_STATUSES:
            final_status = (
                AutoCheckRun.Status.PASSED if result.passed else AutoCheckRun.Status.FAILED
            )
        with transaction.atomic():
            current = AutoCheckRun.objects.select_for_update().get(pk=run.pk)
            completed = compare_and_swap(
                AutoCheckRun,
                pk=current.pk,
                expected_version=current.row_version,
                changes={
                    "status": final_status,
                    "result_summary": result.summary,
                    "evidence": result.evidence,
                    "error_code": result.error_code[:64],
                    "duration_ms": result.duration_ms,
                    "completed_at": timezone.now(),
                },
            )
    except Exception as exc:
        timed_out = isinstance(exc, TimeoutError)
        retryable = (
            not timed_out
            and bool(getattr(exc, "retryable", True))
            and run.attempt_count < int(getattr(settings, "AUTO_CHECK_MAX_ATTEMPTS", 3))
        )
        error_code = str(
            "AUTO_CHECK_TIMEOUT"
            if timed_out
            else getattr(exc, "code", "AUTO_CHECK_EXECUTION_FAILED")
        )[:64]
        with transaction.atomic():
            current = AutoCheckRun.objects.select_for_update().get(pk=run.pk)
            completed = compare_and_swap(
                AutoCheckRun,
                pk=current.pk,
                expected_version=current.row_version,
                changes={
                    "status": (
                        AutoCheckRun.Status.QUEUED
                        if retryable
                        else (
                            AutoCheckRun.Status.TIMEOUT
                            if timed_out
                            else (
                                AutoCheckRun.Status.REJECTED
                                if isinstance(exc, AutoCheckRejected)
                                else AutoCheckRun.Status.FAILED
                            )
                        )
                    ),
                    "error_code": error_code,
                    "error_detail_masked": {"exception": type(exc).__name__},
                    "completed_at": None if retryable else timezone.now(),
                },
            )
            append_failure(
                failure_type="AUTO_CHECK",
                subject_type="AUTO_CHECK_RUN",
                subject_ref=run.public_id,
                error_code=error_code,
                message="Auto check executor failed",
                detail={"exception": type(exc).__name__},
                retryable=retryable,
                trace_id=run.trace_id,
            )
        if retryable:
            AUTO_CHECK_RUNS_TOTAL.labels(result="retry").inc()
            return completed  # type: ignore[return-value]
    context = ActorContext("SYSTEM", "", run.trace_id)
    _event(
        context,
        event_type=events.AUTO_CHECK_COMPLETED,
        aggregate_type="review",
        aggregate_ref=run.review.public_id,
        payload={
            "course_id": run.review.course.public_id,
            "task_id": run.review.task.public_id,
            "user_id": run.review.task.student.public_id,
            "run_id": run.public_id,
            "status": completed.status,
        },
    )
    AUTO_CHECK_RUNS_TOTAL.labels(result=completed.status.lower()).inc()
    return completed  # type: ignore[return-value]


def _similarity_candidates(review: Review) -> list[ReportVersion]:
    if review.report_version is None:
        return []
    values = (
        ReportVersion.objects.select_related("task__student")
        .filter(task__publication=review.task.publication)
        .exclude(task=review.task)
        .order_by("task_id", "-version_no")
    )
    latest: dict[int, ReportVersion] = {}
    for item in values:
        latest.setdefault(item.task_id, item)
    return sorted(latest.values(), key=lambda item: item.public_id)


@transaction.atomic
def start_similarity_run(
    *,
    course_id: str,
    review_id: str,
    actor: User,
    expected_version: int,
    context: ActorContext,
) -> SimilarityRun:
    course, _staff = _locked_review_course(course_id=course_id, actor=actor, context=context)
    review = _review_for_update(course=course, review_id=review_id)
    _assert_review_version(review, expected_version)
    if review.report_version is None:
        raise SimilarityUnavailable(detail={"target": "markdown_report_required"})
    algorithm = str(getattr(settings, "SIMILARITY_ALGORITHM_VERSION", "char-5gram-jaccard-v1"))
    threshold = Decimal(str(getattr(settings, "SIMILARITY_THRESHOLD", "0.30")))
    retention_days = int(getattr(settings, "SIMILARITY_RETENTION_DAYS", 180))
    candidates = _similarity_candidates(review)
    snapshot = [
        {"report_version_id": item.public_id, "body_digest": item.body_digest}
        for item in candidates
    ]
    digest_payload = {
        "target": review.report_version.body_digest,
        "candidates": snapshot,
        "algorithm": algorithm,
        "threshold": str(threshold),
    }
    input_digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = SimilarityRun.objects.filter(
        review=review, algorithm_version=algorithm, input_digest=input_digest
    ).first()
    if existing is not None:
        return existing
    run = SimilarityRun.objects.create(
        course=course,
        review=review,
        target_report_version=review.report_version,
        algorithm_version=algorithm,
        candidate_scope="SAME_PUBLICATION",
        candidate_snapshot=snapshot,
        input_digest=input_digest,
        threshold=threshold,
        candidate_count=len(snapshot),
        trace_id=context.trace_id,
        retention_until=timezone.now() + timedelta(days=retention_days),
    )
    _audit(
        context,
        action="review.similarity.start",
        target_type="similarity_run",
        target_ref=run.public_id,
        course_ref=course.public_id,
        after={"review_id": review.public_id, "candidate_count": len(snapshot)},
    )

    def enqueue() -> None:
        from .tasks import run_similarity_check

        run_similarity_check.apply_async(kwargs={"run_id": run.public_id})

    transaction.on_commit(enqueue)
    return run


def _normalized_chars(value: str) -> str:
    return re.sub(r"\s+", "", value.casefold())


def _shingles(value: str, width: int = 5) -> set[str]:
    normalized = _normalized_chars(value)
    if not normalized:
        return set()
    if len(normalized) <= width:
        return {normalized}
    return {normalized[index : index + width] for index in range(len(normalized) - width + 1)}


def _similarity_evidence(target: str, candidate: str, common: set[str]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for token in sorted(common, key=lambda value: (-len(value), value))[:3]:
        target_index = _normalized_chars(target).find(token)
        candidate_index = _normalized_chars(candidate).find(token)
        evidence.append({
            "target_excerpt": _normalized_chars(target)[
                max(0, target_index - 60) : target_index + 100
            ],
            "candidate_excerpt": _normalized_chars(candidate)[
                max(0, candidate_index - 60) : candidate_index + 100
            ],
        })
    return evidence


def execute_similarity_run(*, run_id: str) -> SimilarityRun:
    with transaction.atomic():
        try:
            run = SimilarityRun.objects.select_for_update().get(public_id=run_id)
        except SimilarityRun.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        if run.status in (SimilarityRun.Status.COMPLETED, SimilarityRun.Status.FAILED):
            return run
        if run.status == SimilarityRun.Status.RUNNING:
            return run
        run = compare_and_swap(
            SimilarityRun,
            pk=run.pk,
            expected_version=run.row_version,
            changes={"status": SimilarityRun.Status.RUNNING, "started_at": timezone.now()},
        )  # type: ignore[assignment]
    try:
        candidate_ids = [str(item["report_version_id"]) for item in run.candidate_snapshot]
        candidates = {
            item.public_id: item
            for item in ReportVersion.objects.filter(public_id__in=candidate_ids).select_related(
                "task__student"
            )
        }
        target_set = _shingles(run.target_report_version.body_markdown)
        matches: list[SimilarityMatch] = []
        for candidate_id in candidate_ids:
            candidate = candidates.get(candidate_id)
            if candidate is None:
                continue
            candidate_set = _shingles(candidate.body_markdown)
            union = target_set | candidate_set
            common = target_set & candidate_set
            raw_score = Decimal(len(common)) / Decimal(len(union)) if union else Decimal("0")
            score = raw_score.quantize(Decimal("0.0001"))
            if score < run.threshold:
                continue
            matches.append(
                SimilarityMatch(
                    run=run,
                    candidate_report_version=candidate,
                    score=score,
                    evidence=_similarity_evidence(
                        run.target_report_version.body_markdown, candidate.body_markdown, common
                    ),
                    retention_until=run.retention_until,
                )
            )
        with transaction.atomic():
            current = SimilarityRun.objects.select_for_update().get(pk=run.pk)
            if not SimilarityMatch.objects.filter(run=current).exists():
                SimilarityMatch.objects.bulk_create(matches)
            completed = compare_and_swap(
                SimilarityRun,
                pk=current.pk,
                expected_version=current.row_version,
                changes={"status": SimilarityRun.Status.COMPLETED, "completed_at": timezone.now()},
            )
    except Exception as exc:
        with transaction.atomic():
            current = SimilarityRun.objects.select_for_update().get(pk=run.pk)
            completed = compare_and_swap(
                SimilarityRun,
                pk=current.pk,
                expected_version=current.row_version,
                changes={
                    "status": SimilarityRun.Status.FAILED,
                    "error_code": "SIMILARITY_EXECUTION_FAILED",
                    "error_detail_masked": {"exception": type(exc).__name__},
                    "completed_at": timezone.now(),
                },
            )
            append_failure(
                failure_type="SIMILARITY",
                subject_type="SIMILARITY_RUN",
                subject_ref=run.public_id,
                error_code="SIMILARITY_EXECUTION_FAILED",
                message="Similarity analysis failed",
                detail={"exception": type(exc).__name__},
                retryable=False,
                trace_id=run.trace_id,
            )
    context = ActorContext("SYSTEM", "", run.trace_id)
    _event(
        context,
        event_type=events.SIMILARITY_COMPLETED,
        aggregate_type="review",
        aggregate_ref=run.review.public_id,
        payload={
            "course_id": run.course.public_id,
            "task_id": run.review.task.public_id,
            "user_id": run.review.task.student.public_id,
            "run_id": run.public_id,
            "status": completed.status,
        },
    )
    SIMILARITY_RUNS_TOTAL.labels(result=completed.status.lower()).inc()
    return completed  # type: ignore[return-value]


@transaction.atomic
def purge_expired_similarity_evidence(*, now: Any | None = None) -> int:
    cutoff = now or timezone.now()
    values = list(
        SimilarityMatch.objects.select_for_update().filter(
            retention_until__lte=cutoff, evidence_purged_at__isnull=True
        )
    )
    for item in values:
        compare_and_swap(
            SimilarityMatch,
            pk=item.pk,
            expected_version=item.row_version,
            changes={"evidence": [], "evidence_purged_at": cutoff},
        )
    return len(values)


def review_monitor_summary() -> dict[str, Any]:
    status_counts = {
        item["status"]: item["total"]
        for item in Review.objects.values("status").annotate(total=Count("id"))
    }
    auto_failures = AutoCheckRun.objects.filter(status=AutoCheckRun.Status.FAILED).count()
    similarity_counts = {
        item["status"]: item["total"]
        for item in SimilarityRun.objects.values("status").annotate(total=Count("id"))
    }
    latest_trace = (
        SimilarityRun.objects.exclude(trace_id="")
        .order_by("-created_at")
        .values_list("trace_id", flat=True)
        .first()
        or AutoCheckRun.objects.exclude(trace_id="")
        .order_by("-created_at")
        .values_list("trace_id", flat=True)
        .first()
        or ""
    )
    return {
        "review_counts": status_counts,
        "auto_check_failures": auto_failures,
        "similarity_counts": similarity_counts,
        "latest_trace_id": latest_trace,
    }
