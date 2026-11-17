export function formatDateTime(value?: string | null): string {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "未设置";
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

export const ENROLLMENT_STATUS_LABEL: Record<string, string> = {
  PENDING: "待审核",
  ACTIVE: "已通过",
  APPROVED: "已通过",
  REJECTED: "已拒绝",
  WITHDRAWN: "已撤回",
  DROPPED: "已退出",
  REMOVED: "已移出",
};

export const PUBLICATION_STATUS_LABEL: Record<string, string> = {
  DRAFT: "草稿",
  PRECHECK: "待预检",
  READY: "待发布",
  PUBLISHING: "发布中",
  PUBLISHED: "已发布",
  PUBLISH_FAILED: "发布失败",
  WITHDRAWN: "已撤回",
  CLOSED: "已关闭",
  FAILED: "发布失败",
};

export const COURSE_STATUS_LABEL: Record<string, string> = {
  DRAFT: "草稿",
  PUBLISHED: "已发布",
  CLOSED: "已关闭",
  ARCHIVED: "已归档",
  ACTIVE: "进行中",
};

export const TASK_STATUS_LABEL: Record<string, string> = {
  ASSIGNED: "待开始",
  IN_PROGRESS: "进行中",
  REPORT_DRAFT: "报告草稿",
  SUBMITTED: "已提交",
  UNDER_REVIEW: "评审中",
  APPROVED: "已通过",
  COMPLETED: "已完成",
  ARCHIVED: "已归档",
  EXPIRED: "已过期",
  CANCELLED: "已取消",
  WITHDRAWN: "已撤回",
  FAILED: "异常",
};

export const TEMPLATE_VERSION_STATUS_LABEL: Record<string, string> = {
  DRAFT: "草稿",
  PRECHECKING: "预检中",
  PRECHECK_FAILED: "预检失败",
  PRECHECK_PASSED: "预检通过",
  PUBLISHED: "已发布",
  WITHDRAWN: "已撤回",
};

export const PRECHECK_STATUS_LABEL: Record<string, string> = {
  QUEUED: "排队中",
  RUNNING: "预检中",
  RETRY: "重试中",
  PASSED: "已通过",
  FAILED: "未通过",
};

export const REVIEW_STATUS_LABEL: Record<string, string> = {
  PENDING: "待评审",
  AUTO_CHECK_PENDING: "自动检查处理中",
  SAVED: "已保存评分",
  APPROVED: "已通过",
  RETURNED: "已退回",
  DECIDED: "已完成评审",
  COMPLETED: "已完成",
};

export function apiErrorMessage(error: unknown): string {
  const fallback = "请求失败，请稍后重试。";
  if (error && typeof error === "object" && "payload" in error) {
    const payload = (error as {
      payload?: { message?: string; detail?: { hint?: unknown } | null };
    }).payload;
    const message = payload?.message ?? "";
    const hint = typeof payload?.detail?.hint === "string" ? payload.detail.hint : "";
    if (hint && !message.includes(hint)) {
      return message ? `${message}：${hint}` : hint;
    }
    return message || fallback;
  }
  return fallback;
}

export const ASSESSMENT_STATUS_LABEL: Record<string, string> = {
  NOT_SUBMITTED: "未交卷", SUBMITTED: "已交卷", RETURNED: "已退回",
};

export const GRADING_STATUS_LABEL: Record<string, string> = {
  NOT_SUBMITTED: "未交卷", PENDING: "评分中", COMPLETED: "评分完成", RETURNED: "已退回",
};

export const REPORT_REVIEW_STATUS_LABEL: Record<string, string> = {
  NOT_REQUIRED: "无需评审", NOT_SUBMITTED: "未提交", PENDING: "待评审",
  COMPLETED: "已完成评审", RETURNED: "已退回",
};
