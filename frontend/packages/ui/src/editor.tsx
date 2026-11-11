import { useCallback, useEffect, useRef } from "react";
import type { ReactNode } from "react";

export interface RichTextEditorProps {
  ariaLabel: string;
  /** 初始 HTML 内容（初始化注入而非持续受控，防止光标抖动） */
  initialHtml: string;
  placeholder?: string;
  onChange?: (html: string) => void;
  onDirty?: () => void;
  saveStatus?: ReactNode;
  toolbarExtra?: ReactNode;
}

const FORMATS: Array<{ command: string; value?: string; label: string; title: string; strong?: boolean }> = [
  { command: "bold", label: "B", title: "加粗", strong: true },
  { command: "italic", label: "I", title: "斜体" },
  { command: "insertUnorderedList", label: "•", title: "项目符号列表" },
  { command: "formatBlock", value: "h3", label: "H3", title: "小标题" },
  { command: "formatBlock", value: "pre", label: "⟨⟩", title: "代码块" },
];

export function RichTextEditor({
  ariaLabel, initialHtml, placeholder, onChange, onDirty, saveStatus, toolbarExtra,
}: RichTextEditorProps) {
  const editorRef = useRef<HTMLDivElement>(null);
  const dirtyRef = useRef(false);
  const lastHtmlRef = useRef(initialHtml);

  useEffect(() => {
    if (editorRef.current && !dirtyRef.current) {
      editorRef.current.innerHTML = initialHtml;
      lastHtmlRef.current = editorRef.current.innerHTML;
    }
  }, [initialHtml]);

  const emit = useCallback(() => {
    const html = editorRef.current?.innerHTML ?? "";
    if (html === lastHtmlRef.current) return;
    lastHtmlRef.current = html;
    dirtyRef.current = true;
    onChange?.(html);
    onDirty?.();
  }, [onChange, onDirty]);

  const applyFormat = (format: (typeof FORMATS)[number]) => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.focus();
    document.execCommand(format.command, false, format.value ?? undefined);
    emit();
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div className="report-format-toolbar" role="toolbar" aria-label="报告文本格式">
        {FORMATS.map((format) => (
          <button key={`${format.command}-${format.value ?? ""}`} type="button"
            data-format={format.command} data-format-value={format.value}
            aria-label={format.title} title={format.title}
            onClick={() => applyFormat(format)}>
            {format.strong
              ? <strong>{format.label}</strong>
              : <span style={format.command === "italic" ? { fontStyle: "italic" } : undefined}>{format.label}</span>}
          </button>
        ))}
        <span aria-hidden="true" />
        <div className="report-toolbar-actions" role="group" aria-label="报告编辑与保存操作">
          {saveStatus}
          {toolbarExtra}
        </div>
      </div>
      <div className="report-editor-divider" aria-hidden="true" />
      <div ref={editorRef} className="rich-report-editor" role="textbox" aria-label={ariaLabel}
        aria-multiline="true" contentEditable tabIndex={0} data-placeholder={placeholder}
        onInput={emit} onBlur={emit}
        onPaste={(event) => {
          event.preventDefault();
          const text = event.clipboardData.getData("text/plain");
          const selection = window.getSelection();
          if (!selection?.rangeCount) return;
          const range = selection.getRangeAt(0);
          if (!editorRef.current?.contains(range.commonAncestorContainer)) return;
          range.deleteContents();
          const fragment = document.createDocumentFragment();
          text.replace(/\r\n?/g, "\n").split("\n").forEach((line, index) => {
            if (index) fragment.append(document.createElement("br"));
            fragment.append(document.createTextNode(line));
          });
          const last = fragment.lastChild;
          range.insertNode(fragment);
          if (last) { range.setStartAfter(last); range.collapse(true); selection.removeAllRanges(); selection.addRange(range); }
          emit();
        }}
        onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key === "s") {
            event.preventDefault();
            emit();
          }
        }} />
    </div>
  );
}
