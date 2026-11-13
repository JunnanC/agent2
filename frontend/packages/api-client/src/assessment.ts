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
}

export interface Assessment {
  task_id: string;
  questions: Array<ChoiceQuestion | ProgrammingQuestion>;
  sections: Array<{
    kind: "CHOICE" | "PROGRAMMING";
    status: "NOT_SUBMITTED" | "SUBMITTED" | "RETURNED";
    submission_version: number | null;
    grading_status: "NOT_SUBMITTED" | "PENDING" | "COMPLETED";
    score: string | null;
    max_score?: string;
    deadline: string;
    editable?: boolean;
    feedback?: string;
    questions?: Array<{ id: string; score: string | null; max_score: string; language: string }>;
  }>;
  all_submitted: boolean;
  server_time: string;
  choice_answers_visible: boolean;
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
};

export interface AssessmentRun {
  id: number;
  status: "PENDING" | "RUNNING" | "RETRY" | "COMPLETED";
  result_status: string;
  stdout: string;
  stderr: string;
  language: AssessmentLanguage;
  snapshot_digest: string;
}

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
    task_id: string; student_name: string; title: string; kind: string; status: string; version_no: number;
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
  sources: Array<{ question_id: string; language: string; files: Record<string, string> }>;
  task_id: string;
  student_name: string;
  sections: Array<Assessment["sections"][number] & {
    row_version: number; max_score: string;
    questions: Array<{ id: string; score: string | null; max_score: string; language: string }>;
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
