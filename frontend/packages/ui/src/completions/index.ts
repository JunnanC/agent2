import {
  completeAnyWord,
  snippetCompletion,
  type Completion,
  type CompletionResult,
  type CompletionSource,
} from "@codemirror/autocomplete";
import { syntaxTree } from "@codemirror/language";

import { c } from "./c";
import { cpp } from "./cpp";
import { go } from "./go";
import { java } from "./java";
import { python } from "./python";
import type { LanguageCompletions } from "./types";

export type Language = "python" | "c" | "cpp" | "java" | "go";

const DATA: Record<Language, LanguageCompletions> = { python, c, cpp, java, go };
const OPTION_CACHE = new Map<Language, Completion[]>();
const WORD = /[\w$]+/;
const VALID_FOR = /^[\w$]*$/;

export function completionOptionsFor(language: Language): Completion[] {
  const cached = OPTION_CACHE.get(language);
  if (cached) return cached;
  const data = DATA[language];
  const merged = new Map<string, Completion>();
  for (const keyword of data.keywords) {
    merged.set(keyword, { label: keyword, type: "keyword" });
  }
  for (const entry of data.builtins) {
    if (merged.has(entry.label)) continue;
    merged.set(entry.label, {
      label: entry.label,
      detail: entry.detail,
      type: entry.type ?? "function",
    });
  }
  for (const snippet of data.snippets) {
    if (merged.has(snippet.label)) continue;
    merged.set(
      snippet.label,
      snippetCompletion(snippet.template, {
        label: snippet.label,
        detail: snippet.detail ?? "代码模板",
        type: "text",
      }),
    );
  }
  const options = [...merged.values()];
  OPTION_CACHE.set(language, options);
  return options;
}

/** 关键字/标准库/模板补全：注释与字符串内不弹，只读编辑器不弹。 */
export function completionSourceFor(language: Language): CompletionSource {
  const options = completionOptionsFor(language);
  return (context) => {
    if (context.state.readOnly) return null;
    const word = context.matchBefore(WORD);
    if (!word || (word.from === word.to && !context.explicit)) return null;
    const tree = syntaxTree(context.state);
    let node = tree.resolveInner(context.pos, -1);
    for (;;) {
      if (/Comment|String/.test(node.name)) return null;
      const parent = node.parent;
      if (!parent) break;
      node = parent;
    }
    const prefix = context.state.sliceDoc(word.from, word.to).toLowerCase();
    const matches = options.filter((option) =>
      option.label.toLowerCase().startsWith(prefix),
    );
    if (!matches.length) return null;
    const result: CompletionResult = { from: word.from, options: matches, validFor: VALID_FOR };
    return result;
  };
}

/** 语言数据：自己的词库 + 文档内已出现的标识符。 */
export function completionDataFor(language: Language): { autocomplete: CompletionSource }[] {
  return [
    { autocomplete: completionSourceFor(language) },
    { autocomplete: completeAnyWord },
  ];
}
