import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import { Button, Panel,  useToast } from "@edu/ui";
import { useSession } from "@/app/session";

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
      
      <div className="grid two">
        <Panel title={<h2>个人资料</h2>}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 6 }}>
            <span className="avatar large">{(me?.display_name ?? me?.username ?? "").slice(0, 1)}</span>
            <div>
              <strong>{me?.username}</strong>
              <small style={{ display: "block" }}>学生 · {me?.portal}</small>
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
        <Panel title={<h2>通知偏好</h2>}>
          <div>
            <div className="item"><div><strong>实验截止提醒</strong><small>截止前 24 小时提醒</small></div><span className="status good">已开启</span></div>
            <div className="item"><div><strong>报告评审结果</strong><small>教师完成评审后通知</small></div><span className="status good">已开启</span></div>
            <div className="item"><div><strong>平台公告</strong><small>服务维护和平台通知</small></div><span className="status neutral">已关闭</span></div>
          </div>
        </Panel>
      </div>
    </>
  );
}
