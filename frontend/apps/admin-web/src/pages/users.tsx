import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import type { PlatformUser, Verification } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  Button, Modal, Panel,  RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { useState } from "react";

export function Users() {
  const toast = useToast();
  const [reviewTarget, setReviewTarget] = useState<Verification | null>(null);
  const [note, setNote] = useState("");

  const users = useQuery({ queryKey: keys.platformUsers({}), queryFn: () => platformApi.users({ page_size: 100 }) });
  const verifications = useQuery({ queryKey: keys.verifications({ status: "PENDING" }), queryFn: () => platformApi.verifications({ status: "PENDING" }) });

  const review = useMutation({
    mutationFn: (input: { target: Verification; decision: "approve" | "reject" }) =>
      platformApi.reviewVerification(input.target.public_id, { decision: input.decision, note }, input.target.payload_summary?.row_version as string ?? ""),
    onSuccess: (_data, input) => {
      toast.notify(input.decision === "approve" ? "已通过" : "已拒绝");
      setReviewTarget(null);
      void verifications.refetch();
      void users.refetch();
    },
    onError: () => toast.notify("审核失败，请检查权限后重试", "error"),
  });

  const rows = users.data?.rows ?? [];
  const pendingVerifications = verifications.data?.rows ?? [];

  return (
    <>
      
      <Panel title={<><h2>待处理资格申请</h2><span className="subtle">按提交时间排序</span></>}>
        <RequestStateView
          loading={verifications.isLoading}
          error={verifications.error}
          onRetry={() => void verifications.refetch()}
          empty={!pendingVerifications.length}
          emptyState={<div className="state-block"><strong>暂无待处理资格申请</strong></div>}
        >
          <div>
            {pendingVerifications.map((item) => (
              <div className="item" key={item.public_id}>
                <div>
                  <strong>{item.target_user_name ?? item.public_id}</strong>
                  <small>{item.kind} · {item.submitted_at}</small>
                </div>
                <Button size="sm" variant="primary" onClick={() => setReviewTarget(item)}>处理</Button>
              </div>
            ))}
          </div>
        </RequestStateView>
      </Panel>

      <Panel className="section" title={<h2>用户列表</h2>}>
        <RequestStateView
          loading={users.isLoading}
          error={users.error}
          onRetry={() => void users.refetch()}
          empty={!rows.length}
          emptyState={<div className="state-block"><strong>暂无用户</strong></div>}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>用户</th><th>邮箱</th><th>账号状态</th><th>资格</th><th>管理员</th></tr></thead>
              <tbody>
                {rows.map((user: PlatformUser) => (
                  <tr key={user.public_id}>
                    <td><strong>{user.display_name}</strong><small style={{ display: "block" }}>{user.username}</small></td>
                    <td>{user.email}</td>
                    <td><StatusBadge tone={user.account_status === "ACTIVE" ? "good" : "neutral"}>{user.account_status}</StatusBadge></td>
                    <td>{user.teacher_qualification?.status
                      ? <StatusBadge tone={user.teacher_qualification.status === "APPROVED" ? "good" : "warn"}>{user.teacher_qualification.status}</StatusBadge>
                      : <span className="subtle">未申请</span>}</td>
                    <td>{user.admin_assignment?.role ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <Modal open={reviewTarget != null} onClose={() => setReviewTarget(null)} eyebrow="资格审核"
        title={reviewTarget ? `审核 ${reviewTarget.target_user_name ?? ""}` : "资格审核"}
        actions={(
          <>
            <Button onClick={() => setReviewTarget(null)}>取消</Button>
            <Button variant="danger" disabled={review.isPending} onClick={() => { if (reviewTarget) review.mutate({ target: reviewTarget, decision: "reject" }); }}>拒绝</Button>
            <Button variant="primary" disabled={review.isPending} onClick={() => { if (reviewTarget) review.mutate({ target: reviewTarget, decision: "approve" }); }}>
              {review.isPending ? "处理中…" : "通过"}
            </Button>
          </>
        )}>
        <p className="subtle">审核会记录操作日志并影响对应门户的访问资格。</p>
        <label className="form-label" htmlFor="verify-note">审核备注 <span>选填</span></label>
        <textarea id="verify-note" className="field" rows={2} value={note} onChange={(event) => setNote(event.target.value)} />
      </Modal>
    </>
  );
}
