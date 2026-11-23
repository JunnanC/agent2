import { newIdempotencyKey, request } from "@edu/auth-client";

export type AssessmentLanguage = "python" | "c" | "cpp" | "java" | "go";

interface QuestionBase {
  id: string;
  title: string;
  description: string;
  instructions: string;
  sort_order: number;
  max_score: string;
}

export interface ChoiceQuestion extends QuestionBase {
  task_type: "SINGLE_CHOICE" | "MULTIPLE_CHOICE";
  options: Array<{ id: string; text: string }>;
  correct_option_ids?: string[];
  explanation?: string;
}

export interface ProgrammingQuestion extends QuestionBase {
  task_type: "PROGRAMMING";
  allowed_languages: AssessmentLanguage[];
  selected_language: AssessmentLanguage;
  samples: Array<{ input: string; output: string }>;
  starter_files: Partial<Record<AssessmentLanguage, Record<string, string>>>;
  limits: Partial<Record<AssessmentLanguage, { timeout_seconds: number; memory_mb: number }>>;
  submitted?: boolean;
  case_count?: number | null;
  case_results?: CaseResult[];
  explanation?: string;
}

export interface CaseResult {
  number: number;
  passed: boolean;
  input?: string;
  expected_output?: string;
  actual_output?: string;
  stderr?: string;
  status?: string;
}

export interface AssessmentPart {
  kind: "CHOICE" | "PROGRAMMING" | "REPORT";
  status: string;
  score: string | null;
  max_score: string;
  score_cap: number;
  deadline: string;
  redo_until: string | null;
  editable: boolean;
  passed_questions?: number;
  total_questions?: number;
}

export interface AssessmentFile {
  asset_id: string;
  file_name: string;
}

export interface AssessmentReport extends AssessmentPart {
  template: AssessmentFile | null;
  attachment: AssessmentFile | null;
  submitted_at: string | null;
  row_version: number | null;
  feedback: string;
  direct_assessment?: boolean;
  released_at?: string | null;
  signer?: string;
  review_status?: string;
  comments?: ReportComment[];
  ai_review?: { score?: string; feedback?: string; comments?: ReportComment[]; error?: string };
  paragraphs?: Array<{ paragraph: number; text: string; sizes_pt: string[] }>;
  paragraphs_unavailable?: boolean;
}

export interface ReportComment {
  paragraph: number;
  text: string;
}

export interface StudentWorkspace {
  status: "NOT_REQUIRED" | "PENDING" | "RUNNING" | "FAILED" | "EXPIRED";
  expires_at: string;
}

export interface Assessment {
  report_required?: boolean;
  report_template?: { asset_id: string; file_name: string } | null;
  task_id: string;
  title?: string;
  course_title?: string;
  chapter_title?: string;
  questions: Array<ChoiceQuestion | ProgrammingQuestion>;
  sections: Array<{
    kind: "CHOICE" | "PROGRAMMING";
    status: "NOT_SUBMITTED" | "SUBMITTED" | "RETURNED";
    review_status?: "NOT_REQUIRED" | "NOT_SUBMITTED" | "PENDING" | "COMPLETED" | "RETURNED";
    submission_version: number | null;
    grading_status: "NOT_SUBMITTED" | "PENDING" | "COMPLETED" | "RETURNED";
    score: string | null;
    max_score?: string;
    deadline: string;
    editable?: boolean;
    feedback?: string;
    questions?: Array<{ id: string; title?: string; score: string | null; max_score: string; language: string }>;
  }>;
  all_submitted: boolean;
  server_time: string;
  choice_answers_visible: boolean;
  workspace_available?: boolean;
  workspace_flow?: boolean;
  current_question_id?: string | null;
  parts?: AssessmentPart[];
  direct_assessment?: boolean;
  grades_published_at?: string | null;
  guidance?: string;
  report_requirements?: string;
}

export interface ChoiceDraft {
  row_version: number;
  selected_option_ids: string[];
}

export interface CodeDraft {
  row_version: number;
  language: AssessmentLanguage;
  files: Record<string, string>;
}

export interface TeacherQuestion {
  public_id: string;
  title: string;
  description: string;
  instructions: string;
  task_type: "SINGLE_CHOICE" | "MULTIPLE_CHOICE" | "PROGRAMMING";
  sort_order: number;
  max_score: string;
  question_spec: Record<string, unknown>;
  marking_spec: Record<string, unknown>;
}

export interface HiddenGroup {
  id: string;
  score: string;
  cases: Array<{ input: string; output: string }>;
}

const questionPath = (taskId: string, questionId: string) =>
  `/tasks/${encodeURIComponent(taskId)}/questions/${encodeURIComponent(questionId)}`;
const taskPath = (taskId: string) => `/tasks/${encodeURIComponent(taskId)}`;
const teachingCoursePath = (courseId: string) => `/teaching/courses/${encodeURIComponent(courseId)}`;
const teachingTaskPath = (courseId: string, taskId: string) =>
  `${teachingCoursePath(courseId)}${taskPath(taskId)}`;

function fileBody(file: File) {
  const body = new FormData();
  body.append("file", file);
  return body;
}

export const assessmentApi = {
  get: (taskId: string) =>
    request<Assessment>(`/tasks/${encodeURIComponent(taskId)}/assessment`).then((r) => r.data),
  history: (taskId: string) => request<{ rows: Array<{
    kind: string; version_no: number; submitted_at: string; is_current: boolean;
    answers: Array<{
      question_id: string; selected_option_ids: string[]; language: string;
      snapshot_digest: string | null;
    }>;
    report: string | null;
  }> }>(`/tasks/${taskId}/assessment/submissions`).then((r) => r.data.rows),
  choiceDraft: (taskId: string, questionId: string) =>
    request<ChoiceDraft>(`${questionPath(taskId, questionId)}/draft`).then((r) => r.data),
  saveChoice: (taskId: string, questionId: string, selected: string[], version: number) =>
    request<ChoiceDraft>(`${questionPath(taskId, questionId)}/draft`, {
      method: "PUT", body: { selected_option_ids: selected }, ifMatch: version,
    }).then((r) => r.data),
  codeDraft: (taskId: string, questionId: string, language: AssessmentLanguage) =>
    request<CodeDraft>(`${questionPath(taskId, questionId)}/code/${language}`).then((r) => r.data),
  saveCode: (
    taskId: string, questionId: string, language: AssessmentLanguage,
    files: Record<string, string>, version: number,
  ) => request<CodeDraft>(`${questionPath(taskId, questionId)}/code/${language}`, {
    method: "PUT", body: { files }, ifMatch: version,
  }).then((r) => r.data),
  // One command owns one key; callers must reuse it after a lost response.
  submitChoices: (taskId: string, versions: Record<string, number>, idempotencyKey: string) =>
    request<{ version_no: number; submitted_at: string }>(
      `/tasks/${encodeURIComponent(taskId)}/sections/choice/submissions`,
      { method: "POST", body: { versions }, idempotencyKey },
    ).then((r) => r.data),
  reportDraft: (taskId: string) =>
    request<{ body_markdown: string; row_version: number; attachments: Array<{
      asset_id: string; file_name: string; scan_status: string;
    }> }>(
      `/tasks/${encodeURIComponent(taskId)}/assessment/report-draft`,
    ).then((r) => r.data),
  saveReport: (taskId: string, bodyMarkdown: string, version: number) =>
    request<{ body_markdown: string; row_version: number }>(
      `/tasks/${encodeURIComponent(taskId)}/assessment/report-draft`,
      { method: "PUT", body: { body_markdown: bodyMarkdown }, ifMatch: version },
    ).then((r) => r.data),
  submitProgramming: (
    taskId: string,
    versions: Record<string, { language: AssessmentLanguage; row_version: number }>,
    reportVersion: number | null, idempotencyKey: string,
  ) => request<{ version_no: number; submitted_at: string }>(
    `/tasks/${encodeURIComponent(taskId)}/sections/programming/submissions`,
    { method: "POST", body: { versions, report_version: reportVersion }, idempotencyKey },
  ).then((r) => r.data),
  run: (
    taskId: string, questionId: string, language: AssessmentLanguage,
    rowVersion: number, stdin: string, idempotencyKey: string,
  ) => request<AssessmentRun>(`${questionPath(taskId, questionId)}/runs`, {
    method: "POST", body: { language, row_version: rowVersion, stdin }, idempotencyKey,
  }).then((r) => r.data),
  runResult: (taskId: string, runId: number) => request<AssessmentRun>(
    `/tasks/${taskId}/assessment/runs/${runId}`,
  ).then((r) => r.data),
  enterWorkspace: (taskId: string) => request<StudentWorkspace>(`${taskPath(taskId)}/workspace`, {
    method: "POST", idempotencyKey: newIdempotencyKey(),
  }).then((r) => r.data),
  workspace: (taskId: string) =>
    request<StudentWorkspace>(`${taskPath(taskId)}/workspace`).then((r) => r.data),
  selectQuestion: (taskId: string, questionId: string) =>
    request(`${taskPath(taskId)}/workspace/questions/${encodeURIComponent(questionId)}`, {
      method: "PUT",
    }).then((r) => r.data),
  attempt: (
    taskId: string, questionId: string, mode: "self-test" | "final-run",
    language: AssessmentLanguage, rowVersion: number, stdin: string, idempotencyKey: string,
  ) => request<AssessmentRun>(`${questionPath(taskId, questionId)}/${mode}`, {
    method: "POST", body: { language, row_version: rowVersion, stdin }, idempotencyKey,
  }).then((r) => r.data),
  attemptResult: (taskId: string, questionId: string, runId: number) =>
    request<AssessmentRun>(`${questionPath(taskId, questionId)}/attempts/${runId}`).then((r) => r.data),
  attachmentReport: (taskId: string) =>
    request<AssessmentReport>(`${taskPath(taskId)}/report`).then((r) => r.data),
  submitReport: (taskId: string, file: File, key = newIdempotencyKey()) => request<AssessmentReport>(`${taskPath(taskId)}/report`, {
    method: "POST", body: fileBody(file), idempotencyKey: key,
  }).then((r) => r.data),
};

export interface AssessmentRun {
  id: number;
  status: "PENDING" | "RUNNING" | "RETRY" | "COMPLETED";
  result_status: string;
  stdout: string;
  stderr: string;
  language: AssessmentLanguage;
  snapshot_digest: string;
  case_results?: CaseResult[];
  submitted?: boolean;
  duration_ms?: number | null;
  next_question_id?: string | null;
}

export interface ReportQueueItem {
  task_id: string;
  student_name: string;
  title: string;
  status: string;
  submitted_at: string;
  review_status?: string;
}

export const assessmentPartsApi = {
  uploadTemplate: (courseId: string, publicationId: string, file: File, version: string | number) =>
    request(`${teachingCoursePath(courseId)}/experiments/${encodeURIComponent(publicationId)}/report-template`, {
      method: "POST", body: fileBody(file), ifMatch: version, idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data),
  reports: (courseId: string, publicationId?: string) =>
    request<{ rows: ReportQueueItem[] }>(`${teachingCoursePath(courseId)}/experiment-reports`, {
      query: { publication_id: publicationId || undefined },
    }).then((r) => r.data.rows),
  report: (courseId: string, taskId: string, paragraphs = false) =>
    request<AssessmentReport>(`${teachingTaskPath(courseId, taskId)}/report`, {
      query: { paragraphs: paragraphs ? 1 : undefined },
    }).then((r) => r.data),
  gradeReport: (courseId: string, taskId: string, score: string, feedback: string, version: number,
    comments?: ReportComment[]) =>
    request<AssessmentReport>(`${teachingTaskPath(courseId, taskId)}/report`, {
      method: "POST", body: { score, feedback, comments }, ifMatch: version, idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data),
  parts: (courseId: string, taskId: string) =>
    request<{ parts: AssessmentPart[]; redo_available: boolean }>(
      `${teachingTaskPath(courseId, taskId)}/assessment/parts`,
    ).then((r) => r.data),
  redo: (courseId: string, taskId: string, part: AssessmentPart["kind"], redoUntil: string, reason: string) =>
    request<{ parts: AssessmentPart[] }>(`${teachingTaskPath(courseId, taskId)}/assessment/parts`, {
      method: "POST", body: { part, redo_until: redoUntil, reason }, idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data.parts),
};

export const assessmentPartLabel: Record<AssessmentPart["kind"], string> = {
  CHOICE: "选择题", PROGRAMMING: "编程题", REPORT: "实验报告",
};

export const assessmentTeachingApi = {
  reportSuggestion: (courseId: string, taskId: string, version: number, key: string) => request<{
    submission_version: number;
    criteria: Array<{ criterion_id: string; score: string; rationale: string; evidence: string }>;
  }>(`/teaching/courses/${courseId}/tasks/${taskId}/assessment/report-suggestion`, {
    method: "POST", body: { submission_version: version }, idempotencyKey: key,
  }).then((r) => r.data),
  reorderQuestions: (courseId: string, chapterId: string, ids: string[], version: string | number) =>
    request(`/teaching/courses/${courseId}/template-chapters/${chapterId}/tasks/reorder`, {
      method: "POST", body: { ids }, ifMatch: version, idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data),
  reviews: (courseId: string, publicationId?: string) => request<{ rows: Array<{
    task_id: string; student_name: string; title: string; kind: string; status: string; review_status?: string; version_no: number;
    workspace_flow?: boolean;
  }> }>(`/teaching/courses/${courseId}/assessment-reviews`, { query: { publication_id: publicationId || undefined } }).then((r) => r.data.rows),
  review: (courseId: string, taskId: string) => request<TeacherAssessmentReview>(
    `/teaching/courses/${courseId}/tasks/${taskId}/assessment`,
  ).then((r) => r.data),
  saveReview: (courseId: string, taskId: string, payload: {
    submission_version: number; scores: Record<string, string>; feedback: string; return_until?: string;
    retry_judge?: boolean;
  }, version: number) => request(
    `/teaching/courses/${courseId}/tasks/${taskId}/assessment`,
    { method: "POST", body: payload, ifMatch: version, idempotencyKey: newIdempotencyKey() },
  ).then((r) => r.data),
  saveQuestion: (
    courseId: string, chapterId: string, questionId: string | null,
    payload: Omit<TeacherQuestion, "public_id" | "sort_order">, version: string | number,
  ) => request<TeacherQuestion>(questionId
    ? `/teaching/courses/${courseId}/template-tasks/${questionId}`
    : `/teaching/courses/${courseId}/template-chapters/${chapterId}/tasks`, {
    method: questionId ? "PATCH" : "POST", body: payload, ifMatch: version,
    idempotencyKey: newIdempotencyKey(),
  }).then((r) => r.data),
  deleteQuestion: (courseId: string, questionId: string, version: string | number) => request(
    `/teaching/courses/${courseId}/template-tasks/${questionId}`,
    { method: "DELETE", ifMatch: version },
  ),
  storeTests: (courseId: string, versionId: string, groups: HiddenGroup[], version: string | number) =>
    request<{ asset_id: string; row_version: number }>(
      `/teaching/courses/${courseId}/template-versions/${versionId}/assessment-tests`, {
        method: "POST", body: {
          groups: groups.map(({ id, cases }) => ({ id, cases })),
          scores: groups.map(({ id, score }) => ({ id, score })),
        }, ifMatch: version, idempotencyKey: newIdempotencyKey(),
      },
    ).then((r) => r.data),
  tests: (courseId: string, questionId: string) => request<{
    groups: Array<Omit<HiddenGroup, "score">>;
  }>(`/teaching/courses/${courseId}/template-tasks/${questionId}/assessment-tests`).then((r) => r.data),
  previewImport: (courseId: string, chapterId: string, file: File) => {
    const form = new FormData(); form.append("file", file);
    return request<{
      rows: TeacherQuestion[]; errors: Array<{ row: number; error: unknown }>;
      token: string | null; count: number; total_score: string;
    }>(`/teaching/courses/${courseId}/template-chapters/${chapterId}/choice-import/preview`, {
      method: "POST", body: form, idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data);
  },
  confirmImport: (courseId: string, chapterId: string, file: File, token: string, key: string) => {
    const form = new FormData(); form.append("file", file); form.append("token", token);
    return request(`/teaching/courses/${courseId}/template-chapters/${chapterId}/choice-import/confirm`, {
      method: "POST", body: form, idempotencyKey: key,
    }).then((r) => r.data);
  },
};

export interface TeacherAssessmentReview {
  parts?: AssessmentPart[];
  sources: Array<{ question_id: string; language: string; files: Record<string, string> }>;
  task_id: string;
  student_name: string;
  sections: Array<Assessment["sections"][number] & {
    row_version: number; max_score: string;
    questions: Array<{ id: string; title?: string; score: string | null; max_score: string; language: string }>;
    report_score: string | null; report_max_score: string; feedback: string;
  }>;
  report: { body_markdown: string; version_no: number } | null;
  history?: Array<{ kind: string; versions: Array<{ version_no: number; submitted_at: string }> }>;
  choice_answers: Array<{
    question_id: string; title: string; task_type: string;
    options: Array<{ id: string; text: string }>;
    selected_option_ids: string[]; correct_option_ids: string[];
    score: string | null; max_score: string;
  }>;
  report_criteria: Array<{ id: string; title: string; max_score: string }>;
}

export interface LabEnvironmentInput {
  name: string;
  language: AssessmentLanguage;
  runtime_adapter_id: string;
  image_id: string;
  cpu_millicores: number;
  memory_mb: number;
}

export interface LabEnvironment extends LabEnvironmentInput {
  public_id: string;
  row_version: number;
  display_name: string;
  usage: {
    status: "PENDING" | "UNAVAILABLE" | "AVAILABLE";
    cpu_millicores?: number;
    memory_bytes?: number;
    containers?: number;
    sampled_at?: string;
  };
  experiments: Array<{ course_id: string; publication_id: string; title: string; status: string }>;
}

interface LabEnvironmentList {
  rows: LabEnvironment[];
  adapters: Array<{ public_id: string; name: string }>;
  images: Array<{ public_id: string; name: string }>;
}

export interface LabCase {
  input: string;
  output: string;
}

export interface LabQuestion {
  task_type: TeacherQuestion["task_type"];
  title: string;
  description: string;
  explanation: string;
  options?: Array<{ id: string; text: string }>;
  correct_option_ids?: string[];
  samples?: LabCase[];
  hidden_cases?: LabCase[];
  starter_code?: string;
  timeout_seconds?: number;
}

export interface LabDesignInput {
  title: string;
  guidance: string;
  report_requirements: string;
  environment_id: string;
  window_start: string;
  window_end: string;
  part_maxima: Record<AssessmentPart["kind"], string>;
  questions: LabQuestion[];
}

interface SavedLabDesign {
  public_id: string;
  row_version: number;
  title: string;
  environment_id: string | null;
  window_start: string;
  window_end: string;
  design: {
    guidance: string;
    report_requirements: string;
    part_maxima: LabDesignInput["part_maxima"];
    questions: Array<Pick<LabQuestion, "task_type" | "title" | "description"> & {
      question_spec: {
        allowed_languages?: AssessmentLanguage[];
        options?: LabQuestion["options"];
        samples?: LabCase[];
        starter_files?: Partial<Record<AssessmentLanguage, Record<string, string>>>;
        limits?: Partial<Record<AssessmentLanguage, { timeout_seconds: number }>>;
      };
      marking_spec: Pick<LabQuestion, "correct_option_ids" | "explanation" | "hidden_cases">;
    }>;
  };
}

export interface GradeRelease {
  grades_published_at: string | null;
  deadline: string;
  pending_reports: number;
  pending_runs: number;
  open_redos: number;
}

const labEnvironmentsPath = (courseId: string) => `${teachingCoursePath(courseId)}/lab-environments`;
const labDesignPath = (courseId: string) => `${teachingCoursePath(courseId)}/experiment-designs`;
const labPublicationPath = (courseId: string, publicationId: string) =>
  `${teachingCoursePath(courseId)}/experiments/${encodeURIComponent(publicationId)}`;

export const labAssessmentApi = {
  environments: (courseId: string) =>
    request<LabEnvironmentList>(labEnvironmentsPath(courseId)).then((r) => r.data),
  saveEnvironment: (courseId: string, body: LabEnvironmentInput, target?: LabEnvironment) =>
    request<{ public_id: string }>(labEnvironmentsPath(courseId) + (target ? `/${target.public_id}` : ""), {
      method: target ? "PATCH" : "POST", body, ifMatch: target?.row_version,
      idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data),
  testEnvironment: (courseId: string, environmentId: string, publicationId?: string) =>
    request<{ test_id: string }>(`${labEnvironmentsPath(courseId)}/${environmentId}/test`, {
      method: "POST", idempotencyKey: newIdempotencyKey(), query: { publication_id: publicationId },
    }).then((r) => r.data),
  testStatus: (courseId: string, environmentId: string, testId: string) =>
    request<{ status: string; reason?: string; stderr?: string }>(
      `${labEnvironmentsPath(courseId)}/${environmentId}/test`, { query: { test_id: testId } },
    ).then((r) => r.data),
  suggest: (courseId: string, purpose: string, language: AssessmentLanguage | "" = "") =>
    request<Pick<LabDesignInput, "guidance" | "questions" | "report_requirements">>(
      `${labDesignPath(courseId)}/suggest`, {
        method: "POST", body: { purpose, language }, idempotencyKey: newIdempotencyKey(),
      },
    ).then((r) => r.data),
  design: (courseId: string, id: string) =>
    request<SavedLabDesign>(`${labDesignPath(courseId)}/${id}`).then((r) => r.data),
  saveDesign: (courseId: string, body: LabDesignInput, target?: { id: string; version: number }) =>
    request<{ public_id: string; row_version: number }>(
      labDesignPath(courseId) + (target ? `/${target.id}` : ""), {
        method: target ? "PATCH" : "POST", body, ifMatch: target?.version,
        idempotencyKey: newIdempotencyKey(),
      },
    ).then((r) => r.data),
  releaseStatus: (courseId: string, publicationId: string) =>
    request<GradeRelease>(`${labPublicationPath(courseId, publicationId)}/grade-release`).then((r) => r.data),
  release: (courseId: string, publicationId: string) =>
    request<GradeRelease>(`${labPublicationPath(courseId, publicationId)}/grade-release`, {
      method: "POST", idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data),
  batchReview: (courseId: string, publicationId: string) =>
    request<{ queued: number; submitted: number }>(`${labPublicationPath(courseId, publicationId)}/word-reviews`, {
      method: "POST", idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data),
  publishedGrade: (taskId: string) =>
    request<{ score: string; max_score: string }>(`${taskPath(taskId)}/published-grade`).then((r) => r.data),
  reviewedReportUrl: (taskId: string) => `/api/v2${taskPath(taskId)}/report/reviewed`,
};
