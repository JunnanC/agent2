import DOMPurify from "dompurify";
import { marked } from "marked";

/** Render trusted course Markdown; raw HTML is sanitized before it reaches the DOM. */
export function Markdown({ source, className }: { source?: string | null; className?: string }) {
  if (!source?.trim()) return null;
  const html = DOMPurify.sanitize(
    marked.parse(source, { async: false, gfm: true, breaks: true }) as string,
    { USE_PROFILES: { html: true } },
  );
  return (
    <div
      className={`markdown-body${className ? ` ${className}` : ""}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
