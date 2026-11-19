import { expect, it } from "vitest";
import { precheckFailureMessage } from "./precheck-errors";

it("identifies which runtime settings to save when programming configuration is missing", () => {
  expect(precheckFailureMessage({
    error_code: "TEMPLATE_VALIDATION_ERROR",
    error_detail: { runtime: "programming_runtime_required" },
  })).toContain("缺少判题环境配置");
});

it("keeps unknown error codes diagnosable and handles missing details", () => {
  expect(precheckFailureMessage({ error_code: "PRECHECK_NEW_ERROR" })).toContain("PRECHECK_NEW_ERROR");
  expect(precheckFailureMessage({})).toContain("服务端未返回具体失败原因");
});
