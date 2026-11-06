import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useNavigate } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  Modal, Button, Breadcrumbs, ConfirmDialog, Panel, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";

interface TemplateRow {
  public_id: string;
  name: string;
  category?: string | null;
  description?: string | null;
  status: string;
  current_version_no?: number;
  current_version_id?: string | null;
  row_version?: number | string;
  owner_id?: string;
}

const STATUS_TONE: Record<string, "good" | "warn" | "blue" | "neutral"> = {
  PUBLISHED: "good",
  DRAFT: "warn",
  REVIEWING: "blue",
};

const STATUS_LABEL: Record<string, string> = {
  PUBLISHED: "已发布",
  DRAFT: "草稿",
  REVIEWING: "评审中",
};

export function Templates() {
  const { courseId = "" } = useParams();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("network");
  const [description, setDescription] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<TemplateRow | null>(null);

  const course = useQuery({ queryKey: keys.teachingCourse(courseId), queryFn: () => teachingApi.course(courseId) });
  const templates = useQuery({ queryKey: keys.templates(courseId, {}), queryFn: () => teachingApi.templates(courseId, {}) });

  const create = useMutation({
    mutationFn: () => teachingApi.createTemplate(courseId, { name: name.trim(), category, description: description.trim() || undefined }),
    onSuccess: (created) => {
      toast.notify(`模板「${created.name}」已创建，可继续配置版本`);
      setCreateOpen(false);
      setName("");
      void templates.refetch();
      navigate(`/courses/${courseId}/templates/${created.public_id}/edit`);
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const remove = useMutation({
    mutationFn: (target: TemplateRow) =>
      teachingApi.deleteTemplate(courseId, target.public_id, target.row_version ?? null),
    onSuccess: () => {
      toast.notify("模板已删除");
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: keys.templates(courseId, {}) });
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (templates.data?.rows ?? [])
      .filter((row: TemplateRow) => statusFilter === "all" || row.status === statusFilter)
      .filter((row: TemplateRow) => !query || row.name.toLowerCase().includes(query) || row.category?.toLowerCase().includes(query));
  }, [templates.data, statusFilter, search]);

  return (
    <>
      <Breadcrumbs
        items={[{ label: "教师门户", onClick: () => { window.location.assign("/"); } }]}
        current="实验设计"
      />
      <div className="page-actions align-end">
        <Button variant="primary" onClick={() => setCreateOpen(true)}>新建实验模板</Button>
      </div>

      <Panel title={<><h2>{course.data?.title ?? "实验模板"}</h2><span className="subtle">模板与版本分离管理，已发布版本不会被草稿修改覆盖</span></>}
        actions={(
          <>
            <select className="field" style={{ width: "auto", minWidth: 120 }} aria-label="模板状态"
              value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">全部状态</option>
              <option value="PUBLISHED">已发布</option>
              <option value="DRAFT">草稿</option>
            </select>
            <input className="field" style={{ width: 190 }} type="search" aria-label="搜索模板"
              placeholder="搜索模板" value={search} onChange={(event) => setSearch(event.target.value)} />
          </>
        )}>
        <RequestStateView
          loading={templates.isLoading}
          error={templates.error}
          onRetry={() => void templates.refetch()}
          empty={!rows.length}
          emptyState={(
            <div className="state-block">
              <strong>{templates.data?.rows.length ? "没有匹配的模板" : "暂无实验模板"}</strong>
              <p>{templates.data?.rows.length ? "试试其他状态或关键词。" : "创建第一个模板后会建立草稿版本。"}</p>
              <Button variant="primary" onClick={() => setCreateOpen(true)}>新建实验模板</Button>
            </div>
          )}
        >
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>模板名称</th><th>当前版本</th><th>发布状态</th><th>分类</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((row: TemplateRow) => {
                  const actionLabel = row.status === "PUBLISHED" ? "配置模板"
                    : row.status === "DRAFT" ? "继续编辑" : "查看版本";
                  const isDraft = row.status === "DRAFT";
                  return (
                    <tr key={row.public_id}>
                      <td><strong>{row.name}</strong></td>
                      <td>{row.current_version_no ? `v${row.current_version_no}` : "—"}</td>
                      <td>
                        <StatusBadge tone={STATUS_TONE[row.status] ?? "blue"}>
                          {STATUS_LABEL[row.status] ?? row.status}
                        </StatusBadge>
                      </td>
                      <td>{row.category ?? "—"}</td>
                      <td className="table-actions">
                        <Link className={`btn sm${row.status === "PUBLISHED" ? " primary" : ""}`}
                          to={`/courses/${courseId}/templates/${row.public_id}/edit`}>
                          {actionLabel}
                        </Link>
                        <Link className="btn sm" to={`/courses/${courseId}/templates/${row.public_id}/validate?version=${row.current_version_id ?? ""}`}>验证实验</Link>
                        <Link className="btn sm" to={`/courses/${courseId}/publishing?template=${row.public_id}`}>配置发布</Link>
                        {isDraft ? (
                          <Button size="sm" variant="danger"
                            disabled={remove.isPending}
                            onClick={() => setDeleteTarget(row)}>
                            删除
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} eyebrow="实验设计"
        title="新建实验模板"
        actions={(
          <>
            <Button onClick={() => setCreateOpen(false)}>取消</Button>
            <Button variant="primary" disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "创建中…" : "创建并进入配置"}
            </Button>
          </>
        )}>
        <p className="subtle">模板属于当前课程。创建后会建立草稿版本。</p>
        <label className="form-label" htmlFor="tpl-name">模板名称 <span>必填</span></label>
        <input id="tpl-name" className="field" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：Linux 网络故障排查实验" />
        <label className="form-label" htmlFor="tpl-category">实验分类</label>
        <select id="tpl-category" className="field" value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="network">网络基础</option>
          <option value="os">操作系统</option>
          <option value="database">数据库</option>
          <option value="Other">其他</option>
        </select>
        <label className="form-label" htmlFor="tpl-desc">模板简介 <span>选填</span></label>
        <textarea id="tpl-desc" className="field" rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => { if (deleteTarget) remove.mutate(deleteTarget); }}
        title="删除实验模板"
        tone="danger"
        busy={remove.isPending}
        description={(
          <p>
            确认删除模板「{deleteTarget?.name}」？删除后模板将从列表移除，仅模板创建者可执行，
            已发布模板需先撤回版本。
          </p>
        )}
      />
    </>
  );
}
