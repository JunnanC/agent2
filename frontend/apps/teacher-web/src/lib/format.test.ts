import { expect, it } from "vitest";
import { REVIEW_STATUS_LABEL } from "./format";

it("maps every review status shown in the review list to a business label", () => {
  expect(REVIEW_STATUS_LABEL.DECIDED).toBe("已完成评审");
  expect(REVIEW_STATUS_LABEL.APPROVED).toBe("已通过");
  expect(REVIEW_STATUS_LABEL.RETURNED).toBe("已退回");
});
