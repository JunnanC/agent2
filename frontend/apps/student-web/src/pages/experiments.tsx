import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { taskApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, DataTable, FilterBar,  Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { formatDateTime, taskStatusLabel, taskStatusTone } from "@/lib/task-format";

const STATUS_FILTERS = [
  { value: "all", label: "全部状态" },
  { value: "ASSIGNED", label: "待开始" },
  { value: "READY", label: "已准备" },
  { value: "IN_PROGRESS", label: "进行中" },
  { value: "REPORT_DRAFT", label: "报告草稿" },
  { value: "COMPLETED", label: "已完成" },
  { value: "REJECTED", label: "需修改" },
  { value: "FAILED", label: "需处理" },
];

export function Experiments() {
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");

  const tasks = useQuery({
    queryKey: keys.tasks({ status: status === "all" ? null : status, q: search }),
    queryFn: () => taskApi.list({ page_size: 50, status: status === "all" ? undefined : status }),
  });

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (tasks.data?.rows ?? [])
      .filter((task) => !query || task.title.toLowerCase().includes(query));
  }, [tasks.data, search]);

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="我的实验" />
      
      <Panel>
        <RequestStateView
          loading={tasks.isLoading}
          error={tasks.error}
          onRetry={() => void tasks.refetch()}
          empty={!rows.length}
          emptyState={(
            <div className="state-block">
              <strong>暂无实验任务</strong>
              <p>实验发布后，任务会按照课程分配到这里。</p>
              <Link className="btn" to="/courses">查看我的课程</Link>
            </div>
          )}
        >
          <FilterBar
            search={{ value: search, onChange: setSearch, label: "搜索实验任务", placeholder: "按名称搜索" }}
            selects={[{ label: "状态", value: status, onChange: setStatus, options: STATUS_FILTERS }]}
          />
          <div className="section" style={{ marginTop: 4 }}>
            <DataTable
              rows={rows}
              rowKey={(task) => task.public_id}
              empty={undefined}
              columns={[
                {
                  key: "title", header: "任务", render: (task) => (
                    <div>
                      <Link className="task-title" to={`/experiments/${task.public_id}`}>{task.title}</Link>
                      <small style={{ display: "block" }}>{task.template_name ?? task.template_version_id}</small>
                    </div>
                  ),
                },
                { key: "progress", header: "完成度", width: 130, render: (task) => (
                  <div style={{ minWidth: 110 }}>
                    <div className="progress"><span style={{ width: `${task.progress}%` }} /></div>
                    <small style={{ display: "block", marginTop: 3 }}>{task.progress}%</small>
                  </div>
                ) },
                { key: "deadline", header: "截止", render: (task) => formatDateTime(task.effective_deadline) },
                { key: "status", header: "状态", render: (task) => (
                  <StatusBadge tone={taskStatusTone(task.status)}>{taskStatusLabel(task.status)}</StatusBadge>
                ) },
                {
                  key: "actions", header: "", align: "right", width: 150, render: (task) => (
                    <div className="table-actions">
                      {task.assessment_available
                        ? <Link className="btn sm primary" to={`/experiments/${task.public_id}/assessment`}>{
                          ["COMPLETED", "APPROVED"].includes(task.status)
                            ? "查看答卷"
                            : ["IN_PROGRESS", "REPORT_DRAFT", "READY"].includes(task.status)
                              ? "继续答题"
                              : "进入实验答题"
                        }</Link>
                        : <Link className="btn sm" to={`/experiments/${task.public_id}`}>查看详情</Link>}
                    </div>
                  ),
                },
              ]}
            />
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}
