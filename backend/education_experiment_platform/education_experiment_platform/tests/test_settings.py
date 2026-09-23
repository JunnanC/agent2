from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

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
    def test_all_target_apps_exist_without_teams(self) -> None:
        installed = {config.label for config in apps.get_app_configs()}
        assert installed >= EXPECTED_DOMAIN_APPS
        assert "teams" not in installed

    def test_contract_revision_and_api_prefix_are_fixed(self) -> None:
        assert settings.OPENAPI_REVISION == "v2-p07"

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
        }
        assert {model._meta.db_table for model in apps.get_app_config("accounts").get_models()} == {
            "accounts_user",
            "accounts_identity_verification",
            "accounts_teacher_qualification",
            "accounts_teacher_qualification_event",
            "accounts_platform_admin_assignment",
            "accounts_platform_admin_assignment_event",
        }
        assert {model._meta.db_table for model in apps.get_app_config("courses").get_models()} == {
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
            "labtemplates_template_precheck_run",
        }
        assert {model._meta.db_table for model in apps.get_app_config("reviews").get_models()} == {
            "reviews_rubric",
            "reviews_rubric_version",
            "reviews_rubric_criterion",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("experiments").get_models()
        } == {
            "experiments_task_publication",
            "experiments_publication_audience",
            "experiments_publication_prerequisite",
            "experiments_experiment_task",
            "experiments_task_state_transition",
            "experiments_task_extension_request",
            "experiments_task_extension_decision",
        }
        assert {
            model._meta.db_table for model in apps.get_app_config("provisioning").get_models()
        } == {
            "provisioning_instance",
            "provisioning_job",
            "provisioning_stage_event",
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
        }
        for app_label in EXPECTED_DOMAIN_APPS - implemented:
            assert list(apps.get_app_config(app_label).get_models()) == []
