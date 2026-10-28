/**
 * 业务资源类型（对齐 docs/frontend/frontend-backend-integration-guide.md 第 7 章）。
 * 生成类型可用后（npm run generate:api），这里以本地宽松结构承载，最终以 schema 为准校验。
 */

export type Portal = "USER" | "TEACHING" | "PLATFORM";
export type Iso8601 = string;

export interface Me {
  public_id: string;
  email: string;
  username: string;
  display_name: string;
  account_status: string;
  row_version: string;
  portal: Portal;
  eligible_portals: string[];
  teacher_qualification?: Record<string, unknown> | null;
  platform_admin_assignment?: Record<string, unknown> | null;
  permissions: string[];
  course_scopes?: Array<Record<string, unknown>>;
}

export interface PortalContext {
  user_role: "STUDENT" | "TEACHER" | "PLATFORM_ADMIN";
  current_term: { id: string; code: string; name: string; status: string };
  courses: Array<{ id: string; code: string; title: string; status: string; staff_role?: string; enrollment_role?: string }>;
}

export interface Course {
  public_id: string;
  code: string;
  title: string;
  summary?: string | null;
  description?: string | null;
  owner_name?: string;
  status: string;
  visibility?: string;
  enrollment_mode: "OPEN" | "APPROVAL";
  capacity: number | null;
  active_enrollment_count: number;
  enrollment_start?: Iso8601 | null;
  enrollment_end?: Iso8601 | null;
  teaching_start?: Iso8601 | null;
  teaching_end?: Iso8601 | null;
  row_version: string;
}

export interface Enrollment {
  public_id: string;
  course_id: string;
  course_code?: string;
  course_title?: string;
  student_id: string;
  student_name: string;
  cycle_no?: number;
  status: "PENDING" | "ACTIVE" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "DROPPED" | "REMOVED";
  application_message?: string | null;
  applied_at?: Iso8601 | null;
  reviewed_at?: Iso8601 | null;
  decision_note?: string | null;
  row_version: string;
}

export interface Chapter {
  public_id: string;
  course_id: string;
  title: string;
  description?: string | null;
  sort_order: number;
  status: string;
  row_version: string;
}

export interface Material {
  public_id: string;
  title: string;
  type?: string;
  status?: string;
  chapter_id?: string | null;
  asset_name?: string;
  row_version?: string;
}

export interface Announcement {
  public_id: string;
  title: string;
  body?: string;
  published_at?: Iso8601 | null;
  status?: string;
}

export interface CalendarEvent {
  public_id: string;
  course_id?: string;
  course_title?: string;
  title: string;
  start_at: Iso8601;
  end_at?: Iso8601 | null;
  kind?: string;
  ref_id?: string | null;
  ref_status?: string | null;
}

export interface WeeklyStudy {
  minutes_by_day: number[];
  total_minutes: number;
  last_week_minutes: number;
  has_records: boolean;
}

export interface StudentDashboard {
  counts?: Record<string, number>;
  weekly_study?: WeeklyStudy;
  next_tasks?: Array<Record<string, unknown>>;
}

export type TaskStatus =
  | "ASSIGNED" | "PROVISIONING" | "READY" | "IN_PROGRESS" | "REPORT_DRAFT"
  | "SUBMITTED" | "UNDER_REVIEW" | "COMPLETED" | "REJECTED" | "FAILED" | "WITHDRAWN";

export interface Blocker {
  code?: string;
  reason?: string;
  detail?: string;
}

export interface Task {
  public_id: string;
  course_id: string;
  publication_id: string;
  enrollment_id?: string;
  student_id?: string;
  student_name?: string;
  title: string;
  template_name?: string;
  template_version_id?: string;
  runtime_type?: string;
  report_required?: boolean;
  status: TaskStatus;
  terminal_target?: string | null;
  progress: number;
  window_start?: Iso8601 | null;
  window_end?: Iso8601 | null;
  effective_deadline?: Iso8601 | null;
  allowed_actions: string[];
  blockers: Blocker[];
  current_failure?: { code?: string; message?: string } | null;
  provisioning?: Record<string, unknown> | null;
  row_version: string;
}

export interface WorkspaceSession {
  public_id: string;
  task_id: string;
  course_id: string;
  instance_id?: string;
  status: string;
  capabilities: Record<string, unknown>;
  workspace_urls?: Record<string, string>;
  expires_at?: Iso8601 | null;
  current_version?: number;
  latest_client_seq?: number;
  workspace_token?: string;
  row_version: string;
}

export interface Checkpoint {
  public_id: string;
  task_id: string;
  session_id?: string;
  version_no?: number;
  label?: string;
  digest_sha256?: string;
  saved_at?: Iso8601;
  row_version?: string;
}

export interface CheckpointList {
  rows: Checkpoint[];
  currentVersion?: number;
  /** 恢复检查点所需的会话 row_version（If-Match 用） */
  sessionRowVersion?: number;
}

export interface ExecutionRun {
  public_id: string;
  task_id: string;
  session_id?: string;
  snapshot_id?: string;
  status: "QUEUED" | "RUNNING" | "PASSED" | "FAILED" | "TIMEOUT" | "RESOURCE_EXCEEDED" | "REJECTED";
  error_code?: string | null;
  result_summary?: string | null;
  started_at?: Iso8601 | null;
  finished_at?: Iso8601 | null;
  duration_ms?: number | null;
  trace_id?: string;
  test_cases?: Array<{ key?: string; name: string; status: string; message?: string }>;
}

export interface ReportAttachment {
  asset_id: string;
  file_name: string;
  size_bytes?: number;
  scan_status: string;
  status?: string;
  uploaded_at?: Iso8601;
}

export interface ReportDraft {
  public_id: string;
  task_id: string;
  body_markdown?: string | null;
  snapshot_digest?: string | null;
  status: string;
  attachments: ReportAttachment[];
  row_version: string;
  updated_at?: Iso8601;
}

export interface ReviewSummary {
  public_id: string;
  task_id: string;
  publication_title?: string;
  student_name: string;
  round_no?: number;
  status: string;
  auto_check_result?: string;
  similarity_ratio?: number | null;
  created_at?: Iso8601;
  score?: number | null;
  decision?: string | null;
  row_version: string;
}

export interface ReviewDetail extends ReviewSummary {
  submission?: {
    report_id?: string;
    report_html?: string;
    /** 批注锚点(TEXT_RANGE)所需：报告 markdown 全文 */
    report_markdown?: string;
    submitted_at?: Iso8601;
    attachments?: ReportAttachment[];
  };
  rubric?: {
    criteria: Array<{ public_id: string; key?: string; title: string; description?: string; max_score: number; score?: number | null }>;
  };
  /** criterion_id 为评测标准 public_id（CriterionScoreWriteItemSerializer 契约） */
  scores?: Array<{ criterion_id: string; score: number; note?: string }>;
  annotations?: Array<{ id: string; body: string; created_at?: Iso8601; revoked?: boolean }>;
}

export interface TeachingCourseList {
  courses: Array<Course & { student_count?: number; template_count?: number; pending_enrollments?: number }>;
}

export interface Template {
  public_id: string;
  course_id: string;
  name: string;
  category?: string;
  description?: string | null;
  status: string;
  current_version_no?: number;
  current_version_id?: string | null;
  row_version: string;
}

export interface TemplateVersion {
  public_id: string;
  template_id: string;
  version_no: number;
  status: string;
  runtime_type?: string;
  runtime_adapter_id?: string | null;
  image_id?: string | null;
  image_digest?: string | null;
  resource_profile_id?: string | null;
  report_template?: string | null;
  report_policy?: Record<string, unknown>;
  review_policy?: Record<string, unknown>;
  spec_digest?: string;
  retention_days?: number;
  row_version: string;
  chapters?: TemplateChapter[];
}

export interface TemplateChapter {
  public_id: string;
  title: string;
  description?: string | null;
  learning_objectives?: string[];
  sort_order: number;
  status: string;
  tasks: TemplateTask[];
}

export interface TemplateTask {
  public_id: string;
  title: string;
  description?: string | null;
  instructions?: string[];
  task_type: string;
  sort_order: number;
  status: string;
  submission_policy?: string;
  grading_policy?: string;
}

export interface PrecheckRun {
  public_id: string;
  template_version_id: string;
  status: "SUBMITTED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  stages?: Array<{ key?: string; name: string; status: string; message?: string; error_code?: string }>;
  created_at?: Iso8601;
  finished_at?: Iso8601 | null;
  trace_id?: string;
}

export interface Publication {
  public_id: string;
  course_id: string;
  template_version_id: string;
  template_name?: string;
  version_no?: number;
  title: string;
  description?: string | null;
  status: "DRAFT" | "PRECHECK" | "READY" | "PUBLISHED" | "WITHDRAWN" | "CLOSED" | "FAILED";
  audience_mode?: string;
  window_start?: Iso8601 | null;
  window_end?: Iso8601 | null;
  assignment_deadline?: Iso8601 | null;
  audience_count?: number;
  publication_error?: { code?: string; message?: string; trace_id?: string } | null;
  allowed_actions?: string[];
  blockers?: Blocker[];
  row_version: string;
}

export interface Invitation {
  public_id: string;
  course_id: string;
  code: string;
  status: string;
  usage_limit?: number | null;
  used_count?: number;
  expires_at?: Iso8601 | null;
}

export interface ImportJob {
  job_id: string;
  status: "SUBMITTED" | "PRECHECK_FAILED" | "RUNNING" | "COMPLETED" | "FAILED";
  stages?: Array<{ name: string; status: string }>;
  stats?: Record<string, number>;
  row_version?: string;
}

export interface Rubric {
  public_id: string;
  course_id: string;
  name: string;
  description?: string | null;
  status: string;
  current_version_id?: string | null;
  row_version?: string;
}

/** 平台端契约对象 */

export interface PlatformUser {
  public_id: string;
  username: string;
  display_name: string;
  email: string;
  account_status: string;
  teacher_qualification?: { status?: string } | null;
  admin_assignment?: { role?: string } | null;
  row_version?: string;
}

export interface Verification {
  public_id: string;
  target_user_name?: string;
  kind: string;
  status: string;
  submitted_at?: Iso8601;
  reviewer_note?: string | null;
  payload_summary?: Record<string, unknown>;
}

export interface PlatformImage {
  public_id: string;
  display_tag: string;
  registry?: string;
  repository?: string;
  digest?: string;
  scan_status: string;
  approval_status: string;
  risk_level?: string;
  scanned_at?: Iso8601 | null;
  approved_at?: Iso8601 | null;
  row_version: string;
}

export interface ImageCreateInput {
  registry: string;
  repository: string;
  display_tag?: string;
  digest?: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  reason: string;
}

export interface ImageScanReportInput {
  scan_status: "CLEAN" | "INFECTED" | "FAILED";
  scan_report_ref?: string;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  reason: string;
}

export interface ResourceProfile {
  public_id: string;
  code: string;
  name: string;
  runtime_type: string;
  status: string;
  cpu_millicores: number;
  memory_mb: number;
  disk_gb: number;
  network_mode: string;
  cpu_limit_millicores?: number;
  memory_limit_mb?: number;
  row_version: string;
}

export interface RuntimeAdapter {
  public_id: string;
  code: string;
  name: string;
  runtime_type: string;
  driver: string;
  status: string;
  health_status: string;
  node_count?: number;
  capacity_cpu_millicores?: number;
  available_cpu_millicores?: number;
  capacity_memory_mb?: number;
  available_memory_mb?: number;
  last_health_at?: Iso8601 | null;
  row_version: string;
}

export interface Quota {
  public_id: string;
  scope?: string;
  metric: string;
  limit_value: number;
  used_value?: number;
  status?: string;
  row_version?: string;
}

export interface Compensation {
  public_id: string;
  task_type: string;
  subject_type: string;
  subject_ref: string;
  status: string;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at?: string | null;
  error_code?: string | null;
  trace_id?: string;
  row_version: string;
}

export interface Instance {
  public_id: string;
  task_id?: string | null;
  template_name?: string;
  student_name?: string;
  resource_profile_name?: string;
  status: string;
  health_status?: string;
  started_at?: Iso8601 | null;
  orphaned?: boolean;
  last_activity_at?: Iso8601 | null;
}

export interface Anomaly {
  public_id: string;
  kind: "task" | "report-scan" | "precheck" | "instance";
  target_ref: string;
  level: "INFO" | "HIGH" | "MEDIUM" | "LOW";
  status: string;
  code?: string;
  message: string;
  trace_id?: string;
  occurred_at?: Iso8601;
  assignee?: string | null;
  payload?: Record<string, unknown>;
}

export interface OperationLog {
  id: string;
  occurred_at: Iso8601;
  actor_name?: string;
  actor?: string;
  action: string;
  target: string;
  result: string;
  trace_id?: string;
  detail?: Record<string, unknown>;
}

export interface OperationsOverview {
  counts?: Record<string, number>;
  health?: Array<{ name: string; status: string; detail?: string }>;
  logs_head?: OperationLog[];
}

export interface ModelRoute {
  public_id: string;
  name?: string;
  scope?: string;
  model: string;
  status?: string;
  row_version?: string;
}

export interface ToolPolicy {
  public_id: string;
  name: string;
  scope?: string;
  tools: Array<{ key: string; mode: "ALLOW" | "DENY" | "ASK" }>;
  row_version?: string;
}

export interface UsageCost {
  scope?: string;
  course?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost_minor?: number;
  currency_code?: string;
  window?: string;
}

export interface NotificationItem {
  id: string;
  kind?: string;
  title: string;
  body?: string;
  read: boolean;
  created_at?: Iso8601;
  links?: Array<{ label?: string; task_id?: string; course_id?: string; url?: string }>;
}

/** 任务操作常量 */
export const TASK_ACTION = {
  START: "start",
  ENTER: "enter",
  RETRY: "retry",
  COMPLETE: "complete",
  EXTENSION: "extension",
  SUBMIT_REPORT: "submit_report",
  VIEW_WORKBENCH: "view_workbench",
} as const;

export const PUBLICATION_ACTION = {
  PUBLISH: "publish",
  WITHDRAW: "withdraw",
  CLOSE: "close",
  PRECHECK: "precheck",
} as const;
