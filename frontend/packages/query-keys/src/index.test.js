import { describe, expect, it } from "vitest";
import { keys } from "./index";
describe("query-keys", () => {
    it("筛选参数参与键并保持稳定顺序", () => {
        expect(keys.tasks({ status: "IN_PROGRESS", courseId: "c1" }))
            .toEqual(keys.tasks({ courseId: "c1", status: "IN_PROGRESS" }));
    });
    it("空值与空字符串不参与键", () => {
        expect(keys.tasks({ status: null, q: "" })).toEqual(keys.tasks());
    });
    it("不同筛选得到不同键", () => {
        expect(keys.tasks({ status: "IN_PROGRESS" })).not.toEqual(keys.tasks({ status: "FAILED" }));
    });
    it("资源键包含 id 与资源名", () => {
        expect(keys.courseResource("course-1", "chapters")).toEqual(["courses", "course-1", "chapters"]);
        expect(keys.task("task-1")).toEqual(["tasks", "task-1"]);
        expect(keys.teachingAnalytics("course-1", "overview")).toEqual(["teaching-analytics", "course-1", "overview"]);
    });
});
