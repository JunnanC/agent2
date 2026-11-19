import { CompletionContext } from "@codemirror/autocomplete";
import { python } from "@codemirror/lang-python";
import { EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";
import { completionOptionsFor, completionSourceFor, type Language } from "./index";

const LANGUAGES: Language[] = ["python", "c", "cpp", "java", "go"];

const PREFIX_CASES: Array<[Language, string, string]> = [
  ["python", "sqr", "sqrt"],
  ["c", "pri", "printf"],
  ["cpp", "vec", "vector"],
  ["java", "arra", "ArrayList"],
  ["go", "fmt", "fmt"],
];

function sourceAt(language: Language, doc: string) {
  const state = EditorState.create({ doc });
  return completionSourceFor(language)(new CompletionContext(state, doc.length, false));
}

describe("language completions", () => {
  it.each(LANGUAGES)("%s offers unique completion options", (language) => {
    const options = completionOptionsFor(language);
    expect(options.length).toBeGreaterThan(50);
    expect(new Set(options.map((option) => option.label)).size).toBe(options.length);
  });

  it.each(PREFIX_CASES)("%s completes %s", (language, prefix, expected) => {
    const result = sourceAt(language, prefix) as unknown as {
      options: Array<{ label: string }>;
    } | null;
    expect(result).not.toBeNull();
    expect(result!.options.map((option) => option.label)).toContain(expected);
  });

  it("does not complete inside a comment", () => {
    const doc = "# sqr";
    const state = EditorState.create({ doc, extensions: [python()] });
    const result = completionSourceFor("python")(
      new CompletionContext(state, doc.length, false),
    );
    expect(result).toBeNull();
  });

  it("stays closed in a read-only editor", () => {
    const state = EditorState.create({
      doc: "pri",
      extensions: [EditorState.readOnly.of(true)],
    });
    expect(completionSourceFor("c")(new CompletionContext(state, 3, false))).toBeNull();
  });
});
