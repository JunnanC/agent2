import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import type { NotificationPreferenceUpdate } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Panel, RequestStateView, useToast } from "@edu/ui";

export function NotificationPreferencesPanel() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const preferences = useQuery({ queryKey: keys.notificationPreferences(), queryFn: meApi.notificationPreferences });
  const update = useMutation({
    mutationFn: (payload: NotificationPreferenceUpdate) => meApi.updateNotificationPreferences(payload, preferences.data?.row_version ?? null),
    onSuccess: (data) => { queryClient.setQueryData(keys.notificationPreferences(), data); toast.notify("通知偏好已保存"); },
    onError: (error) => { toast.notify(error.message, "error"); void preferences.refetch(); },
  });
  return <Panel title={<h2>通知偏好</h2>}>
    <RequestStateView loading={preferences.isLoading} error={preferences.error} onRetry={() => void preferences.refetch()} empty={!preferences.data}>
      <label className="item"><span><strong>站内通知</strong><small>在通知中心接收学习消息</small></span>
        <input type="checkbox" checked={preferences.data?.channels.in_app ?? true} disabled={update.isPending || !preferences.data}
          onChange={(event) => update.mutate({ channels: { ...preferences.data?.channels, in_app: event.target.checked } })} /></label>
      <label className="item"><span><strong>通知摘要</strong><small>接收汇总消息</small></span>
        <input type="checkbox" checked={preferences.data?.digest_enabled ?? false} disabled={update.isPending || !preferences.data}
          onChange={(event) => update.mutate({ digest_enabled: event.target.checked })} /></label>
    </RequestStateView>
  </Panel>;
}
