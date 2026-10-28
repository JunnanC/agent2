import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, EmptyState, Panel, RequestStateView, StatusBadge, useToast } from "@edu/ui";
import { formatDateTime } from "@/lib/task-format";

interface NotificationRow {
  id: string;
  kind?: string | null;
  title: string;
  body?: string | null;
  read: boolean;
  created_at?: string | null;
  links?: Array<{ label?: string; task_id?: string; course_id?: string; url?: string }> | null;
}

const KIND_ICON: Record<string, string> = {
  deadline: "calendar-clock",
  review: "message",
  system: "bell",
  risk: "alert-triangle",
  recommendation: "lightbulb",
};

export function Notifications() {
  const toast = useToast();
  const [readFilter, setReadFilter] = useState<"all" | "unread">("all");

  const notifications = useQuery({
    queryKey: keys.notifications({}),
    queryFn: () => meApi.notifications({ page_size: 50 }),
  });

  const markRead = useMutation({
    mutationFn: (id: string) => meApi.markNotificationRead(id),
    onSuccess: () => void notifications.refetch(),
    onError: () => toast.notify("标记失败，请重试", "error"),
  });

  const rows = (notifications.data?.rows ?? []) as NotificationRow[];
  const unread = rows.filter((row) => !row.read).length;
  const visible = readFilter === "all" ? rows : rows.filter((row) => !row.read);

  return (
    <>
      <div className="page-actions align-end">
        <span className={`status ${unread ? "warn" : "good"}`}>{unread ? `${unread} 条未读` : "全部已读"}</span>
        <button type="button" className={`btn sm${readFilter === "all" ? " primary" : ""}`} onClick={() => setReadFilter("all")}>全部</button>
        <button type="button" className={`btn sm${readFilter === "unread" ? " primary" : ""}`} onClick={() => setReadFilter("unread")}>未读</button>
      </div>
      <Panel>
        <RequestStateView
          loading={notifications.isLoading}
          error={notifications.error}
          onRetry={() => void notifications.refetch()}
          empty={!visible.length}
          emptyState={<EmptyState title="暂无通知" hint="任务截止、报告评审与平台消息会集中显示在这里。" />}
        >
          <div className="notification-list">
            {visible.map((row) => (
              <article className={`notification-card${row.read ? " read" : ""}`} key={row.id}>
                <div className="notification-icon" aria-hidden="true">
                  {KIND_ICON[row.kind ?? ""] ?? "bell"}
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="notification-card-head">
                    <strong>{row.title}</strong>
                    <small>{formatDateTime(row.created_at)}</small>
                  </div>
                  <p style={{ margin: "4px 0 0" }}>{row.body}</p>
                  <div className="notification-actions">
                    {(row.links ?? []).filter((link) => link.task_id || link.course_id || link.url).slice(0, 1).map((link, index) => (
                      <a key={index} className="btn sm" href={link.url ?? (link.task_id ? `/experiments/${link.task_id}` : `/courses/${link.course_id}`)}>
                        {link.label ?? "查看详情"}
                      </a>
                    ))}
                    {!row.read
                      ? <Button size="sm" disabled={markRead.isPending} onClick={() => markRead.mutate(row.id)}>
                        {markRead.isPending && markRead.variables === row.id ? "标记中…" : "标记已读"}
                      </Button> : null}
                  </div>
                </div>
                {!row.read ? <StatusBadge tone="warn">未读</StatusBadge> : null}
              </article>
            ))}
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}
