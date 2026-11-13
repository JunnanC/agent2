import { expect, it } from "vitest";
import { importErrorText } from "@/lib/import-errors";

it("explains an invalid choice answer in business language", () => {
  expect(importErrorText({ correct_option_ids: "invalid_answer_set" })).toBe("正确答案不在已填写的选项中");
});

it("falls back to a readable explanation for unknown errors", () => {
  expect(importErrorText(undefined)).toBe("导入数据有误");
  expect(importErrorText({ title: "required" })).toBe("title：required");
});
