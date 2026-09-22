from django.test import TestCase

from apps.core.errors import RowVersionConflict
from apps.governance.models import ResourceProfile

from ..errors import TemplateStateConflict, TemplateValidationError
from ..models import AutoCheckRule, TemplatePrecheckRun, TemplateVersion
from ..services import (
    clone_version,
    execute_precheck,
    publish_version,
    replace_rules,
    request_precheck,
    update_version,
)
from .helpers import add_valid_rule, context, create_template_version


class TemplateServiceTests(TestCase):
    def test_precheck_freezes_publish_and_clone_preserves_spec(self) -> None:
        owner, course, _template, version = create_template_version(suffix="freeze")
        version = add_valid_rule(owner=owner, course=course, version=version)
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner, "r"),
        )
        completed = execute_precheck(run_id=run.public_id)
        self.assertEqual(completed.status, TemplatePrecheckRun.Status.PASSED)
        self.assertEqual(
            [item["stage"] for item in completed.stage_results],
            ["SCOPE", "ASSETS", "GOVERNANCE", "RULES", "POLICY", "DIGEST"],
        )
        version = TemplateVersion.objects.get(pk=version.pk)
        self.assertEqual(version.status, TemplateVersion.Status.PRECHECK_PASSED)
        self.assertEqual(len(version.spec_digest or ""), 64)

        published = publish_version(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner),
        )
        with self.assertRaises(TemplateStateConflict):
            update_version(
                course_id=course.public_id,
                version_id=published.public_id,
                actor=owner,
                expected_version=published.row_version,
                changes={"retention_days": 60},
                context=context(owner),
            )
        clone = clone_version(
            course_id=course.public_id,
            version_id=published.public_id,
            actor=owner,
            expected_version=published.row_version,
            context=context(owner),
        )
        self.assertEqual(clone.status, TemplateVersion.Status.DRAFT)
        self.assertIsNone(clone.spec_digest)
        self.assertNotEqual(clone.public_id, published.public_id)

    def test_invalid_schema_records_exact_failed_stage(self) -> None:
        owner, course, _template, version = create_template_version(suffix="schema")
        version = replace_rules(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            rules=[
                {
                    "position": 1,
                    "checker_type": "PYTEST",
                    "input_schema": {"type": "not-a-json-schema-type"},
                    "output_schema": {"type": "object"},
                    "timeout_seconds": 10,
                    "resource_limit": {},
                    "network_policy": {"mode": "DENY_ALL"},
                    "display_policy": {},
                    "failure_semantics": {"on_failure": "FAIL_CHECK"},
                }
            ],
            context=context(owner),
        )
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner),
        )
        completed = execute_precheck(run_id=run.public_id)
        self.assertEqual(completed.status, TemplatePrecheckRun.Status.FAILED)
        self.assertEqual(completed.current_stage, "RULES")
        self.assertEqual(completed.error_code, "TEMPLATE_VALIDATION_ERROR")
        self.assertEqual(completed.stage_results[-1]["result"], "FAILED")

    def test_governance_retirement_is_rechecked_by_precheck(self) -> None:
        owner, course, _template, version = create_template_version(suffix="retired")
        version = add_valid_rule(owner=owner, course=course, version=version)
        ResourceProfile.objects.filter(pk=version.resource_profile_id).update(status="RETIRED")
        run = request_precheck(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            context=context(owner),
        )
        completed = execute_precheck(run_id=run.public_id)
        self.assertEqual(completed.status, TemplatePrecheckRun.Status.FAILED)
        self.assertEqual(completed.current_stage, "GOVERNANCE")

    def test_rule_replacement_preserves_inactive_history(self) -> None:
        owner, course, _template, version = create_template_version(suffix="history")
        version = add_valid_rule(owner=owner, course=course, version=version)
        first = AutoCheckRule.objects.get(template_version=version, is_active=True)
        version = replace_rules(
            course_id=course.public_id,
            version_id=version.public_id,
            actor=owner,
            expected_version=version.row_version,
            rules=[
                {
                    "position": 1,
                    "checker_type": "SHELL",
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "timeout_seconds": 30,
                    "resource_limit": {},
                    "network_policy": {"mode": "DENY_ALL"},
                    "display_policy": {},
                    "failure_semantics": {"on_failure": "WARN"},
                }
            ],
            context=context(owner),
        )
        self.assertEqual(AutoCheckRule.objects.filter(template_version=version).count(), 2)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(
            AutoCheckRule.objects.get(template_version=version, is_active=True).checker_type,
            "SHELL",
        )

    def test_cas_and_unavailable_resource_are_rejected(self) -> None:
        owner, course, template, version = create_template_version(suffix="guards")
        with self.assertRaises(RowVersionConflict):
            update_version(
                course_id=course.public_id,
                version_id=version.public_id,
                actor=owner,
                expected_version=999,
                changes={"retention_days": 1},
                context=context(owner),
            )
        with self.assertRaises(TemplateValidationError):
            from ..services import create_version

            create_version(
                course_id=course.public_id,
                template_id=template.public_id,
                actor=owner,
                data={
                    "runtime_type": "CONTAINER",
                    "runtime_adapter_id": "0" * 26,
                    "image_id": "0" * 26,
                    "resource_profile_id": "0" * 26,
                },
                context=context(owner),
            )
