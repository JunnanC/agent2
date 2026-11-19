import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { teachingApi, type Invitation } from "@edu/api-client";
import { request, newIdempotencyKey } from "@edu/auth-client";
import { keys } from "@edu/query-keys";
import { Button, useToast } from "@edu/ui";
import { copyText } from "@/lib/clipboard";
import { apiErrorMessage, formatDateTime } from "@/lib/format";

type Summary = Record<string, { code: string; recoverable: boolean; expires_at: string }>;
const queryKey = ["teaching-invitation-summary"];

export function CourseInvitationActions({ courseId }: { courseId: string }) {
  const toast = useToast();
  const client = useQueryClient();
  const [generated, setGenerated] = useState<Invitation | null>(null);
  const invitationKey = keys.invitations(courseId);
  const invitations = useQuery({ queryKey: invitationKey, queryFn: () => teachingApi.invitations(courseId) });
  const generate = useMutation({
    mutationFn: () => teachingApi.createInvitation(courseId, { valid_days: 30 }),
    onSuccess: async (created) => {
      setGenerated(created);
      const copied = await copyText(created.code);
      toast.notify(copied ? "新邀请码已生成并复制" : "新邀请码已生成，请手动复制", copied ? "default" : "error");
      void client.invalidateQueries({ queryKey: invitationKey });
      void client.invalidateQueries({ queryKey });
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const active = invitations.data?.rows.find((item) => ["ACTIVE", "ENABLED"].includes(item.status));
  const current = generated ?? active;
  const code = generated?.code ?? (active?.recoverable ? active.code : null);

  async function copyInvitation() {
    if (!code) return;
    const copied = await copyText(code);
    toast.notify(copied ? "邀请码已复制" : "浏览器未允许复制，请选中邀请码手动复制", copied ? "default" : "error");
  }

  return <div className="course-context-invitation" role="group" aria-label="课程邀请码">
    <div className="page-actions">
      <Button variant={code ? undefined : "primary"} disabled={generate.isPending || invitations.isPending}
        onClick={() => generate.mutate()}>
        {generate.isPending ? "生成中…" : code ? "重新生成邀请码" : "生成邀请码"}
      </Button>
      <Button variant={code ? "primary" : undefined} disabled={!code || generate.isPending} onClick={() => void copyInvitation()}>
        复制邀请码
      </Button>
    </div>
    {code ? <div className="course-context-invitation-details">
      <code>{code}</code>
      <small>{current?.expires_at ? `${formatDateTime(current.expires_at)} 失效` : "长期有效"}</small>
    </div> : invitations.isPending ? <small role="status">正在读取邀请码…</small>
      : invitations.isError ? <Button size="sm" onClick={() => void invitations.refetch()}>重试读取邀请码</Button>
        : <small>{active ? "旧邀请码已脱敏，可生成新码" : "暂无启用中的邀请码"}</small>}
  </div>;
}

export function CourseInvitation({ courseId }: { courseId: string }) {
  const toast = useToast();
  const client = useQueryClient();
  const invitations = useQuery({ queryKey, queryFn: () => request<Summary>("/teaching/course-invitations").then(result => result.data), staleTime: 30000 });
  const current = invitations.data?.[courseId];
  const generate = useMutation({
    mutationFn: () => request(`/teaching/courses/${courseId}/invitations`, { method: "POST", body: { max_uses: 100000, expires_at: new Date(Date.now() + 30 * 86400000).toISOString() }, idempotencyKey: newIdempotencyKey() }),
    onSuccess: () => { void client.invalidateQueries({ queryKey }); toast.notify("邀请码已生成，30 天内有效；学生使用后需审核"); },
    onError: (error: Error) => toast.notify(error.message, "error"),
  });
  return <div className="section course-invite-line" style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
    {invitations.isPending ? <p>正在读取邀请码…</p> : invitations.error ? <Button size="sm" onClick={() => void invitations.refetch()}>重试</Button> : current ? <>
      <code style={{ overflowWrap: "anywhere" }}>{current.code}</code>
      <small>至 {new Date(current.expires_at).toLocaleDateString()}</small>
      {current.recoverable ? <Button size="sm" onClick={() => { void copyText(current.code).then(copied => toast.notify(copied ? "邀请码已复制" : "复制失败，请手动复制", copied ? "default" : "error")).catch(() => toast.notify("复制失败，请手动复制", "error")); }}>复制</Button> : null}
    </> : <small>暂无邀请码</small>}
    {(!current || !current.recoverable) && <Button size="sm" disabled={generate.isPending} onClick={() => generate.mutate()}>{generate.isPending ? "生成中…" : "生成邀请码"}</Button>}
  </div>;
}
