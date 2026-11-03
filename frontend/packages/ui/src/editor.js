import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useCallback, useEffect, useRef } from "react";
const FORMATS = [
    { command: "bold", label: "B", title: "加粗", strong: true },
    { command: "italic", label: "I", title: "斜体" },
    { command: "insertUnorderedList", label: "•", title: "项目符号列表" },
    { command: "formatBlock", value: "h3", label: "H3", title: "小标题" },
    { command: "formatBlock", value: "pre", label: "⟨⟩", title: "代码块" },
];
export function RichTextEditor({ ariaLabel, initialHtml, placeholder, onChange, onDirty, saveStatus, toolbarExtra, }) {
    const editorRef = useRef(null);
    const dirtyRef = useRef(false);
    useEffect(() => {
        if (editorRef.current && !dirtyRef.current) {
            editorRef.current.innerHTML = initialHtml;
        }
    }, [initialHtml]);
    const emit = useCallback(() => {
        dirtyRef.current = true;
        onChange?.(editorRef.current?.innerHTML ?? "");
        onDirty?.();
    }, [onChange, onDirty]);
    const applyFormat = (format) => {
        const editor = editorRef.current;
        if (!editor)
            return;
        editor.focus();
        document.execCommand(format.command, false, format.value ?? undefined);
        emit();
    };
    return (_jsxs("div", { style: { flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }, children: [_jsxs("div", { className: "report-format-toolbar", role: "toolbar", "aria-label": "\u62A5\u544A\u6587\u672C\u683C\u5F0F", children: [FORMATS.map((format) => (_jsx("button", { type: "button", "data-format": format.command, "data-format-value": format.value, "aria-label": format.title, title: format.title, onClick: () => applyFormat(format), children: format.strong
                            ? _jsx("strong", { children: format.label })
                            : _jsx("span", { style: format.command === "italic" ? { fontStyle: "italic" } : undefined, children: format.label }) }, `${format.command}-${format.value ?? ""}`))), _jsx("span", { "aria-hidden": "true" }), _jsxs("div", { className: "report-toolbar-actions", role: "group", "aria-label": "\u62A5\u544A\u7F16\u8F91\u4E0E\u4FDD\u5B58\u64CD\u4F5C", children: [saveStatus, toolbarExtra] })] }), _jsx("div", { className: "report-editor-divider", "aria-hidden": "true" }), _jsx("div", { ref: editorRef, className: "rich-report-editor", role: "textbox", "aria-label": ariaLabel, "aria-multiline": "true", contentEditable: true, tabIndex: 0, "data-placeholder": placeholder, onInput: emit, onBlur: emit, onKeyDown: (event) => {
                    if ((event.ctrlKey || event.metaKey) && event.key === "s") {
                        event.preventDefault();
                        emit();
                    }
                } })] }));
}
