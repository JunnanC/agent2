import os
import subprocess
import sys
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

ROOT = (
    Path(os.environ["PROJECT_ROOT"])
    if os.environ.get("PROJECT_ROOT")
    else Path(__file__).resolve().parents[3]
)

EXPECTED_DOMAIN_APPS = {
    "core",
    "accounts",
    "courses",
    "governance",
    "labtemplates",
    "experiments",
    "provisioning",
    "workspaces",
    "reports",
    "reviews",
    "archives",
    "agents",
    "notifications",
    "analytics",
    "integrations",
}


class SettingsTests(SimpleTestCase):
    def test_functional_setting_names_preserve_legacy_env_fallbacks(self) -> None:
        aliases = {
            "AUTO_CHECK_MAX_ATTEMPTS": "P10_AUTO_CHECK_MAX_ATTEMPTS",
            "PUBLICATION_SYNC_LIMIT": "P06_PUBLICATION_SYNC_LIMIT",
            "PUBLICATION_CHUNK_SIZE": "P06_PUBLICATION_CHUNK_SIZE",
        }
        environment = os.environ.copy()
        environment["DJANGO_SETTINGS_MODULE"] = "education_experiment_platform.settings.test"
        for current, legacy in aliases.items():
            environment.pop(current, None)
            environment[legacy] = "7"
        probe = (
            "import education_experiment_platform.settings.base as config; "
            f"print([getattr(config, key) for key in {list(aliases)!r}])"
        )
        for use_current_name, expected in ((False, "[7, 7, 7]"), (True, "[11, 11, 11]")):
            if use_current_name:
                environment.update(dict.fromkeys(aliases, "11"))
            result = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=ROOT / "backend",
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            assert result.stdout.strip() == expected

    def test_unit_test_settings_use_the_local_protocol_stub(self) -> None:
        assert settings.LOCAL_RUNTIME_MODE == "STUB"

    def test_production_rejects_fake_runtime_without_adapter_configuration(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "education_experiment_platform.settings.prod",
                "DJANGO_SECRET_KEY": "test-secret",
                "IDENTITY_HMAC_KEY": "test-identity",
                "WORKSPACE_UPSTREAM_HMAC_KEY": "test-upstream",
                "DJANGO_ALLOWED_HOSTS": "localhost",
                "DJANGO_TRUSTED_ORIGINS": "http://localhost",
                "TRUSTED_PROXY_CIDRS": "127.0.0.1/32",
                "RUNTIME_MODE": "fake",
                "RUNTIME_ADAPTER_CODE": "runtime/fake",
                "RUNTIME_ADAPTER_CONFIGS": "{}",
            }
        )
        result = subprocess.run(
            [sys.executable, "-c", "import education_experiment_platform.settings.prod"],
            cwd=ROOT / "backend",
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "Production requires RUNTIME_MODE=swarm" in result.stderr

    def test_all_target_apps_exist_without_teams(self) -> None:
        installed = {config.label for config in apps.get_app_configs()}
        assert installed >= EXPECTED_DOMAIN_APPS
        assert "teams" not in installed

    def test_contract_revision_and_api_prefix_are_fixed(self) -> None:
        assert settings.OPENAPI_REVISION == "v2-p15"

    def test_celery_preserves_structured_application_logging(self) -> None:
        assert settings.CELERY_WORKER_HIJACK_ROOT_LOGGER is False

    def test_domain_models_are_limited_to_declared_domain_tables(self) -> None:
        assert {model._meta.db_table for model in apps.get_app_config("core").get_models()} == {
            "core_object_asset",
            "core_object_purge_log",
            "core_outbox_event",
            "core_outbox_delivery",
            "core_idempotency_record",
            "core_audit_log",
            "core_failure_record",
            "core_compensation_task",
            "core_file_download_grant",
        }
        assert {model._meta.db_table for model in apps.get_app_config("accounts").get_models()} == {
            "accounts_user",
            "accounts_pending_registration",
            "accounts_identity_verification",
            "accounts_teacher_qualification",
            "accounts_teacher_qualification_event",
            "accounts_platform_admin_assignment",
            "accounts_platform_admin_assignment_event",
        }
        assert {model._meta.db_table for model in apps.get_app_config("courses").get_models()} == {
            "courses_academic_term",
            "courses_course",
            "courses_course_staff",
            "courses_course_staff_event",
            "courses_course_staff_grant",
            "courses_course_staff_grant_event",
            "courses_enrollment",
            "courses_enrollment_event",
            "courses_chapter",
            "courses_material",
            "courses_material_version",
            "courses_announcement",
            "courses_calendar_event",
            "courses_course_prerequisite",
            "courses_chapter_prerequisite",
            "courses_question",
            "courses_answer",
            "courses_moderation_event",
            "courses_invitation",
            "courses_enrollment_import_job",
            "courses_enrollment_import_item",
            "courses_copy_job",
            "courses_copy_item",
            "courses_administrative_class",
            "courses_administrative_class_membership",
            "courses_course_schedule",
            "courses_timetable_import_job",
            "courses_student_schedule_entry",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("governance").get_models()
        } == {
            "governance_runtime_adapter",
            "governance_image_asset",
            "governance_resource_profile",
            "governance_quota",
            "governance_quota_reservation",
            "governance_security_policy",
            "governance_network_allowlist",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("labtemplates").get_models()
        } == {
            "labtemplates_template",
            "labtemplates_template_version",
            "labtemplates_auto_check_rule",
            "labtemplates_template_chapter",
            "labtemplates_template_task",
            "labtemplates_template_precheck_run",
            "labtemplates_experiment_image",
            "labtemplates_image_build_job",
            "labtemplates_legacy_template_migration",
        }
        assert {model._meta.db_table for model in apps.get_app_config("reviews").get_models()} == {
            "reviews_rubric",
            "reviews_rubric_version",
            "reviews_rubric_criterion",
            "reviews_review",
            "reviews_criterion_score",
            "reviews_criterion_score_event",
            "reviews_review_decision",
            "reviews_review_annotation",
            "reviews_annotation_revision",
            "reviews_auto_check_run",
            "reviews_similarity_run",
            "reviews_similarity_match",
            "reviews_ai_score_batch",
            "reviews_ai_score_suggestion",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("experiments").get_models()
        } == {
            "experiments_task_publication",
            "experiments_publication_chapter",
            "experiments_publication_task",
            "experiments_publication_audience",
            "experiments_publication_prerequisite",
            "experiments_experiment_task",
            "experiments_experiment_retake_link",
            "experiments_task_state_transition",
            "experiments_task_extension_request",
            "experiments_task_extension_decision",
            "experiments_answer_draft",
            "experiments_code_draft",
            "experiments_assessment_section",
            "experiments_section_submission",
            "experiments_question_submission",
            "experiments_question_grade",
            "experiments_assessment_run",
            "experiments_report_grade",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("provisioning").get_models()
        } == {
            "provisioning_instance",
            "provisioning_job",
            "provisioning_runtime_capacity_reservation",
            "provisioning_stage_event",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("workspaces").get_models()
        } == {
            "workspaces_workspace_session",
            "workspaces_workspace_snapshot",
            "workspaces_workspace_autosave_log",
            "workspaces_workspace_checkpoint",
            "workspaces_operation_event",
            "workspaces_execution_run",
            "workspaces_workspace_storage_job",
        }
        assert {model._meta.db_table for model in apps.get_app_config("reports").get_models()} == {
            "reports_report_draft",
            "reports_report_attachment",
            "reports_report_version",
            "reports_report_version_attachment",
            "reports_system_artifact",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("archives").get_models()
        } == {
            "archives_archive_job",
            "archives_archive_manifest",
            "archives_archive_verification",
            "archives_export_grant",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("agents").get_models()
        } == {
            "agents_agent_definition",
            "agents_knowledge_base",
            "agents_source",
            "agents_source_version",
            "agents_ingestion_run",
            "agents_prompt_template",
            "agents_prompt_version",
            "agents_model_route",
            "agents_tool_policy",
            "agents_course_profile",
            "agents_session",
            "agents_message",
            "agents_retrieval_trace",
            "agents_citation",
            "agents_tool_call",
            "agents_tool_call_state",
            "agents_approval",
            "agents_eval_suite",
            "agents_eval_case",
            "agents_eval_run",
            "agents_eval_result",
            "agents_session_feedback",
            "agents_session_feedback_triage",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("notifications").get_models()
        } == {"notifications_notification", "notifications_preference"}
        assert {
            model._meta.db_table for model in apps.get_app_config("analytics").get_models()
        } == {
            "analytics_course_daily",
            "analytics_student_risk_signal",
            "analytics_course_quality_snapshot",
            "analytics_learning_recommendation",
            "analytics_resource_cost_daily",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("integrations").get_models()
        } == {
            "integrations_oidc_provider",
            "integrations_oidc_identity",
            "integrations_api_client",
            "integrations_api_client_grant",
            "integrations_webhook_endpoint",
            "integrations_webhook_delivery",
            "integrations_webhook_delivery_attempt",
        }
        implemented = {
            "core",
            "accounts",
            "courses",
            "governance",
            "labtemplates",
            "reviews",
            "experiments",
            "provisioning",
            "workspaces",
            "reports",
            "archives",
            "agents",
            "notifications",
            "analytics",
            "integrations",
        }
        for app_label in EXPECTED_DOMAIN_APPS - implemented:
            assert list(apps.get_app_config(app_label).get_models()) == []
