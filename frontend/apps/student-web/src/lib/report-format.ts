/* 学生报告编辑器(contentEditable 富文本)与后端存储字段 body_markdown 的双向转换。
   编辑器只支持标题、段落、换行、有序/无序列表、加粗、斜体、行内代码与围栏代码块;
   其余标签降级为其中文本内容,保证保存时不丢失内容。 */

const HTML_ESCAPE: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
const LINE_START_PATTERN = /^(\s*)(#{1,6}|[-*+]|\d+(?:\.\d+)*[.)])(?=\s)/;

function escapeHtml(text: string): string {
  return text.replace(/[&<>]/g, (char) => HTML_ESCAPE[char] ?? char);
}

function escapeInlineMarkdown(text: string): string {
  return text
    .replace(/\u00a0/g, " ")
    .replace(/\u200b/g, "")
    .replace(/[\\`*]/g, "\\$&");
}

function escapeLineStart(line: string): string {
  return line.replace(LINE_START_PATTERN, "$1\\$2");
}

function inlineContent(element: HTMLElement): string {
  return Array.from(element.childNodes).map(inlineToMarkdown).join("");
}

function allParagraphText(text: string): string {
  return text.split("\n").map(escapeLineStart).join("\n").trim();
}

/* 行内还原:先隔离 `code` 与已转义字符(含行首结构标记),再解析强调结构,最后还原 token */
function renderInline(markdown: string): string {
  const tokens: string[] = [];
  let html = markdown.replace(/`([^`]+)`/g, (_match, code: string) => {
    tokens.push(`<code>${escapeHtml(code)}</code>`);
    return `\u0000${tokens.length - 1}\u0000`;
  });
  html = html.replace(/\\([\\`*\-+#]|\d)/g, (_match, char: string) => {
    tokens.push(escapeHtml(char));
    return `\u0000${tokens.length - 1}\u0000`;
  });
  html = escapeHtml(html);
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
  return html.replace(/\u0000(\d+)\u0000/g, (_m, index: string) => tokens[Number(index)] ?? "");
}

export function markdownToHtml(markdown: string): string {
  if (!markdown.trim()) return "";
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const blocks: string[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let fence: string[] | null = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push(`<p>${paragraph.join("<br>")}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    const tag = list.ordered ? "ol" : "ul";
    blocks.push(`<${tag}>${list.items.map((item) => `<li>${item}</li>`).join("")}</${tag}>`);
    list = null;
  };

  for (const line of lines) {
    if (fence != null) {
      if (!line.trim().startsWith("```")) {
        fence.push(line);
        continue;
      }
      blocks.push(`<pre>${escapeHtml(fence.join("\n"))}</pre>`);
      fence = null;
      continue;
    }
    if (line.trim().startsWith("```")) {
      flushParagraph();
      flushList();
      fence = [];
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+(?:\.\d+)*[.)]\s+(.+)$/);
    const content = heading != null
      ? renderInline((heading[2] ?? "").trim())
      : renderInline((ordered ?? unordered)?.[1]?.trim() ?? line.trim());
    if (heading != null) {
      flushParagraph();
      flushList();
      const level = (heading[1] ?? "###").length;
      blocks.push(`<h${level}>${content}</h${level}>`);
      continue;
    }
    if (unordered != null || ordered != null) {
      flushParagraph();
      const wantOrdered = ordered != null;
      if (list == null) {
        list = { ordered: wantOrdered, items: [content] };
      } else if (list.ordered !== wantOrdered) {
        flushList();
        list = { ordered: wantOrdered, items: [content] };
      } else {
        list.items.push(content);
      }
      continue;
    }
    paragraph.push(content);
  }
  if (fence != null) blocks.push(`<pre>${escapeHtml(fence.join("\n"))}</pre>`);
  flushParagraph();
  flushList();
  return blocks.join("\n");
}

function inlineToMarkdown(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    const text = (node.nodeValue ?? "").replace(/[\t\r\n]/g, " ");
    if (!/\S/.test(text)) return text.includes(" ") ? " " : "";
    return escapeInlineMarkdown(text);
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const element = node as HTMLElement;
  switch (element.tagName) {
    case "BR":
      return "\n";
    case "B":
    case "STRONG": {
      const content = inlineContent(element).trim();
      return content ? `**${content}**` : "";
    }
    case "I":
    case "EM": {
      const content = inlineContent(element).trim();
      return content ? `*${content}*` : "";
    }
    case "CODE":
      return `\`${element.textContent ?? ""}\``;
    case "SCRIPT":
    case "STYLE":
    case "IMG":
    case "INPUT":
      return "";
    default:
      return inlineContent(element);
  }
}

function serializeBlocks(container: Node, blocks: string[]): void {
  let buffer: string[] = [];
  const flushParagraph = () => {
    if (!buffer.length) return;
    const text = buffer.join("");
    buffer = [];
    const paragraph = allParagraphText(text);
    if (paragraph) blocks.push(paragraph);
  };
  for (const node of Array.from(container.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.nodeValue ?? "").replace(/[\t\r\n]/g, " ");
      if (text.trim()) buffer.push(escapeInlineMarkdown(text));
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;
    const element = node as HTMLElement;
    switch (element.tagName) {
      case "BR":
        buffer.push("\n");
        continue;
      case "H1":
      case "H2":
      case "H3":
      case "H4":
      case "H5":
      case "H6":
        flushParagraph();
        blocks.push(`${"#".repeat(Number(element.tagName.slice(1)))} ${inlineContent(element).trim().split("\n").join(" ")}`);
        continue;
      case "P": {
        flushParagraph();
        const paragraph = allParagraphText(inlineContent(element));
        if (paragraph) blocks.push(paragraph);
        continue;
      }
      case "DIV": {
        flushParagraph();
        const nested = element.querySelector("p,div,ul,ol,pre,h1,h2,h3,h4,h5,h6,table") != null;
        if (nested) {
          serializeBlocks(element, blocks);
        } else {
          const paragraph = allParagraphText(inlineContent(element));
          if (paragraph) blocks.push(paragraph);
        }
        continue;
      }
      case "UL":
      case "OL": {
        flushParagraph();
        const list = Array.from(element.children)
          .filter((child) => child.tagName === "LI")
          .map((child, index) => {
            const marker = element.tagName === "OL" ? `${index + 1}. ` : "- ";
            return marker + inlineContent(child as HTMLElement).split("\n").join(" ");
          })
          .join("\n");
        if (list.trim()) blocks.push(list);
        continue;
      }
      case "PRE":
        flushParagraph();
        blocks.push(`\`\`\`\n${(element.textContent ?? "").replace(/\n+$/, "")}\n\`\`\``);
        continue;
      case "TABLE":
      case "BLOCKQUOTE":
      case "SECTION":
      case "ARTICLE": {
        flushParagraph();
        if (element.querySelector("p,div,ul,ol,pre,h1,h2,h3,h4,h5,h6,table") != null) {
          serializeBlocks(element, blocks);
        } else {
          const paragraph = allParagraphText(inlineContent(element));
          if (paragraph) blocks.push(paragraph);
        }
        continue;
      }
      default:
        buffer.push(inlineToMarkdown(element));
        continue;
    }
  }
  flushParagraph();
}

export function htmlToMarkdown(html: string): string {
  if (!html.trim()) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  const blocks: string[] = [];
  serializeBlocks(doc.body, blocks);
  return blocks.join("\n\n").trim();
}
