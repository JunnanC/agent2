import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import { Breadcrumbs, Button, PageHeader, Panel,  useToast } from "@edu/ui";
import { useSession } from "@/app/session";
import { NotificationPreferencesPanel } from "@/components/notification-preferences";

export function Profile() {
  const toast = useToast();
  const { me, reload } = useSession();
  const [displayName, setDisplayName] = useState(me?.display_name ?? "");
  const [email, setEmail] = useState(me?.email ?? "");

  const save = useMutation({
    mutationFn: () => meApi.updateProfile({ display_name: displayName.trim() }, me?.row_version),
    onSuccess: () => {
      toast.notify("个人资料已保存");
      reload();
    },
    onError: (error) => {
      const payload = (error as { payload?: { message?: string } }).payload;
      if (payload && /row_version|conflict/i.test(String(payload.message))) {
        toast.notify("资料已被其他设备更新，请刷新后重试。", "error");
      } else {
        toast.notify(payload?.message ?? "保存失败", "error");
      }
    },
  });

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="个人设置" />
      <PageHeader title="个人设置" />
      <div className="grid equal">
        <Panel title={<h2>个人资料</h2>}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 6 }}>
            <span className="avatar large">{(me?.display_name ?? me?.username ?? "").slice(0, 1)}</span>
            <div>
              <strong>{me?.display_name || me?.username}</strong>
              <small style={{ display: "block" }}>{me?.username}</small>
            </div>
          </div>
          <label className="form-label" htmlFor="display-name">显示名称</label>
          <input id="display-name" className="field" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          <label className="form-label" htmlFor="email">邮箱</label>
          <input id="email" className="field" value={email} onChange={(event) => setEmail(event.target.value)} disabled />
          <div className="section" style={{ marginTop: 12 }}>
            <Button variant="primary" disabled={save.isPending || !displayName.trim()}
              onClick={() => save.mutate()}>
              {save.isPending ? "保存中…" : "保存修改"}
            </Button>
          </div>
        </Panel>
        <NotificationPreferencesPanel />
      </div>
    </>
  );
}

