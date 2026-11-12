import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { agentApi, fileApi } from "@edu/api-client";
import type { AgentFeedback, AgentMessage, AgentMode, AgentSession, AgentToolCall } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, EmptyState, Panel, RequestStateView, useToast } from "@edu/ui";

const modeLabels: Record<AgentMode, string> = {
  KNOWLEDGE_QA: "课程问答", SOCRATIC_HINT: "启发提示", DEBUG_ASSIST: "调试辅助",
  REPORT_COACH: "报告指导", CODE_ASSIST: "工作区助手",
};
const toolStates: Record<string, string> = {
  PENDING_APPROVAL: "等待确认", QUEUED: "排队中", RUNNING: "执行中", SUCCEEDED: "已完成",
  FAILED: "执行失败", REJECTED: "已拒绝", DENIED: "禁止执行", EXPIRED: "已过期",
};

// POST acknowledges a USER message; the ASSISTANT reply arrives asynchronously.
function agentReplyPending(messages: AgentMessage[]): boolean {
  const lastUserIndex = messages.findLastIndex((message) => message.role === "USER");
  return lastUserIndex >= 0 && !messages.slice(lastUserIndex + 1).some((message) =>
    message.role === "ASSISTANT" && ["COMPLETE", "FAILED"].includes(message.status));
}

export function CourseAgent({ courseId, taskId }: { courseId: string; taskId?: string }) {
  const [open, setOpen] = useState(false);
  return <Panel title={<h2>{taskId ? "实验助手" : "课程助手"}</h2>} actions={<Button onClick={() => setOpen(!open)}>{open ? "收起助手" : "打开助手"}</Button>}>
    {open ? <AgentConversation key={`${courseId}-${taskId ?? "course"}`} courseId={courseId} taskId={taskId} /> :
      <p className="subtle">使用教师开放的辅助模式，获取课程解答和实验指导。</p>}
  </Panel>;
}

function AgentConversation({ courseId, taskId }: { courseId: string; taskId?: string }) {
  const client = useQueryClient();
  const toast = useToast();
  const activeKey = keys.activeAgentSession(courseId, taskId);
  const [sessionId, setSessionId] = useState(() => client.getQueryData<string>(activeKey) ?? "");
  const [mode, setMode] = useState<AgentMode | "">("");
  const [body, setBody] = useState("");
  const [feedbackSent, setFeedbackSent] = useState<Record<string, boolean>>({});
  const profile = useQuery({ queryKey: keys.agentProfile(courseId), queryFn: () => agentApi.courseProfile(courseId) });
  const modes = profile.data?.capabilities.modes ?? [];
  const selectedMode = modes.includes(mode as AgentMode) ? mode as AgentMode : modes[0];
  const session = useQuery({ queryKey: keys.agentSession(sessionId), queryFn: () => agentApi.session(sessionId), enabled: Boolean(sessionId) });
  const messages = useQuery({ queryKey: keys.agentMessages(sessionId), queryFn: () => agentApi.messages(sessionId), enabled: Boolean(sessionId),
    refetchInterval: (query) => {
      const rows = query.state.data?.rows ?? [];
      return agentReplyPending(rows) || rows.some((message) => message.tool_calls.some((tool) => ["QUEUED", "RUNNING"].includes(tool.state?.status ?? ""))) ? 2000 : false;
    },
  });
  const create = useMutation({
    mutationFn: () => {
      if (!selectedMode) throw new Error("当前课程未开放辅助模式");
      return taskId ? agentApi.createTaskSession(taskId, selectedMode) : agentApi.createCourseSession(courseId, selectedMode);
    },
    onSuccess: (data: AgentSession) => {
      client.setQueryData(keys.agentSession(data.public_id), data); client.setQueryData(activeKey, data.public_id);
      setSessionId(data.public_id); setBody("");
    }, onError: (error) => toast.notify(error.message, "error"),
  });
  const send = useMutation({
    mutationFn: () => agentApi.sendMessage(sessionId, body.trim()),
    onSuccess: (message) => {
      client.setQueryData(keys.agentMessages(sessionId), (previous: Awaited<ReturnType<typeof agentApi.messages>> | undefined) => {
        const rows = [...(previous?.rows ?? []).filter((item) => item.public_id !== message.public_id), message];
        return { rows, page: 1, pageSize: rows.length, total: rows.length };
      });
      setBody(""); void messages.refetch();
    }, onError: (error) => { toast.notify(error.message, "error"); void session.refetch(); },
  });
  const feedback = useMutation({ mutationFn: (input: { id: string; rating: AgentFeedback["rating"] }) => agentApi.feedback(input.id, { rating: input.rating }),
    onSuccess: (_, input) => { setFeedbackSent((current) => ({ ...current, [input.id]: true })); toast.notify("反馈已提交"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const decide = useMutation({ mutationFn: (input: { tool: AgentToolCall; decision: "APPROVED" | "REJECTED" }) => {
    if (input.tool.state?.status !== "PENDING_APPROVAL") throw new Error("工具调用状态已变化，请刷新后重试");
    return agentApi.decideToolCall(input.tool.public_id, { decision: input.decision }, input.tool.state.row_version);
  }, onSuccess: () => { void messages.refetch(); }, onError: (error) => { toast.notify(error.message, "error"); void messages.refetch(); } });
  const download = useMutation({ mutationFn: (assetId: string) => fileApi.createDownloadGrant(assetId),
    onSuccess: (grant) => { if (grant.download_path.startsWith("/files/") && !grant.download_path.includes("\\")) window.location.assign(grant.download_path); else toast.notify("下载地址无效", "error"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const rows = messages.data?.rows ?? [];
  const waiting = agentReplyPending(rows);
  return <RequestStateView loading={profile.isLoading} error={profile.error} onRetry={() => void profile.refetch()} empty={!modes.length} emptyState={<EmptyState title="当前课程尚未开放助手" />}>
    <label className="form-label">辅助模式<select className="field" value={selectedMode ?? ""} disabled={create.isPending || send.isPending || waiting}
      onChange={(event) => setMode(event.target.value as AgentMode)}>{modes.map((value) => <option key={value} value={value}>{modeLabels[value]}</option>)}</select></label>
    <Button disabled={create.isPending || send.isPending || waiting || !selectedMode} onClick={() => create.mutate()}>{create.isPending ? "创建中…" : sessionId ? "开始新对话" : "开始对话"}</Button>
    {sessionId && <>
      <RequestStateView loading={session.isLoading} error={session.error} empty={false} onRetry={() => void session.refetch()}>
        {session.data && <p className="subtle">当前对话 · {modeLabels[session.data.mode]}{session.data.status !== "ACTIVE" ? " · 已暂停，请开始新对话" : ""}</p>}
      </RequestStateView>
      <RequestStateView loading={messages.isLoading} error={messages.error} onRetry={() => void messages.refetch()} empty={!rows.length} emptyState={<p className="subtle">输入你的课程或实验问题。</p>}>
        <div aria-label="助手对话" style={{ maxHeight: 480, overflowY: "auto" }}>{rows.map((message) => <article className="section" key={message.public_id}>
          <strong>{message.role === "USER" ? "我" : "助手"}</strong><p style={{ whiteSpace: "pre-wrap" }}>{message.body}</p>
          {message.status === "FAILED" && <p role="alert">回复生成失败，可重新提问。</p>}
          {message.citations.map((citation) => <div className="item" key={citation.public_id}><div><strong>{citation.title}</strong><p>{citation.accessible ? citation.snippet : "引用内容暂不可访问"}</p></div>
            {citation.accessible && citation.asset_id && <Button size="sm" disabled={download.isPending} onClick={() => download.mutate(citation.asset_id!)}>下载引用</Button>}</div>)}
          {message.tool_calls.map((tool) => <div className="section" key={tool.public_id}>
            <strong>{tool.tool_name}</strong><span> · {toolStates[tool.state?.status ?? ""] ?? tool.state?.status}</span>
            {tool.state?.status === "PENDING_APPROVAL" && <div className="page-actions"><span>该操作需要你确认（{tool.risk}）</span>
              <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ tool, decision: "APPROVED" })}>允许执行</Button>
              <Button size="sm" disabled={decide.isPending} onClick={() => decide.mutate({ tool, decision: "REJECTED" })}>拒绝执行</Button></div>}
            {tool.state?.error_code && <p role="alert">工具执行失败：{tool.state.error_code}</p>}
          </div>)}
          {message.role === "ASSISTANT" && message.status === "COMPLETE" && <div className="page-actions">
            <Button size="sm" disabled={feedback.isPending || feedbackSent[message.public_id]} onClick={() => feedback.mutate({ id: message.public_id, rating: "USEFUL" })}>有帮助</Button>
            <Button size="sm" disabled={feedback.isPending || feedbackSent[message.public_id]} onClick={() => feedback.mutate({ id: message.public_id, rating: "NOT_USEFUL" })}>没有帮助</Button>
          </div>}
        </article>)}</div>
      </RequestStateView>
      {waiting && <p role="status">助手正在回复，完成后会自动更新。</p>}
      <form onSubmit={(event) => { event.preventDefault(); if (body.trim() && !waiting && !send.isPending && session.data?.status === "ACTIVE") send.mutate(); }}>
        <label className="form-label" htmlFor={`agent-body-${taskId ?? courseId}`}>向助手提问</label>
        <textarea className="field" id={`agent-body-${taskId ?? courseId}`} rows={3} value={body} disabled={send.isPending} onChange={(event) => setBody(event.target.value)} />
        <Button type="submit" variant="primary" disabled={!body.trim() || send.isPending || waiting || messages.isError || session.data?.status !== "ACTIVE"}>{send.isPending ? "发送中…" : "发送"}</Button>
      </form>
    </>}
  </RequestStateView>;
}
