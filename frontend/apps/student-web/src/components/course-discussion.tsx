import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { courseDiscussionApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, EmptyState, Panel, RequestStateView, useToast } from "@edu/ui";

export function CourseDiscussion({ courseId }: { courseId: string }) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [replies, setReplies] = useState<Record<string, string>>({});
  const questions = useQuery({ queryKey: keys.courseResource(courseId, "questions"), queryFn: () => courseDiscussionApi.questions(courseId) });
  const create = useMutation({
    mutationFn: () => courseDiscussionApi.createQuestion(courseId, { title: title.trim(), body: body.trim() }),
    onSuccess: () => { setTitle(""); setBody(""); void questions.refetch(); toast.notify("问题已发布"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const reply = useMutation({
    mutationFn: (questionId: string) => courseDiscussionApi.answerQuestion(questionId, (replies[questionId] ?? "").trim()),
    onSuccess: (_, questionId) => { setReplies((current) => ({ ...current, [questionId]: "" })); void questions.refetch(); toast.notify("回复已发布"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  return <Panel title={<h2>课程问答</h2>}>
    <form onSubmit={(event) => { event.preventDefault(); if (title.trim() && body.trim()) create.mutate(); }}>
      <label className="form-label" htmlFor="question-title">问题标题</label>
      <input id="question-title" className="field" value={title} maxLength={180} required onChange={(event) => setTitle(event.target.value)} />
      <label className="form-label" htmlFor="question-body">问题描述</label>
      <textarea id="question-body" className="field" value={body} required rows={3} onChange={(event) => setBody(event.target.value)} />
      <Button type="submit" variant="primary" disabled={create.isPending || !title.trim() || !body.trim()}>{create.isPending ? "发布中…" : "发布问题"}</Button>
    </form>
    <RequestStateView loading={questions.isLoading} error={questions.error} onRetry={() => void questions.refetch()}
      empty={!questions.data?.rows.length} emptyState={<EmptyState title="暂无课程提问" />}>
      {(questions.data?.rows ?? []).map((question) => <article className="section" key={question.public_id}>
        <strong>{question.title}</strong><small className="subtle"> · {question.author_name}</small>
        <p style={{ whiteSpace: "pre-wrap" }}>{question.body}</p>
        {question.answers.map((answer) => <div className="item" key={answer.public_id}><div><strong>{answer.author_name}</strong><p style={{ whiteSpace: "pre-wrap" }}>{answer.body}</p></div></div>)}
        <form onSubmit={(event) => { event.preventDefault(); if (replies[question.public_id]?.trim()) reply.mutate(question.public_id); }}>
          <label className="form-label" htmlFor={`reply-${question.public_id}`}>回复「{question.title}」</label>
          <textarea id={`reply-${question.public_id}`} className="field" rows={2} required value={replies[question.public_id] ?? ""}
            onChange={(event) => setReplies((current) => ({ ...current, [question.public_id]: event.target.value }))} />
          <Button type="submit" size="sm" disabled={reply.isPending || !replies[question.public_id]?.trim()}>回复</Button>
        </form>
      </article>)}
    </RequestStateView>
  </Panel>;
}
