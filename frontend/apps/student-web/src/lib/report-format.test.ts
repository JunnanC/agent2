import { describe, expect, it } from "vitest";
import { htmlToMarkdown, markdownToHtml } from "./report-format";

describe("markdownToHtml", () => {
  it("空内容返回空串", () => {
    expect(markdownToHtml("")).toBe("");
    expect(markdownToHtml("\n \n")).toBe("");
  });

  it("标题、段落、列表按块渲染", () => {
    const html = markdownToHtml("### 实验目标\n\n请简述目标。\n\n- 项目一\n- 项目二\n\n1. 第一步\n2. 第二步");
    expect(html).toContain("<h3>实验目标</h3>");
    expect(html).toContain("<p>请简述目标。</p>");
    expect(html).toContain("<ul><li>项目一</li><li>项目二</li></ul>");
    expect(html).toContain("<ol><li>第一步</li><li>第二步</li></ol>");
  });

  it("加粗、斜体与行内代码", () => {
    const html = markdownToHtml("**加粗**与*斜体*与`code`");
    expect(html).toBe("<p><strong>加粗</strong>与<em>斜体</em>与<code>code</code></p>");
  });

  it("围栏代码块转 pre", () => {
    const html = markdownToHtml("```\nprint(1)\nprint(2)\n```");
    expect(html).toBe("<pre>print(1)\nprint(2)</pre>");
  });

  it("转义的行首标记按原文字符显示", () => {
    expect(markdownToHtml("\\# 标签")).toBe("<p># 标签</p>");
    expect(markdownToHtml("\\- 项")).toBe("<p>- 项</p>");
    expect(markdownToHtml("\\1. 序号")).toBe("<p>1. 序号</p>");
    expect(markdownToHtml("\\*\\* literal \\*\\*")).toBe("<p>** literal **</p>");
  });
});

describe("htmlToMarkdown", () => {
  it("标题、段落、行内样式", () => {
    const markdown = htmlToMarkdown(
      "<h3>标题</h3><p>段落<b>加粗</b><i>斜体</i><code>x*y</code></p>",
    );
    expect(markdown).toBe("### 标题\n\n段落**加粗***斜体*`x*y`");
  });

  it("列表与围栏代码块", () => {
    const markdown = htmlToMarkdown(
      "<ul><li>项目</li></ul><ol><li>第一步</li><li>第二步</li></ol><pre>code\nline</pre>",
    );
    expect(markdown).toBe("- 项目\n\n1. 第一步\n2. 第二步\n\n```\ncode\nline\n```");
  });

  it("用户手打的 markdown 字符保存时转义", () => {
    const markdown = htmlToMarkdown("<p># 标签</p><p>1. 序号</p><p>- 项</p><p>* 星</p>");
    expect(markdown).toBe("\\# 标签\n\n\\1. 序号\n\n\\- 项\n\n\\* 星");
  });

  it("段内换行与空行", () => {
    const markdown = htmlToMarkdown("<p>上行<br>下行</p><p><br></p><p>尾段</p>");
    expect(markdown).toBe("上行\n下行\n\n尾段");
  });
});

describe("markdown 往返稳定", () => {
  const samples = [
    "### 实验目标与任务\n\n请简述本阶段目标与任务要求。\n\n### 操作过程与关键结果\n\n请记录关键步骤、命令与输出。\n\n### 问题分析与修复方案\n\n请说明定位过程和修复方法。\n\n### 验证结果与总结\n\n请填写验证结果和本阶段结论。",
    "## 标题\n\n第一行\n\n- 步骤一\n- 步骤二\n\n```\ncd workspace\nls\n```\n\n结论:**成功**。",
    "1. 第一步\n2. 第二步\n\n*斜体*与`code`与**加粗**",
  ];

  it.each(samples)("往返后内容一致", (markdown) => {
    expect(htmlToMarkdown(markdownToHtml(markdown))).toBe(markdown);
  });

  it.each(samples)("保存再载入富文本后仍为同一 markdown", (markdown) => {
    const originalHtml = markdownToHtml(markdown);
    expect(htmlToMarkdown(markdownToHtml(htmlToMarkdown(originalHtml)))).toBe(markdown);
  });
});
