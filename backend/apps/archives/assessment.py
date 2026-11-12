"""Student-safe assessment archive content, independent of IDE and hidden marking assets."""

from typing import Any

from apps.core.models import ObjectAsset
from apps.experiments.assessment import section_result
from apps.experiments.models import AssessmentSection, SectionSubmission


def assessment_archive(task: Any) -> tuple[dict[str, Any], list[ObjectAsset]]:
    sections = list(AssessmentSection.objects.filter(task=task))
    submissions = []
    assets = {}
    for submission in SectionSubmission.objects.filter(section__task=task).select_related(
        "section", "report_version",
    ).order_by("section__kind", "version_no"):
        answers = []
        for answer in submission.answers.select_related("question", "code_snapshot__asset"):
            item = {
                "question_id": answer.question.public_id, "title": answer.question.title,
                "task_type": answer.question.task_type, "language": answer.language,
                "selected_option_ids": answer.selected_option_ids,
            }
            if answer.code_snapshot_id:
                asset = answer.code_snapshot.asset
                assets[asset.pk] = asset
                item["source_asset_id"] = asset.public_id
                item["source_digest"] = answer.code_snapshot.digest_sha256
            answers.append(item)
        report = submission.report_version
        if report:
            for link in report.attachments.select_related("attachment__asset"):
                assets[link.attachment.asset_id] = link.attachment.asset
        submissions.append({
            "kind": submission.section.kind, "version_no": submission.version_no,
            "submitted_at": submission.submitted_at, "answers": answers,
            "report": report.body_markdown if report else None,
        })
    return {
        "task": {"id": task.public_id, "title": task.publication.title},
        "report": {"submissions": submissions},
        "review": {"sections": [section_result(section, student=True) for section in sections]},
        "workspace": {}, "system_artifacts": [],
    }, list(assets.values())
