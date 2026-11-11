#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
if [[ "${mode}" != "prepare" && "${mode}" != "restrict" && "${mode}" != "verify" ]]; then
  echo "Usage: configure-users.sh prepare|restrict|verify" >&2
  exit 2
fi

required=(MYSQL_DATABASE MYSQL_ROOT_PASSWORD MYSQL_MIGRATION_USER MYSQL_MIGRATION_PASSWORD MYSQL_APP_USER MYSQL_APP_PASSWORD)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required database bootstrap variable: ${name}" >&2
    exit 2
  fi
done

for identifier in MYSQL_DATABASE MYSQL_MIGRATION_USER MYSQL_APP_USER; do
  if [[ ! "${!identifier}" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "Unsafe MySQL identifier in ${identifier}" >&2
    exit 2
  fi
done

for password in MYSQL_MIGRATION_PASSWORD MYSQL_APP_PASSWORD; do
  if [[ ! "${!password}" =~ ^[A-Za-z0-9._~-]+$ ]]; then
    echo "${password} must use the portable secret character set [A-Za-z0-9._~-]" >&2
    exit 2
  fi
done

export MYSQL_PWD="${MYSQL_ROOT_PASSWORD}"
mysql=(mysql --protocol=tcp --host=mysql --user=root --batch --skip-column-names)

if [[ "${mode}" != "verify" ]]; then
"${mysql[@]}" <<SQL
CREATE USER IF NOT EXISTS '${MYSQL_MIGRATION_USER}'@'%' IDENTIFIED BY '${MYSQL_MIGRATION_PASSWORD}';
ALTER USER '${MYSQL_MIGRATION_USER}'@'%' IDENTIFIED BY '${MYSQL_MIGRATION_PASSWORD}';
CREATE USER IF NOT EXISTS '${MYSQL_APP_USER}'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
ALTER USER '${MYSQL_APP_USER}'@'%' IDENTIFIED BY '${MYSQL_APP_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_MIGRATION_USER}'@'%';
FLUSH PRIVILEGES;
SQL
fi

if [[ "${mode}" == "prepare" ]]; then
  exit 0
fi

if [[ "${mode}" == "restrict" ]]; then
"${mysql[@]}" <<SQL
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.core_object_asset TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.core_object_purge_log TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.core_outbox_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.core_outbox_delivery TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.core_idempotency_record TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.core_audit_log TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.core_failure_record TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.core_compensation_task TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.core_file_download_grant TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`${MYSQL_DATABASE}\`.django_session TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.accounts_user TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`${MYSQL_DATABASE}\`.accounts_pending_registration TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.accounts_identity_verification TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.accounts_teacher_qualification TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.accounts_teacher_qualification_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.accounts_platform_admin_assignment TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.accounts_platform_admin_assignment_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_course TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_course_staff TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_course_staff_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_course_staff_grant TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_course_staff_grant_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_enrollment TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_enrollment_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_chapter TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_material TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_material_version TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_announcement TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_calendar_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_course_prerequisite TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_chapter_prerequisite TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_question TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_answer TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_moderation_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_invitation TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_enrollment_import_job TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_enrollment_import_item TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_copy_job TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_copy_item TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_academic_term TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_administrative_class TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_administrative_class_membership TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_course_schedule TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.courses_timetable_import_job TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.courses_student_schedule_entry TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.governance_runtime_adapter TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.governance_image_asset TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.governance_resource_profile TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.governance_quota TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.governance_quota_reservation TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.governance_security_policy TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.governance_network_allowlist TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_template TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_template_version TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_auto_check_rule TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_template_precheck_run TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_template_chapter TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_template_task TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_experiment_image TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_image_build_job TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.labtemplates_legacy_template_migration TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_rubric TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_rubric_version TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_rubric_criterion TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_review TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_ai_score_batch TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_ai_score_suggestion TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_criterion_score TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.reviews_criterion_score_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.reviews_review_decision TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_review_annotation TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.reviews_annotation_revision TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_auto_check_run TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_similarity_run TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reviews_similarity_match TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.experiments_task_publication TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.experiments_publication_audience TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.experiments_publication_prerequisite TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.experiments_experiment_task TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.experiments_experiment_retake_link TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.experiments_task_state_transition TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.experiments_publication_chapter TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.experiments_publication_task TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.experiments_task_extension_request TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.experiments_task_extension_decision TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.provisioning_instance TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.provisioning_job TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.provisioning_stage_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.provisioning_runtime_capacity_reservation TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.workspaces_workspace_session TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.workspaces_workspace_snapshot TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.workspaces_workspace_autosave_log TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.workspaces_workspace_checkpoint TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.workspaces_operation_event TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.workspaces_execution_run TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.workspaces_workspace_storage_job TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.reports_report_draft TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.reports_report_attachment TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.reports_report_version TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.reports_report_version_attachment TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.reports_system_artifact TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.archives_archive_job TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.archives_archive_manifest TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.archives_archive_verification TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.archives_export_grant TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_agent_definition TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_session TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.agents_message TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_source TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_source_version TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_tool_call TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.agents_approval TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_tool_call_state TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_course_profile TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_eval_run TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.agents_eval_result TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_eval_suite TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_eval_case TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_ingestion_run TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_knowledge_base TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_prompt_template TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_prompt_version TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.agents_retrieval_trace TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.agents_citation TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.agents_session_feedback TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_session_feedback_triage TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_model_route TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.agents_tool_policy TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.analytics_course_daily TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.analytics_student_risk_signal TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.analytics_course_quality_snapshot TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.analytics_learning_recommendation TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.analytics_resource_cost_daily TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.notifications_notification TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.notifications_preference TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.integrations_oidc_provider TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.integrations_oidc_identity TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.integrations_api_client TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.integrations_api_client_grant TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.integrations_webhook_endpoint TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT, UPDATE ON \`${MYSQL_DATABASE}\`.integrations_webhook_delivery TO '${MYSQL_APP_USER}'@'%';
GRANT SELECT, INSERT ON \`${MYSQL_DATABASE}\`.integrations_webhook_delivery_attempt TO '${MYSQL_APP_USER}'@'%';
FLUSH PRIVILEGES;
SQL
fi

privilege_count=$("${mysql[@]}" --execute="SELECT COUNT(DISTINCT PRIVILEGE_TYPE) FROM information_schema.TABLE_PRIVILEGES WHERE TABLE_SCHEMA='${MYSQL_DATABASE}' AND TABLE_NAME='experiments_experiment_retake_link' AND GRANTEE=CONCAT(CHAR(39), '${MYSQL_APP_USER}', CHAR(39), '@', CHAR(39), '%', CHAR(39)) AND PRIVILEGE_TYPE IN ('SELECT', 'INSERT', 'UPDATE');")
if [[ "${privilege_count}" != "3" ]]; then
  echo "Runtime database grants are incomplete for experiments_experiment_retake_link" >&2
  exit 1
fi

app_mysql=(mysql --protocol=tcp --host=mysql --user="${MYSQL_APP_USER}" --database="${MYSQL_DATABASE}" --batch --skip-column-names)
MYSQL_PWD="${MYSQL_APP_PASSWORD}" "${app_mysql[@]}" --execute="SELECT 1 FROM experiments_experiment_retake_link LIMIT 0;" >/dev/null
