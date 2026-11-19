import { useEffect, useRef } from "react";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { indentWithTab } from "@codemirror/commands";
import { StreamLanguage } from "@codemirror/language";
import { python } from "@codemirror/lang-python";
import { cpp } from "@codemirror/lang-cpp";
import { java } from "@codemirror/lang-java";
import { go } from "@codemirror/legacy-modes/mode/go";
import { basicSetup } from "codemirror";
import { completionDataFor } from "./completions";

export interface CodeEditorProps {
  value: string;
  language: "python" | "c" | "cpp" | "java" | "go";
  onChange: (value: string) => void;
  readOnly?: boolean;
  ariaLabel?: string;
}

export default function CodeEditor({ value, language, onChange, readOnly = false, ariaLabel = "代码编辑器" }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<EditorView | null>(null);
  const changeHandler = useRef(onChange);
  const initialValue = useRef(value);
  const replacing = useRef(false);
  useEffect(() => { changeHandler.current = onChange; }, [onChange]);
  useEffect(() => { initialValue.current = value; }, [value]);

  useEffect(() => {
    if (!host.current) return;
    const syntax = language === "python" ? python() : language === "java" ? java()
      : language === "go" ? StreamLanguage.define(go) : cpp();
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: initialValue.current,
        extensions: [basicSetup, syntax, keymap.of([indentWithTab]),
          EditorState.languageData.of(() => completionDataFor(language)),
          EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
          EditorView.theme({
            "&": { height: "100%", minHeight: "360px", fontSize: "14px" },
            ".cm-scroller": { overflow: "auto", fontFamily: "Consolas, monospace" },
          }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !replacing.current) changeHandler.current(update.state.doc.toString());
          }),
        ],
      }),
    });
    editor.current = view;
    return () => { editor.current = null; view.destroy(); };
  }, [language, readOnly, ariaLabel]);

  useEffect(() => {
    const view = editor.current;
    if (view && view.state.doc.toString() !== value) {
      replacing.current = true;
      try { view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } }); }
      finally { replacing.current = false; }
    }
  }, [value]);

  return <div ref={host} style={{ height: "100%", minWidth: 0 }} />;
}
