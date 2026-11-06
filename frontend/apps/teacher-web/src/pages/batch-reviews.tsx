import { useState } from "react";
import { teachingApi } from "@edu/api-client";
import type { ReviewSummary } from "@edu/api-client";
import { useToast, ConfirmDialog } from "@edu/ui";

export function BatchReviews({ courseId, publicationId, rows, refresh }: { courseId: string; publicationId: string; rows: ReviewSummary[]; refresh: () => void }) {
  const [selected, setSelected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [message, setMessage] = useState("");
  const toast = useToast();
  const run = async (action: "start" | "accept" | "confirm") => {
    setBusy(true); setConfirm(false);
    let success = 0; const failures: string[] = [];
    try {
      if (action === "start") {
        // Existing endpoint starts a publication-wide batch; do not imply subset scoring.
        await teachingApi.startAIScoreBatch(courseId, publicationId);
        setMessage("本次发布的 AI 评分作业已提交；稍后可批量采纳或进入报告核对建议");
      } else {
        const batch = action === "accept" ? (await teachingApi.aiScoreBatches(courseId, publicationId))[0] : null;
        if (action === "accept" && !batch) throw new Error("请先运行 AI 评分");
        for (const row of rows.filter(r => r.status === "PENDING")) {
          try {
            const detail = await teachingApi.review(courseId, row.public_id);
            if (action === "accept") {
              const suggestion = await teachingApi.aiScoreSuggestion(courseId, batch!.public_id, row.public_id);
              if (!suggestion || !["READY", "ACCEPTED"].includes(suggestion.status)) throw new Error("建议未就绪");
              await teachingApi.acceptAIScoreSuggestion(courseId, row.public_id, suggestion.public_id, detail.row_version);
            } else {
              if (!detail.rubric?.criteria.length || detail.rubric.criteria.some(c => c.score == null)) throw new Error("评分尚未完整保存");
              await teachingApi.decideReview(courseId, row.public_id, { decision: "approve" }, detail.row_version);
            }
            success += 1;
          } catch { failures.push(row.student_name); }
        }
        setMessage(`${action === "accept" ? "采纳建议（未确认成绩）" : "教师确认"}成功 ${success} 份；失败 ${failures.length} 份${failures.length ? `：${failures.join("、")}` : ""}`);
        refresh(); setSelected(false);
      }
    } catch (error) { toast.notify(error instanceof Error ? error.message : "批量操作失败", "error"); }
    finally { setBusy(false); }
  };
  return <><div className="batch-toolbar"><label><input type="checkbox" checked={selected} onChange={e => setSelected(e.target.checked)} disabled={busy} /> 全选全部筛选结果（{rows.length} 份）</label><button className="btn" disabled={busy || !publicationId} onClick={() => void run("start")}>本次发布 AI 批量评分</button><button className="btn" disabled={!selected || busy} onClick={() => void run("accept")}>批量采纳建议</button><button className="btn primary" disabled={!selected || busy} onClick={() => setConfirm(true)}>教师确认成绩</button></div><p className="subtle" role="status">{message || "采纳 AI 建议后，请逐份核对、调整分数，再由教师确认。AI 作业按整个发布运行。"}</p><ConfirmDialog open={confirm} onClose={() => setConfirm(false)} title="确认所选报告成绩？" description={`将确认当前筛选结果中已有完整评分的待审报告，共选择 ${rows.length} 份。未完成评分的报告会跳过并报告失败。`} confirmLabel="确认成绩" onConfirm={() => void run("confirm")} /></>;
}
