import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { request, newIdempotencyKey } from "@edu/auth-client";
import { Button, Modal, useToast } from "@edu/ui";

export function RubricCreate({ courseId, onCreated }: { courseId: string; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [criteria, setCriteria] = useState([{ title: "实验完成情况", score: "100" }]);
  const [rubricId, setRubricId] = useState("");
  const [version, setVersion] = useState<{ public_id: string; row_version: number } | null>(null);
  const toast = useToast();
  const total = criteria.reduce((sum, row) => sum + Number(row.score), 0);
  const valid = name.trim() && criteria.every((row) => row.title.trim() && Number(row.score) > 0) && total > 0;
  const create = useMutation({
    mutationFn: async () => {
      const base = `/teaching/courses/${courseId}`;
      const id = rubricId || (await request<{ public_id: string }>(`${base}/rubrics`, {
        method: "POST", body: { name: name.trim() }, idempotencyKey: newIdempotencyKey(),
      })).data.public_id;
      setRubricId(id);
      let weight = 0;
      const current = version || (await request<{ public_id: string; row_version: number }>(`${base}/rubrics/${id}/versions`, {
        method: "POST", idempotencyKey: newIdempotencyKey(), body: {
          title: name.trim(), total_score: total,
          criteria: criteria.map((row, index) => {
            const points = index === criteria.length - 1 ? 10000 - weight : Math.round(Number(row.score) / total * 10000);
            weight += points;
            return { title: row.title.trim(), max_score: Number(row.score), position: index + 1, weight_basis_points: points };
          }),
        },
      })).data;
      setVersion(current);
      await request(`${base}/rubric-versions/${current.public_id}/publish`, {
        method: "POST", body: {}, ifMatch: current.row_version, idempotencyKey: newIdempotencyKey(),
      });
    },
    onSuccess: () => { setOpen(false); setName(""); setRubricId(""); setVersion(null); onCreated(); toast.notify("评分表已发布，可用于实验发布"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  return <><Button onClick={() => setOpen(true)}>新建评分表</Button><Modal open={open} title="新建评分表" onClose={() => { if (!create.isPending) setOpen(false); }} actions={<Button variant="primary" disabled={!valid || create.isPending} onClick={() => create.mutate()}>{create.isPending ? "发布中…" : "创建并发布评分表"}</Button>}>
    <label className="form-label">评分表名称<input className="field" value={name} disabled={Boolean(rubricId)} onChange={(event) => setName(event.target.value)} /></label>
    {criteria.map((row, index) => <div className="page-actions" key={index}>
      <label className="form-label">评分项 {index + 1}<input className="field" disabled={Boolean(version)} value={row.title} onChange={(event) => setCriteria((rows) => rows.map((item, i) => i === index ? { ...item, title: event.target.value } : item))} /></label>
      <label className="form-label">满分<input className="field" type="number" min="0.01" step="0.01" disabled={Boolean(version)} value={row.score} onChange={(event) => setCriteria((rows) => rows.map((item, i) => i === index ? { ...item, score: event.target.value } : item))} /></label>
      {criteria.length > 1 && <Button disabled={Boolean(version)} onClick={() => setCriteria((rows) => rows.filter((_, i) => i !== index))}>删除评分项 {index + 1}</Button>}
    </div>)}
    <Button disabled={Boolean(version)} onClick={() => setCriteria((rows) => [...rows, { title: "", score: "10" }])}>添加评分项</Button><p>总分：{total}；权重按各项满分比例分配。</p>
  </Modal></>;
}
