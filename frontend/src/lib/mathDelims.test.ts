import { describe, expect, it } from "vitest";
import { normalizeMathDelims } from "./mathDelims";

describe("normalizeMathDelims", () => {
  it("rewrites \\( \\) to $ and \\[ \\] to $$", () => {
    expect(normalizeMathDelims("a \\(x+1\\) b")).toBe("a $x+1$ b");
    expect(normalizeMathDelims("\\[ y = 2 \\]")).toBe("$$ y = 2 $$");
  });

  it("skips fenced code blocks and tildes", () => {
    const src = "before \\(a\\)\n```\n\\(keep\\)\n```\nafter \\(b\\)";
    expect(normalizeMathDelims(src)).toBe(
      "before $a$\n```\n\\(keep\\)\n```\nafter $b$",
    );
    const tilde = "~~~\n\\(keep\\)\n~~~";
    expect(normalizeMathDelims(tilde)).toBe(tilde);
  });

  it("skips inline code spans", () => {
    expect(normalizeMathDelims("`\\(x\\)` and \\(y\\)")).toBe(
      "`\\(x\\)` and $y$",
    );
  });

  it("leaves unclosed delimiters untouched", () => {
    expect(normalizeMathDelims("open \\( never closed")).toBe(
      "open \\( never closed",
    );
  });

  it("handles multiple spans in one line", () => {
    expect(normalizeMathDelims("\\(a\\) then \\(b\\)")).toBe("$a$ then $b$");
  });
});
