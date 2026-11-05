import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageActions } from "./MessageActions";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function mockClipboard(writeText = vi.fn().mockResolvedValue(undefined)) {
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  return writeText;
}

describe("MessageActions", () => {
  it("copies the entire original reply, including Markdown, code, and links", async () => {
    const writeText = mockClipboard();
    const content = "# Answer\n\n**Details**\n\n```ts\nconst n = 1;\n```\n\n[Image](artifacts/image.png)\n\nLast paragraph.";
    render(<MessageActions content={content} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));

    expect(writeText).toHaveBeenCalledWith(content);
    await screen.findByRole("button", { name: "Copied" });
    expect(screen.getByRole("status").textContent).toBe("Message copied");
  });

  it("resets success feedback so the message can be copied again", async () => {
    vi.useFakeTimers();
    mockClipboard();
    render(<MessageActions content="Reply" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    });
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByRole("button", { name: "Copy message" })).toBeTruthy();
  });

  it("copies user input exactly, preserving whitespace and line breaks", async () => {
    const writeText = mockClipboard();
    const content = "  Please edit this:\n\nfirst line\n  indented line\n";
    render(<MessageActions content={content} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(writeText).toHaveBeenCalledWith(content);
  });

  it("reports clipboard denial without falsely claiming success and allows retry", async () => {
    const writeText = mockClipboard(vi.fn().mockRejectedValue(new Error("Denied")));
    render(<MessageActions content="Reply" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn't copy"));
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();

    writeText.mockResolvedValue(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await screen.findByRole("button", { name: "Copied" });
  });

  it("handles an unavailable clipboard API", async () => {
    vi.stubGlobal("navigator", {});
    render(<MessageActions content="Reply" />);
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Couldn't copy"));
  });

  it("does not offer copying for an empty reply", () => {
    render(<MessageActions content={" \n "} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
