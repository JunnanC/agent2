import { describe, expect, it } from "vitest";
import { effectiveGrade, meanGrade } from "./grades";
describe("original experiment grade", () => {
  it("caps the retake and never lowers the first score", () => {
    expect(effectiveGrade(45, 80)).toBe(60);
    expect(effectiveGrade(55, 40)).toBe(55);
    expect(effectiveGrade(45, 52)).toBe(52);
    expect(effectiveGrade(null, 75)).toBe(60);
  });
  it("keeps ten original assignments in the denominator", () => {
    const scores = Array<number>(10).fill(80);
    scores[2] = effectiveGrade(45, 80);
    expect(meanGrade(scores)).toBe(78);
    expect(meanGrade([80, effectiveGrade(null)])).toBe(40);
    expect(meanGrade([])).toBeNull();
  });
});
