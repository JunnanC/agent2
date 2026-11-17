import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { request, newIdempotencyKey } from "@edu/auth-client";
import { Button, Panel, useToast } from "@edu/ui";

export function DirectInvite({ courseId, onAdded }: { courseId: string; onAdded: () => void }) {
  const [identity, setIdentity] = useState("");
  const toast = useToast();
  const invite = useMutation({
    mutationFn: () => request(`/teaching/courses/${courseId}/direct-invitations`, { method: "POST", body: { identity: identity.trim() }, idempotencyKey: newIdempotencyKey() }),
    onSuccess: () => { setIdentity(""); onAdded(); toast.notify("学生已直接加入课程"); },
    onError: (error: Error) => toast.notify(error.message, "error"),
  });
  return <Panel title={<h2>教师邀请学生</h2>}>
    <p className="subtle">教师指定学生后直接加入；学生自行使用邀请码时需要审核。</p>
    <form onSubmit={event => { event.preventDefault(); invite.mutate(); }}>
      <label className="form-label">学生账号或邮箱<input className="field" value={identity} onChange={event => setIdentity(event.target.value)} /></label>
      <Button type="submit" disabled={!identity.trim() || invite.isPending}>{invite.isPending ? "添加中…" : "邀请并直接加入"}</Button>
    </form>
  </Panel>;
}
