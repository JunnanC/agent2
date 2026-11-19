export interface CompletionEntry {
  label: string;
  detail?: string;
  type?: "keyword" | "function" | "class" | "constant" | "variable" | "text";
}

export interface SnippetEntry {
  label: string;
  template: string;
  detail?: string;
}

export interface LanguageCompletions {
  keywords: string[];
  builtins: CompletionEntry[];
  snippets: SnippetEntry[];
}
