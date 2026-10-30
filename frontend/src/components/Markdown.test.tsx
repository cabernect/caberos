import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Markdown } from "./Markdown";

describe("Markdown math", () => {
  it("renders \\(...\\) inline math via katex", () => {
    const { container } = render(
      <Markdown>{"First compute \\( 347 \\times 89 \\) then check."}</Markdown>,
    );
    expect(container.querySelector(".katex")).toBeTruthy();
    expect(container.textContent).toContain("First compute");
  });

  it("renders \\[...\\] display math via katex", () => {
    const { container } = render(
      <Markdown>{"\\[ 347 \\times 90 - 347 = 30{,}883 \\]"}</Markdown>,
    );
    expect(container.querySelector(".katex")).toBeTruthy();
  });

  it("still renders $ and $$ math via remark-math", () => {
    const { container } = render(<Markdown>{"sum $a + b$ and $$x^2$$"}</Markdown>);
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(2);
  });

  it("leaves delimiters inside code blocks literal", () => {
    const src = "```\n\\(not math\\)\n```";
    const { container } = render(<Markdown>{src}</Markdown>);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.textContent).toContain("\\(not math\\)");
  });
});
