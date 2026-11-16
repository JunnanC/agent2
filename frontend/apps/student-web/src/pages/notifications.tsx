import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, EmptyState, Icon, Modal, Panel, RequestStateView, StatusBadge, isSafeUrl, useToast } from "@edu/ui";
import type { IconName } from "@edu/ui";
import { formatDateTime } from "@/lib/task-format";

interface NotificationRow {
  id: string;
  kind?: string | null;
  title: string;
  body?: string | null;
  read: boolean;
  row_version?: number;
  created_at?: string | null;
  links?: Array<{ label?: string; task_id?: string; course_id?: string; url?: string }> | null;
}

const KIND_ICON: Record<string, IconName> = {
  deadline: "calendar-clock",
  review: "message",
  system: "bell",
  risk: "alert-triangle",
  recommendation: "lightbulb",
};

export function Notifications() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const pendingReads = useRef(new Set<string>());
  const [readFilter, setReadFilter] = useState<"all" | "unread">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const notifications = useQuery({
    queryKey: keys.notifications({}),
    queryFn: () => meApi.notifications({ page_size: 50 }),
  });

  const markRead = useMutation({
    mutationFn: (row: NotificationRow) => {
      if (row.row_version == null) throw new Error("通知版本缺失，请刷新后重试");
      return meApi.markNotificationRead(row.id, row.row_version);
    },
    onSuccess: (_result, row) => {
      queryClient.setQueryData<Awaited<ReturnType<typeof meApi.notifications>>>(keys.notifications({}), (current) => current && ({
        ...current, rows: current.rows.map((item) => item.id === row.id
          ? { ...item, read: true, row_version: (row.row_version ?? 0) + 1 } : item),
      }));
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: () => {
      toast.notify("自动标记已读失败，请点击标记已读重试", "error");
      void notifications.refetch();
    },
    onSettled: (_result, _error, row) => { pendingReads.current.delete(row.id); },
  });

  function markAsRead(row: NotificationRow) {
    if (row.read || pendingReads.current.has(row.id)) return;
    pendingReads.current.add(row.id);
    markRead.mutate(row);
  }

  function viewNotification(row: NotificationRow) {
    setSelectedId(row.id);
    markAsRead(row);
  }

  const rows = (notifications.data?.rows ?? []) as NotificationRow[];
  const unread = rows.filter((row) => !row.read).length;
  const visible = readFilter === "all" ? rows : rows.filter((row) => !row.read);
  const selected = rows.find((row) => row.id === selectedId);

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="通知" />
      <header className="student-overview-heading">
        <div><h1>通知</h1><p>任务截止、报告评审与课程消息，在这里查看</p></div>
      </header>
      <Panel className="student-notifications">
        <div className="notification-filters">
          <div className="notification-tabs" aria-label="通知筛选">
            <button type="button" aria-pressed={readFilter === "all"} onClick={() => setReadFilter("all")}>全部</button>
            <button type="button" aria-pressed={readFilter === "unread"} onClick={() => setReadFilter("unread")}>未读</button>
          </div>
          <span className="subtle" aria-live="polite">{unread ? `${unread} 条未读` : "全部已读"}</span>
        </div>
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
                  <Icon name={KIND_ICON[row.kind ?? ""] ?? "bell"} size={18} />
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="notification-card-head">
                    <strong>{row.title}</strong>
                    <small>{formatDateTime(row.created_at)}</small>
                  </div>
                  <p style={{ margin: "4px 0 0" }}>{row.body}</p>
                  <div className="notification-actions">
                    <Button size="sm" onClick={() => viewNotification(row)}>查看详情</Button>
                    {!row.read
                      ? <Button size="sm" disabled={markRead.isPending} onClick={() => markAsRead(row)}>
                        {markRead.isPending && markRead.variables?.id === row.id ? "标记中…" : "标记已读"}
                      </Button> : null}
                  </div>
                </div>
                {!row.read ? <StatusBadge tone="warn">未读</StatusBadge> : null}
              </article>
            ))}
          </div>
        </RequestStateView>
      </Panel>
      <Modal open={selected != null} title={selected?.title ?? "通知详情"} onClose={() => setSelectedId(null)}
        actions={<Button onClick={() => setSelectedId(null)}>关闭</Button>}>
        {selected && <>
          <p className="subtle">{formatDateTime(selected.created_at)} · {selected.read ? "已读" : "未读"}</p>
          <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{selected.body || "此通知暂无补充内容。"}</p>
          <div className="notification-actions">
            {!selected.read && <Button size="sm" disabled={markRead.isPending} onClick={() => markAsRead(selected)}>
              {markRead.isPending ? "标记中…" : "标记已读"}
            </Button>}
            {(selected.links ?? []).filter((link) => link.task_id || link.course_id || link.url).map((link) => {
              const href = link.url || (link.task_id ? `/experiments/${link.task_id}` : `/courses/${link.course_id}`);
              if (!isSafeUrl(href)) return null;
              const label = href.startsWith("/experiments/") ? "查看实验任务"
                : href.startsWith("/courses/") ? "查看课程" : link.label && link.label !== "查看详情" ? link.label : "打开相关页面";
              return <a key={link.url ?? link.task_id ?? link.course_id ?? href} className="btn sm" href={href}>{label}</a>;
            })}
          </div>
        </>}
      </Modal>
    </>
  );
}
