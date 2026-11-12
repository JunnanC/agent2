from unittest.mock import patch

from django.test import TestCase

from apps.core.errors import RowVersionConflict
from apps.labtemplates.choice_import import confirm_choices, download_template, preview_choices
from apps.labtemplates.models import TemplateChapter
from apps.labtemplates.services import create_version

from .helpers import context, create_domain


class ChoiceImportConfirmationTests(TestCase):
    def test_confirmation_is_bound_to_preview_version_and_never_repeats_append(self) -> None:
        owner, course, original, _ = create_domain(suffix="choice-import")
        version = create_version(
            actor=owner, course_id=course.public_id, template_id=original.template.public_id,
            data={}, context=context(owner),
        )
        chapter = TemplateChapter.objects.create(
            template_version=version, title="Choices", sort_order=1,
        )
        content = download_template()
        preview = preview_choices(
            actor=owner, course_id=course.public_id, chapter_id=chapter.public_id, content=content,
        )
        assert not preview["errors"]
        confirm_choices(
            actor=owner, course_id=course.public_id, chapter_id=chapter.public_id,
            content=content, token=preview["token"], context=context(owner),
        )
        assert chapter.tasks.count() == 1
        with self.assertRaises(RowVersionConflict):
            confirm_choices(
                actor=owner, course_id=course.public_id, chapter_id=chapter.public_id,
                content=content, token=preview["token"], context=context(owner),
            )
        assert chapter.tasks.count() == 1

    def test_choice_precheck_never_calls_runtime(self) -> None:
        owner, course, original, _ = create_domain(suffix="choice-no-runtime")
        from apps.labtemplates.services import create_task, execute_precheck, request_precheck

        version = create_version(
            actor=owner, course_id=course.public_id, template_id=original.template.public_id,
            data={}, context=context(owner),
        )
        chapter = TemplateChapter.objects.create(
            template_version=version, title="Choices", sort_order=1,
        )
        create_task(
            actor=owner, course_id=course.public_id, chapter_id=chapter.public_id,
            expected_version=version.row_version, context=context(owner), data={
                "title": "Q", "task_type": "SINGLE_CHOICE", "max_score": "1",
                "question_spec": {"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]},
                "marking_spec": {"correct_option_ids": ["a"]},
            },
        )
        version.refresh_from_db()
        run = request_precheck(
            actor=owner, course_id=course.public_id, version_id=version.public_id,
            expected_version=version.row_version, context=context(owner),
        )
        with (
            patch("apps.provisioning.adapters.runtime_for_driver") as runtime,
            patch("apps.core.tasks.relay_outbox.apply_async"),
        ):
            assert execute_precheck(run_id=run.public_id).status == "PASSED"
            runtime.assert_not_called()
