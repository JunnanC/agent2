"""Container-independent assessment drafts and immutable section submissions."""

import hashlib
import json
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.audit import append_audit
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, StateConflict
from apps.core.outbox import append_outbox_event
from apps.courses.models import Enrollment
from apps.labtemplates.questions import (
    CHOICE_TYPES,
    QUESTION_TYPES,
    project_files,
    public_question,
)

from .models import (
    AnswerDraft,
    AssessmentRun,
    AssessmentSection,
    CodeDraft,
    ExperimentTask,
    PublicationTask,
    QuestionGrade,
    QuestionSubmission,
    ReportGrade,
    SectionSubmission,
    TaskPublication,
)
from .selectors import task_for_user


def _task(actor: User, task_id: str, *, write: bool = False) -> ExperimentTask:
    task = task_for_user(actor=actor, task_id=task_id)
    if task.enrollment.status != Enrollment.Status.ACTIVE:
        raise ResourceNotFound()
    if task.course_id != task.publication.course_id or task.course_id != task.enrollment.course_id:
        raise ResourceNotFound()
    if timezone.now() < task.publication.window_start:
        raise StateConflict(detail={"window": "not_started"})
    if write:
        task = ExperimentTask.objects.select_for_update().get(pk=task.pk)
        task.publication = TaskPublication.objects.select_for_update().get(pk=task.publication_id)
        if task.publication.status != TaskPublication.Status.PUBLISHED:
            raise StateConflict(detail={"publication": "not_open"})
        if task.status in {
            "CANCELLED", "EXPIRED", "FAILED", "ARCHIVING", "DESTROYING", "COMPLETED",
        }:
            raise StateConflict(detail={"task": "not_open"})
        if timezone.now() < task.publication.window_start:
            raise StateConflict(detail={"window": "not_started"})
    return task


def _question(task: ExperimentTask, question_id: str) -> PublicationTask:
    try:
        return PublicationTask.objects.get(
            public_id=question_id, publication_chapter__publication_id=task.publication_id,
            task_type__in=QUESTION_TYPES,
        )
    except PublicationTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def _kind(question: PublicationTask) -> str:
    return "CHOICE" if question.task_type in CHOICE_TYPES else "PROGRAMMING"


def _deadline(task: ExperimentTask, kind: str) -> Any:
    deadline = task.effective_deadline or task.publication.window_end
    if kind == "CHOICE":
        return min(deadline, task.publication.window_end)
    section = AssessmentSection.objects.filter(task=task, kind=kind).first()
    if section and section.resubmit_until:
        deadline = max(deadline, section.resubmit_until)
    return deadline


def _writable(task: ExperimentTask, kind: str) -> None:
    if timezone.now() >= _deadline(task, kind):
        raise StateConflict(detail={"window": "closed"})


def sync_assessment_status(task: ExperimentTask) -> None:
    """Keep the existing task projection usable without coupling it to container lifecycle."""
    kinds = {"CHOICE" if kind in CHOICE_TYPES else "PROGRAMMING" for kind in
             PublicationTask.objects.filter(
                 publication_chapter__publication_id=task.publication_id,
                 task_type__in=QUESTION_TYPES,
             ).values_list("task_type", flat=True)}
    sections = list(AssessmentSection.objects.filter(task=task))
    submitted = sum(section.status == "SUBMITTED" for section in sections)
    all_submitted = submitted == len(kinds)
    returned = any(section.status == "RETURNED" for section in sections)
    status = "UNDER_REVIEW" if all_submitted else "REPORT_DRAFT" if returned else "IN_PROGRESS"
    if all_submitted and all(
        section_result(s, student=False)["score"] is not None for s in sections
    ):
        status = "APPROVED"
    compare_and_swap(
        ExperimentTask, pk=task.pk, expected_version=task.row_version,
        changes={"status": status, "progress": round(submitted / max(1, len(kinds)) * 100),
                 "submitted_at": timezone.now() if all_submitted else task.submitted_at},
    )


def _draft(task: ExperimentTask, question: PublicationTask, language: str = "") -> Any:
    if question.task_type in CHOICE_TYPES:
        if language:
            raise ResourceNotFound()
        return AnswerDraft.objects.get_or_create(task=task, question=question)[0]
    if language not in question.question_spec["allowed_languages"]:
        raise StateConflict(detail={"language": "not_allowed"})
    return CodeDraft.objects.get_or_create(
        task=task, question=question, language=language,
        defaults={"files": question.question_spec["starter_files"][language]},
    )[0]


def draft_data(draft: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"row_version": draft.row_version}
    if isinstance(draft, CodeDraft):
        data.update(language=draft.language, files=draft.files)
    else:
        data.update(selected_option_ids=draft.selected_option_ids)
    return data


@transaction.atomic
def read_draft(
    *, actor: User, task_id: str, question_id: str, language: str = "",
) -> dict[str, Any]:
    task = _task(actor, task_id)
    question = _question(task, question_id)
    return draft_data(_draft(task, question, language))


@transaction.atomic
def save_draft(
    *, actor: User, task_id: str, question_id: str, expected_version: int,
    data: dict[str, Any], language: str = "",
) -> dict[str, Any]:
    task = _task(actor, task_id, write=True)
    question = _question(task, question_id)
    _writable(task, _kind(question))
    draft = _draft(task, question, language)
    changes: dict[str, Any]
    if isinstance(draft, CodeDraft):
        if set(data) != {"files"}:
            raise StateConflict(detail={"draft": "files_required"})
        changes = {"files": project_files(data["files"])}
    else:
        selected = data.get("selected_option_ids")
        allowed = {option["id"] for option in question.question_spec["options"]}
        if (
            set(data) != {"selected_option_ids"} or not isinstance(selected, list)
            or any(not isinstance(x, str) for x in selected)
            or len(set(selected)) != len(selected) or not set(selected) <= allowed
            or (question.task_type == "SINGLE_CHOICE" and len(selected) > 1)
        ):
            raise StateConflict(detail={"selected_option_ids": "invalid_answer_set"})
        changes = {"selected_option_ids": sorted(selected)}
    changed = compare_and_swap(
        type(draft), pk=draft.pk, expected_version=expected_version, changes=changes,
    )
    if isinstance(draft, CodeDraft):
        selection, _ = AnswerDraft.objects.get_or_create(task=task, question=question)
        compare_and_swap(
            AnswerDraft, pk=selection.pk, expected_version=selection.row_version,
            changes={"selected_language": language},
        )
    return draft_data(changed)


def assessment_data(*, actor: User, task_id: str) -> dict[str, Any]:
    task = _task(actor, task_id)
    questions = list(PublicationTask.objects.filter(
        publication_chapter__publication_id=task.publication_id, task_type__in=QUESTION_TYPES,
    ).order_by("publication_chapter__sort_order", "sort_order", "id"))
    if not questions:
        raise ResourceNotFound()
    now = timezone.now()
    answer_visible = now >= task.publication.window_end
    section_rows = {row.kind: row for row in AssessmentSection.objects.filter(task=task)}
    kinds = sorted({_kind(question) for question in questions})
    selections = {row.question_id: row.selected_language for row in AnswerDraft.objects.filter(
        task=task, question__task_type="PROGRAMMING",
    )}
    values = []
    for question in questions:
        value = public_question(question)
        if question.task_type == "PROGRAMMING":
            value["selected_language"] = (
                selections.get(question.pk) or value["allowed_languages"][0]
            )
        elif answer_visible:
            value["correct_option_ids"] = question.marking_spec["correct_option_ids"]
            value["explanation"] = question.marking_spec.get("explanation", "")
        values.append(value)
    sections = []
    for kind in kinds:
        section = section_rows.get(kind) or AssessmentSection(
            task=task, kind=kind, status="NOT_SUBMITTED",
        )
        sections.append({
            **section_result(section, student=True), "deadline": _deadline(task, kind),
            "editable": task.publication.status == "PUBLISHED" and task.status not in {
                "COMPLETED", "CANCELLED", "EXPIRED", "FAILED", "ARCHIVING", "DESTROYING",
            } and now < _deadline(task, kind),
        })
    return {
        "task_id": task.public_id, "questions": values, "sections": sections,
        "all_submitted": all(s["status"] == "SUBMITTED" for s in sections),
        "server_time": now, "choice_answers_visible": answer_visible,
        "report_required": task.publication.report_required,
    }


@transaction.atomic
def submit_choices(
    *, actor: User, task_id: str, versions: dict[str, int], trace_id: str,
) -> SectionSubmission:
    task = _task(actor, task_id, write=True)
    _writable(task, "CHOICE")
    questions = list(PublicationTask.objects.filter(
        publication_chapter__publication_id=task.publication_id, task_type__in=CHOICE_TYPES,
    ).order_by("id"))
    if not questions or set(versions) != {question.public_id for question in questions}:
        raise StateConflict(detail={"versions": "complete_question_set_required"})
    drafts = []
    for question in questions:
        draft = _draft(task, question)
        if isinstance(versions[question.public_id], bool) or (
            not isinstance(versions[question.public_id], int)
        ):
            raise StateConflict(detail={"versions": "integer_versions_required"})
        if draft.row_version != versions[question.public_id]:
            from apps.core.errors import RowVersionConflict

            raise RowVersionConflict(detail={"question_id": question.public_id})
        drafts.append(draft)
    section, _ = AssessmentSection.objects.get_or_create(task=task, kind="CHOICE")
    last = section.current_submission
    submission = SectionSubmission.objects.create(
        section=section, version_no=last.version_no + 1 if last else 1,
        publication_digest=task.publication.publication_digest or "",
        submitted_at=timezone.now(), trace_id=trace_id,
    )
    for question, draft in zip(questions, drafts, strict=True):
        answer = QuestionSubmission.objects.create(
            submission=submission, question=question, selected_option_ids=draft.selected_option_ids,
        )
        correct = set(draft.selected_option_ids) == set(question.marking_spec["correct_option_ids"])
        QuestionGrade.objects.create(
            answer=answer, status="COMPLETED",
            score=question.max_score if correct else Decimal("0"),
        )
    compare_and_swap(
        AssessmentSection, pk=section.pk, expected_version=section.row_version,
        changes={"current_submission": submission, "status": "SUBMITTED"},
    )
    append_outbox_event(
        event_type="assessment.section_submitted", aggregate_type="experiment_task",
        aggregate_ref=task.public_id, payload={"task_id": task.public_id, "section": "CHOICE"},
        trace_id=trace_id,
    )
    sync_assessment_status(task)
    append_audit(
        actor_ref=actor.public_id, actor_portal="USER", actor_context={},
        action="assessment.choice.submit", target_type="section_submission",
        target_ref=str(submission.pk), course_ref=task.course.public_id,
        after={"version_no": submission.version_no}, trace_id=trace_id, result="SUCCEEDED",
    )
    return submission


@transaction.atomic
def submit_programming(
    *, actor: User, task_id: str, versions: dict[str, dict[str, Any]],
    report_version: int | None, trace_id: str,
) -> SectionSubmission:
    from apps.reports.models import ReportDraft, ReportVersion, ReportVersionAttachment
    from apps.workspaces.code_snapshots import create_code_snapshot

    from .models import CodeDraft

    task = _task(actor, task_id, write=True)
    _writable(task, "PROGRAMMING")
    questions = list(PublicationTask.objects.filter(
        publication_chapter__publication_id=task.publication_id, task_type="PROGRAMMING",
    ).order_by("id"))
    if not questions or set(versions) != {question.public_id for question in questions}:
        raise StateConflict(detail={"versions": "complete_question_set_required"})
    report = ReportDraft.objects.select_for_update().filter(task=task, student=actor).first()
    if task.publication.report_required and (report is None or not report.body_markdown.strip()):
        raise StateConflict(detail={"report": "required"})
    if report is not None and report.row_version != report_version:
        from apps.core.errors import RowVersionConflict

        raise RowVersionConflict(detail={"report": "version_mismatch"})
    if report is None and report_version is not None:
        raise StateConflict(detail={"report": "not_found"})
    drafts = []
    for question in questions:
        choice = versions[question.public_id]
        language = choice.get("language")
        if language not in question.question_spec["allowed_languages"]:
            raise StateConflict(detail={"language": "not_allowed"})
        draft = CodeDraft.objects.select_for_update().filter(
            task=task, question=question, language=language,
        ).first()
        if draft is None or draft.row_version != choice.get("row_version"):
            from apps.core.errors import RowVersionConflict

            raise RowVersionConflict(detail={"question_id": question.public_id})
        drafts.append(draft)
    attachments = list(report.attachments.select_related("asset")) if report else []
    from apps.core.models import ObjectAsset

    if ObjectAsset.objects.filter(
        owner_type="REPORT_ATTACHMENT", owner_ref=task.public_id, status="ACTIVE",
    ).exclude(scan_status="CLEAN").exists():
        raise StateConflict(detail={"report_attachments": "scan_not_ready"})
    if any(a.asset.scan_status != "CLEAN" or a.asset.status != "ACTIVE" for a in attachments):
        raise StateConflict(detail={"report_attachments": "scan_not_ready"})
    section, _ = AssessmentSection.objects.get_or_create(task=task, kind="PROGRAMMING")
    snapshots = [
        create_code_snapshot(task=task, question=question, draft=draft)
        for question, draft in zip(questions, drafts, strict=True)
    ]
    manifest_digest = hashlib.sha256(json.dumps([
        [question.public_id, draft.language, snapshot.digest_sha256]
        for question, draft, snapshot in zip(questions, drafts, snapshots, strict=True)
    ], separators=(",", ":")).encode()).hexdigest()
    report_snapshot = None
    if report is not None:
        previous = ReportVersion.objects.filter(task=task).order_by("-version_no").first()
        report_snapshot = ReportVersion.objects.create(
            task=task, draft=report, student=actor,
            version_no=previous.version_no + 1 if previous else 1,
            body_markdown=report.body_markdown,
            body_digest=hashlib.sha256(report.body_markdown.encode()).hexdigest(),
            workspace_snapshot=None, snapshot_digest=manifest_digest,
            submitted_by=actor, submitted_at=timezone.now(), trace_id=trace_id,
        )
        ReportVersionAttachment.objects.bulk_create([
            ReportVersionAttachment(
                version=report_snapshot, attachment=attachment,
                asset_digest=attachment.asset.digest_sha256,
            ) for attachment in attachments
        ])
    previous_submission = section.current_submission
    submission = SectionSubmission.objects.create(
        section=section,
        version_no=previous_submission.version_no + 1 if previous_submission else 1,
        report_version=report_snapshot,
        publication_digest=task.publication.publication_digest or "",
        submitted_at=timezone.now(), trace_id=trace_id,
    )
    report_points = (
        task.publication.rubric_version.total_score
        if task.publication.report_required and task.publication.rubric_version_id else Decimal("0")
    )
    ReportGrade.objects.create(submission=submission, score=0 if report_points == 0 else None)
    for question, draft, snapshot in zip(questions, drafts, snapshots, strict=True):
        answer = QuestionSubmission.objects.create(
            submission=submission, question=question, language=draft.language,
            code_snapshot=snapshot,
        )
        blank = not any(text.strip() for text in draft.files.values())
        QuestionGrade.objects.create(
            answer=answer, status="COMPLETED" if blank else "PENDING",
            score=Decimal("0") if blank else None,
        )
    compare_and_swap(
        AssessmentSection, pk=section.pk, expected_version=section.row_version,
        changes={"current_submission": submission, "status": "SUBMITTED"},
    )
    append_outbox_event(
        event_type="assessment.section_submitted", aggregate_type="experiment_task",
        aggregate_ref=task.public_id,
        payload={
            "task_id": task.public_id, "section": "PROGRAMMING", "submission_id": submission.pk,
            "student_id": task.student.public_id, "course_id": task.course.public_id,
            "title": "编程与报告卷已提交", "message": "本次提交版本已固定，正在评分。",
            "link_url": f"/experiments/{task.public_id}/assessment",
        },
        trace_id=trace_id,
    )
    sync_assessment_status(task)
    append_audit(
        actor_ref=actor.public_id, actor_portal="USER", actor_context={},
        action="assessment.programming.submit", target_type="section_submission",
        target_ref=str(submission.pk), course_ref=task.course.public_id,
        after={"version_no": submission.version_no}, trace_id=trace_id, result="SUCCEEDED",
    )
    return submission


@transaction.atomic
def report_draft(
    *, actor: User, task_id: str, expected_version: int | None = None,
    body_markdown: str | None = None,
) -> dict[str, Any]:
    from apps.reports.models import ReportDraft

    task = _task(actor, task_id, write=body_markdown is not None)
    if not PublicationTask.objects.filter(
        publication_chapter__publication_id=task.publication_id, task_type="PROGRAMMING",
    ).exists():
        raise ResourceNotFound()
    if body_markdown is not None:
        _writable(task, "PROGRAMMING")
    draft, _ = ReportDraft.objects.get_or_create(task=task, defaults={"student": actor})
    if body_markdown is not None:
        if expected_version is None or len(body_markdown.encode("utf-8")) > 1048576:
            raise StateConflict(detail={"report": "invalid"})
        draft = compare_and_swap(
            ReportDraft, pk=draft.pk, expected_version=expected_version,
            changes={"body_markdown": body_markdown},
        )
    return {
        "body_markdown": draft.body_markdown, "row_version": draft.row_version,
        "attachments": [{
            "asset_id": link.asset.public_id, "file_name": link.asset.original_name,
            "scan_status": link.asset.scan_status,
        } for link in draft.attachments.select_related("asset")],
    }


@transaction.atomic
def request_run(
    *, actor: User, task_id: str, question_id: str, language: str,
    expected_version: int, stdin: str, trace_id: str,
) -> AssessmentRun:
    from apps.workspaces.code_snapshots import create_code_snapshot

    task = _task(actor, task_id, write=True)
    _writable(task, "PROGRAMMING")
    question = _question(task, question_id)
    if question.task_type != "PROGRAMMING" or not isinstance(stdin, str):
        raise ResourceNotFound()
    if len(stdin.encode()) > 1048576:
        raise StateConflict(detail={"stdin": "too_large"})
    draft = _draft(task, question, language)
    if draft.row_version != expected_version:
        from apps.core.errors import RowVersionConflict

        raise RowVersionConflict()
    run = AssessmentRun.objects.create(
        task=task, question=question,
        snapshot=create_code_snapshot(task=task, question=question, draft=draft), stdin=stdin,
    )
    append_outbox_event(
        event_type="assessment.run_requested", aggregate_type="experiment_task",
        aggregate_ref=task.public_id,
        payload={"task_id": task.public_id, "run_id": run.pk}, trace_id=trace_id,
    )
    return run


def section_result(section: AssessmentSection, *, student: bool) -> dict[str, Any]:
    task = section.task
    submission = section.current_submission
    questions = PublicationTask.objects.filter(
        publication_chapter__publication_id=task.publication_id,
        task_type__in=CHOICE_TYPES if section.kind == "CHOICE" else ["PROGRAMMING"],
    )
    maximum = sum((q.max_score for q in questions), Decimal("0"))
    report_max = (
        task.publication.rubric_version.total_score
        if section.kind == "PROGRAMMING" and task.publication.report_required
        and task.publication.rubric_version_id else Decimal("0")
    )
    maximum += report_max
    visible = not student or timezone.now() >= (
        task.publication.window_end if section.kind == "CHOICE" else max(
            task.publication.window_end,
            task.publication.score_release_at or task.publication.window_end,
        )
    )
    result: dict[str, Any] = {
        "kind": section.kind, "status": section.status, "row_version": section.row_version,
        "max_score": str(maximum), "score": None, "questions": [],
        "grading_status": "NOT_SUBMITTED", "visible": visible,
        "submission_version": submission.version_no if submission else None,
    }
    if not submission:
        if timezone.now() >= _deadline(task, section.kind):
            result["grading_status"] = "COMPLETED"
            result["missing"] = True
            if visible:
                result["score"] = "0"
        return result
    answers = list(submission.answers.select_related("question", "grade", "code_snapshot"))
    grades = [answer.grade for answer in answers]
    report = ReportGrade.objects.filter(submission=submission).first()
    complete = bool(grades) and all(grade.status == "COMPLETED" for grade in grades)
    complete = complete and (
        section.kind == "CHOICE" or report is not None and report.score is not None
    )
    result["grading_status"] = "COMPLETED" if complete else "PENDING"
    if section.status == "RETURNED":
        result["grading_status"] = "RETURNED"
        result["feedback"] = report.feedback if report else ""
    if not visible:
        return result
    result["questions"] = [{
        "id": answer.question.public_id, "score": str(answer.grade.score)
        if answer.grade.status == "COMPLETED" else None,
        "max_score": str(answer.question.max_score), "language": answer.language,
        **({"private_result": answer.grade.private_result} if not student else {}),
    } for answer in answers]
    result["report_score"] = str(report.score) if report and report.score is not None else None
    result["report_max_score"] = str(report_max)
    result["feedback"] = report.feedback if report else ""
    if complete and section.status != "RETURNED":
        result["score"] = str(
            sum((grade.score or Decimal("0") for grade in grades), Decimal("0"))
            + (report.score or Decimal("0") if report else Decimal("0"))
        )
    return result


def assessment_results(task: ExperimentTask, *, student: bool) -> list[dict[str, Any]]:
    kinds = {"CHOICE" if kind in CHOICE_TYPES else "PROGRAMMING" for kind in
             PublicationTask.objects.filter(
                 publication_chapter__publication_id=task.publication_id,
                 task_type__in=QUESTION_TYPES,
             ).values_list("task_type", flat=True)}
    sections = {section.kind: section for section in AssessmentSection.objects.filter(task=task)}
    return [section_result(
        sections.get(kind) or AssessmentSection(task=task, kind=kind), student=student,
    ) for kind in sorted(kinds)]


def submission_history(*, actor: User, task_id: str) -> dict[str, Any]:
    task = _task(actor, task_id)
    history = []
    for submission in SectionSubmission.objects.filter(section__task=task).select_related(
        "section", "report_version",
    ).order_by("section__kind", "-version_no"):
        history.append({
            "kind": submission.section.kind, "version_no": submission.version_no,
            "submitted_at": submission.submitted_at,
            "is_current": submission.section.current_submission_id == submission.pk,
            "report": (
                submission.report_version.body_markdown if submission.report_version else None
            ),
            "answers": [{
                "question_id": answer.question.public_id,
                "selected_option_ids": answer.selected_option_ids, "language": answer.language,
                "snapshot_digest": (
                    answer.code_snapshot.digest_sha256 if answer.code_snapshot else None
                ),
            } for answer in submission.answers.select_related("question", "code_snapshot")],
        })
    return {"rows": history}


@transaction.atomic
def review_programming(
    *, actor: User, course_id: str, task_id: str, submission_version: int,
    expected_version: int, scores: dict[str, str], feedback: str,
    return_until: Any = None, retry_judge: bool = False, trace_id: str,
) -> dict[str, Any]:
    from apps.labtemplates.questions import score_value
    from apps.reviews.selectors import teaching_course

    course = teaching_course(actor=actor, course_id=course_id)
    try:
        task = ExperimentTask.objects.select_for_update().get(public_id=task_id, course=course)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    try:
        section = AssessmentSection.objects.select_for_update().get(task=task, kind="PROGRAMMING")
    except AssessmentSection.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    submission = section.current_submission
    if submission is None or submission.version_no != submission_version:
        raise StateConflict(detail={"submission": "not_current"})
    if task.status in {"ARCHIVING", "DESTROYING", "COMPLETED", "CANCELLED", "EXPIRED"}:
        raise StateConflict(detail={"task": "terminal"})
    if return_until is None and section.status == "RETURNED":
        raise StateConflict(detail={"submission": "returned_submission_cannot_be_graded"})
    if section.row_version != expected_version:
        from apps.core.errors import RowVersionConflict

        raise RowVersionConflict()
    grade = ReportGrade.objects.select_for_update().get(submission=submission)
    if retry_judge:
        for item in QuestionGrade.objects.select_for_update().filter(
            answer__submission=submission, status="RETRY",
        ):
            compare_and_swap(
                QuestionGrade, pk=item.pk, expected_version=item.row_version,
                changes={"status": "PENDING", "attempt_count": 0},
            )
        return section_result(section, student=False)
    if return_until is not None:
        if return_until <= timezone.now():
            raise StateConflict(detail={"resubmit_until": "future_required"})
        changed = compare_and_swap(
            AssessmentSection, pk=section.pk, expected_version=section.row_version,
            changes={"status": "RETURNED", "resubmit_until": return_until},
        )
        compare_and_swap(
            ReportGrade, pk=grade.pk, expected_version=grade.row_version,
            changes={"feedback": feedback, "reviewed_by": actor, "reviewed_at": timezone.now()},
        )
    else:
        criteria = list(task.publication.rubric_version.criteria.all()) if (
            task.publication.report_required and task.publication.rubric_version_id
        ) else []
        if set(scores) != {criterion.public_id for criterion in criteria}:
            raise StateConflict(detail={"scores": "complete_report_criteria_required"})
        total = Decimal("0")
        for criterion in criteria:
            score = score_value(scores[criterion.public_id], allow_zero=True)
            if score > criterion.max_score:
                raise StateConflict(detail={"scores": "exceeds_criterion"})
            total += score
        compare_and_swap(
            ReportGrade, pk=grade.pk, expected_version=grade.row_version,
            changes={
                "score": total, "criterion_scores": scores, "feedback": feedback,
                "reviewed_by": actor, "reviewed_at": timezone.now(),
            },
        )
        changed = compare_and_swap(
            AssessmentSection, pk=section.pk, expected_version=section.row_version, changes={},
        )
    append_outbox_event(
        event_type="assessment.review_changed", aggregate_type="experiment_task",
        aggregate_ref=task.public_id,
        payload={
            "task_id": task.public_id, "submission_id": submission.pk,
            "student_id": task.student.public_id, "course_id": task.course.public_id,
            "title": "编程卷已退回" if return_until else "实验报告审核已更新",
            "message": "请进入实验查看提交状态，成绩按发布规则开放。",
            "link_url": f"/experiments/{task.public_id}/assessment",
        }, trace_id=trace_id,
    )
    sync_assessment_status(task)
    append_audit(
        actor_ref=actor.public_id, actor_portal="TEACHING", actor_context={},
        action="assessment.programming.return" if return_until else "assessment.report.grade",
        target_type="section_submission", target_ref=str(submission.pk),
        course_ref=task.course.public_id,
        after={"submission_version": submission_version, "returned": return_until is not None},
        trace_id=trace_id, result="SUCCEEDED",
    )
    return section_result(changed, student=False)
