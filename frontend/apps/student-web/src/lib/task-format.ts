import type { Task } from "@edu/api-client";

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

export function relativeTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  return formatDate(value);
}

const TASK_STATUS_LABEL: Record<string, string> = {
  ASSIGNED: "待开始",
  IN_PROGRESS: "进行中",
  REPORT_DRAFT: "报告草稿",
  SUBMITTED: "已提交",
  UNDER_REVIEW: "评审中",
  COMPLETED: "已完成",
  REJECTED: "需修改",
  FAILED: "需处理",
  WITHDRAWN: "已撤回",
};

const TASK_STATUS_TONE: Record<string, "good" | "warn" | "blue" | "bad" | "neutral"> = {
  ASSIGNED: "warn",
  IN_PROGRESS: "good",
  REPORT_DRAFT: "good",
  SUBMITTED: "blue",
  UNDER_REVIEW: "blue",
  COMPLETED: "good",
  REJECTED: "bad",
  FAILED: "bad",
  WITHDRAWN: "neutral",
};

export function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABEL[status] ?? status.replace(/_/g, " ").toLowerCase();
}

export function taskStatusTone(status: string): "good" | "warn" | "blue" | "bad" | "neutral" {
  return TASK_STATUS_TONE[status] ?? "neutral";
}

/** 是否可以参加整体实验进程（用于日历与列表过滤） */
export function isTaskActionable(task: Pick<Task, "status" | "allowed_actions" | "blockers">): boolean {
  return !["COMPLETED", "WITHDRAWN"].includes(task.status);
}

export const ACTION_LABELS: Record<string, string> = {
  start: "开始任务",
  enter: "进入工作台",
  retry: "重试任务",
  complete: "完成任务",
  extension: "申请延期",
  request_extension: "申请延期",
  submit_report: "提交报告",
  view_workbench: "查看工作台",
  cancel_provisioning: "取消准备",
  drop: "退出任务",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}
