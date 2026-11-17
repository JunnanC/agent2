import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./markdown";

describe("Markdown", () => {
  it("renders headings and tables but strips raw scripts", () => {
    const { container } = render(
      <Markdown source={"## 本章导读\n\n| 阶 | 场景 |\n| --- | --- |\n| O(n) | 遍历 |\n\n<script>alert(1)</script>"} />,
    );

    expect(screen.getByRole("heading", { level: 2, name: "本章导读" })).toBeInTheDocument();
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("renders nothing for empty input", () => {
    const { container } = render(<Markdown source="   " />);
    expect(container).toBeEmptyDOMElement();
  });
});
