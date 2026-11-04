import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { meApi } from "@edu/api-client";
import type { NotificationItem } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, EmptyState, Panel, RequestStateView, StatusBadge, useToast } from "@edu/ui";
import { formatDateTime } from "@/lib/task-format";

export function Notifications() {
  const client = useQueryClient();
  const toast = useToast();
  const notifications = useQuery({
    queryKey: keys.notifications({}),
    queryFn: () => meApi.notifications({ page_size: 50 }),
    refetchInterval: 30_000,
  });
  const markRead = useMutation({
    mutationFn: (item: NotificationItem) => {
      if (item.row_version == null) throw new Error("通知版本缺失，请刷新后重试");
      return meApi.markNotificationRead(item.id, item.row_version);
    },
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["notifications"] }); },
    onError: (error) => { toast.notify(error.message, "error"); },
  });
  const rows = notifications.data?.rows ?? [];
  const unread = rows.filter((item) => !item.read).length;

  return <>
    <Breadcrumbs items={[{ label: "教师门户" }]} current="通知中心" />
    <Panel title={<><h2>通知中心</h2><StatusBadge tone={unread ? "warn" : "good"}>{unread} 条未读</StatusBadge></>}>
      <RequestStateView loading={notifications.isLoading} error={notifications.error}
        onRetry={() => void notifications.refetch()} empty={!rows.length}
        emptyState={<EmptyState title="暂无通知" hint="学生退课等课程消息会显示在这里。" />}>
        <div className="notification-list">
          {rows.map((item) => <article key={item.id} className={`notification-card${item.read ? " read" : ""}`}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="notification-card-head"><strong>{item.title}</strong><small>{formatDateTime(item.created_at)}</small></div>
              <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{item.body}</p>
              <div className="notification-actions">
                {(item.links ?? []).filter((link) => link.url?.startsWith("/courses/")).map((link, index) =>
                  <Link key={index} className="btn sm" to={link.url!}>查看选课管理</Link>)}
                {!item.read && <Button size="sm" disabled={markRead.isPending} onClick={() => markRead.mutate(item)}>
                  {markRead.isPending && markRead.variables?.id === item.id ? "标记中…" : "标记已读"}
                </Button>}
              </div>
            </div>
            {!item.read && <StatusBadge tone="warn">未读</StatusBadge>}
          </article>)}
        </div>
      </RequestStateView>
    </Panel>
  </>;
}
