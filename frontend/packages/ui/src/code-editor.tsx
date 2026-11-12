import { lazy, Suspense } from "react";
import type { CodeEditorProps } from "./code-editor-impl";

const Editor = lazy(() => import("./code-editor-impl"));

export type { CodeEditorProps } from "./code-editor-impl";

export function CodeEditor(props: CodeEditorProps) {
  return <Suspense fallback={<p role="status">正在载入代码编辑器…</p>}>
    <Editor {...props} />
  </Suspense>;
}
