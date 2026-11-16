import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request, newIdempotencyKey } from "@edu/auth-client";
import { Button, useToast } from "@edu/ui";
import { copyText } from "@/lib/clipboard";

type Summary = Record<string, { code: string; recoverable: boolean; expires_at: string }>;
const queryKey = ["teaching-invitation-summary"];

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
  return <div className="section">
    {invitations.isPending ? <p>正在读取邀请码…</p> : invitations.error ? <Button onClick={() => void invitations.refetch()}>重试读取邀请码</Button> : current ? <>
      <p>邀请码：<code style={{ overflowWrap: "anywhere" }}>{current.code}</code></p>
      <p className="subtle">有效至 {new Date(current.expires_at).toLocaleDateString()} · 使用后需教师审核</p>
      {current.recoverable ? <Button onClick={() => { void copyText(current.code).then(copied => toast.notify(copied ? "邀请码已复制" : "复制失败，请手动复制", copied ? "default" : "error")).catch(() => toast.notify("复制失败，请手动复制", "error")); }}>复制邀请码</Button> : <p className="subtle">历史邀请码仅保留脱敏值，可生成新码供学生申请。</p>}
    </> : <p className="subtle">暂无可用邀请码，或当前账号无查看权限。</p>}
    {(!current || !current.recoverable) && <Button disabled={generate.isPending} onClick={() => generate.mutate()}>生成邀请码</Button>}
  </div>;
}
