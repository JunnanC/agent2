import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { TeacherAssessmentReview } from "@edu/api-client";
import { SubmissionEvidence } from "./students";

afterEach(cleanup);

const review = {
  task_id: "task-1",
  student_name: "张三",
  sources: [],
  sections: [{
    kind: "PROGRAMMING", status: "SUBMITTED", grading_status: "COMPLETED", review_status: "COMPLETED",
    score: "86", max_score: "100", submission_version: 1, row_version: 1,
    questions: [{ id: "q1", title: "计算两数之和", score: "86", max_score: "100", language: "python" }],
    report_score: "86", report_max_score: "100", feedback: "",
  }],
  report: { body_markdown: "# 报告正文", version_no: 2 },
  report_criteria: [{ id: "c1", title: "分析", max_score: "100" }],
} as unknown as TeacherAssessmentReview;

it("renders submitted evidence as readable fields and keeps raw JSON in a details block", () => {
  const { container } = render(<SubmissionEvidence review={review} />);
  expect(screen.getByText("编程与报告")).toBeTruthy();
  expect(screen.getByText("实验总报告 · 第 2 次提交")).toBeTruthy();
  expect(screen.getByText("# 报告正文")).toBeTruthy();
  expect(screen.getByText("报告评分项")).toBeTruthy();
  expect(screen.getByText("计算两数之和")).toBeTruthy();
  expect(screen.getByText("答题状态：已交卷 · 评分状态：评分完成")).toBeTruthy();
  const visible = container.cloneNode(true) as HTMLElement;
  visible.querySelector("details")?.remove();
  expect(visible.textContent).not.toMatch(/SUBMITTED|COMPLETED|q1/);
  expect(screen.getByText("技术详情").closest("details")).not.toBeNull();
  expect(container.querySelector("details pre")?.textContent).toContain("\"task_id\"");
});

it("shows returned submission and report status in Chinese", () => {
  render(<SubmissionEvidence review={{ ...review, sections: [{ ...review.sections[0]!, status: "RETURNED", grading_status: "RETURNED", review_status: "RETURNED" }] }} />);
  expect(screen.getByText("答题状态：已退回 · 评分状态：已退回")).toBeTruthy();
  expect(screen.getByText("报告评审：已退回")).toBeTruthy();
});
