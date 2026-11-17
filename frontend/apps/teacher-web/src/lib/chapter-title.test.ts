import { expect, it } from "vitest";
import { chapterLabel, chapterName, chapterTitle } from "./chapter-title";

it.each([[1, "第一章"], [4, "第四章"], [10, "第十章"], [11, "第十一章"], [20, "第二十章"], [101, "第一百零一章"], [1001, "第一千零一章"], [10000, "第10000章"]])("formats chapter %i", (number, label) => {
  expect(chapterLabel(Number(number))).toBe(label);
});
it("keeps the editable name free of legacy prefixes and avoids duplicate numbering", () => {
  expect(chapterName("第三章 云教学实验")).toBe("云教学实验");
  expect(chapterName("第3章：云教学实验")).toBe("云教学实验");
  expect(chapterName("云教学实验")).toBe("云教学实验");
  expect(chapterTitle(4, "云教学实验")).toBe("第四章 云教学实验");
  expect(chapterTitle(4, "第三章 云教学实验")).toBe("第四章 云教学实验");
});
