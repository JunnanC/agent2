export function formatDateTime(value?: string | null): string {
  if (!value) return "未设置";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export const TASK_STATUS_LABEL: Record<string, string> = {
  ASSIGNED: "待开始",
  PROVISIONING: "准备环境",
  READY: "已准备",
  IN_PROGRESS: "进行中",
  REPORT_DRAFT: "报告草稿",
  SUBMITTED: "已提交",
  UNDER_REVIEW: "评审中",
  COMPLETED: "已完成",
  REJECTED: "需修改",
  FAILED: "需处理",
};

export const TASK_STATUS_TONE: Record<string, "good" | "warn" | "blue" | "bad" | "neutral"> = {
  ASSIGNED: "warn",
  PROVISIONING: "blue",
  READY: "blue",
  IN_PROGRESS: "good",
  REPORT_DRAFT: "good",
  SUBMITTED: "blue",
  UNDER_REVIEW: "blue",
  COMPLETED: "good",
  REJECTED: "bad",
  FAILED: "bad",
};

export function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABEL[status] ?? status;
}

export function taskStatusTone(status: string): "good" | "warn" | "blue" | "bad" | "neutral" {
  return TASK_STATUS_TONE[status] ?? "neutral";
}
