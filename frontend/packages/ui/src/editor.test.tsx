import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RichTextEditor } from "./editor";

afterEach(cleanup);

it("only reports real changes, so saving then blurring stays saved", () => {
  const onChange = vi.fn(), onDirty = vi.fn();
  render(<RichTextEditor ariaLabel="报告" initialHtml="<p>初稿</p>" onChange={onChange} onDirty={onDirty} />);
  const editor = screen.getByRole("textbox", { name: "报告" });
  fireEvent.blur(editor);
  expect(onChange).not.toHaveBeenCalled();
  editor.innerHTML = "<p>修改后的报告</p>";
  fireEvent.input(editor);
  expect(onChange).toHaveBeenCalledExactlyOnceWith("<p>修改后的报告</p>");
  fireEvent.blur(editor);
  expect(onDirty).toHaveBeenCalledTimes(1);
  editor.innerHTML = "<p>再次修改</p>";
  fireEvent.input(editor);
  expect(onDirty).toHaveBeenCalledTimes(2);
});

it("pastes multiline plain text without injecting HTML and retains line breaks", () => {
  const onChange = vi.fn();
  render(<RichTextEditor ariaLabel="报告" initialHtml="" onChange={onChange} />);
  const editor = screen.getByRole("textbox", { name: "报告" });
  const selection = window.getSelection()!;
  const range = document.createRange();
  range.selectNodeContents(editor);
  selection.removeAllRanges(); selection.addRange(range);
  fireEvent.paste(editor, { clipboardData: { getData: () => "第一段\r\n\r\n<script>text</script>" } });
  expect(editor.querySelectorAll("br")).toHaveLength(2);
  expect(editor.querySelector("script")).toBeNull();
  expect(editor.textContent).toBe("第一段<script>text</script>");
  expect(onChange).toHaveBeenCalledTimes(1);
});
