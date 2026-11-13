import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PreviewBackend } from "@/lib/api";
import { ConfirmProvider } from "@/lib/confirm";
import type { PreviewPayload } from "@/lib/types";
import { OfficePreviewNotice } from "./OfficePreviewNotice";
import { PreviewPanel } from "./PreviewPanel";

function payload(overrides: Partial<PreviewPayload> = {}): PreviewPayload {
  return {
    kind: "slides",
    name: "uploaded.pptx",
    path: "uploaded.pptx",
    size: 100,
    artifact: null,
    slides: [{ title: "Review content", elements: [] }],
    slide_count: 1,
    ...overrides,
  };
}

function backend(preview: PreviewBackend["preview"]): PreviewBackend {
  return {
    preview,
    blob: vi.fn().mockResolvedValue("blob:preview-test"),
    pdfPage: vi.fn().mockResolvedValue("blob:preview-page"),
  };
}

describe("Office preview limitations", () => {
  it.each([
    ["slides", "PowerPoint"],
    ["document", "Word"],
    ["workbook", "Formulas are not calculated here"],
  ] as const)("shows a non-blocking notice for %s while retaining content", async (kind, text) => {
    const be = backend(vi.fn().mockResolvedValue(payload({
      kind,
      mode: "approximate",
      elements: [{ type: "paragraph", text: "Document content" }],
      sheets: [{ name: "Metrics", rows: [["Revenue", 67]], row_count: 1, truncated: false }],
    })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "uploaded.pptx" }} backend={be} />
      </ConfirmProvider>,
    );
    const notice = await screen.findByRole("note", { name: "Office preview limitations" });
    expect(notice).toHaveTextContent("Limited preview.");
    expect(notice).toHaveTextContent(text);
    expect(notice.querySelector("button")).toBeNull();
    expect(screen.getByRole("button", { name: "Expand preview" })).toBeEnabled();
    const content = kind === "slides" ? "Review content" : kind === "document" ? "Document content" : "Revenue";
    expect(screen.getByText(content)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Expand preview" }));
    expect(screen.getByRole("note")).toHaveTextContent(text);
    expect(screen.getByText(content)).toBeVisible();
  });

  it.each([
    "pdf", "image", "markdown", "code", "text", "table", "json", "media", "unknown",
  ] as const)("does not label %s as an Office preview", (kind) => {
    const { container } = render(<OfficePreviewNotice kind={kind} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("stays silent unless the payload declares approximate fidelity", () => {
    for (const mode of [undefined, "content", "native"] as const) {
      const { container } = render(<OfficePreviewNotice kind="slides" mode={mode} />);
      expect(container).toBeEmptyDOMElement();
    }
    const { container } = render(<OfficePreviewNotice kind="code" mode="approximate" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("updates the notice on source changes and removes it for non-Office content", async () => {
    const be = backend(vi.fn(async (source) => source.path === "notes.md"
      ? payload({ kind: "markdown", name: "notes.md", path: "notes.md", content: "Current notes" })
      : source.path === "report.docx"
        ? payload({ kind: "document", name: "report.docx", mode: "approximate", elements: [] })
        : payload({ mode: "approximate" })));
    const view = (path: string) => (
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path }} backend={be} />
      </ConfirmProvider>
    );
    const { rerender } = render(view("uploaded.pptx"));
    expect(await screen.findByRole("note")).toHaveTextContent("PowerPoint");
    rerender(view("report.docx"));
    await waitFor(() => expect(screen.getByRole("note")).toHaveTextContent("Word"));
    rerender(view("notes.md"));
    expect(await screen.findByText("Current notes")).toBeVisible();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("shows parse errors without presenting them as a limited successful preview", async () => {
    const be = backend(vi.fn().mockResolvedValue(payload({
      error: "Presentation unreadable", slides: [],
    })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "broken.pptx" }} backend={be} />
      </ConfirmProvider>,
    );
    expect(await screen.findByText("Presentation unreadable")).toBeVisible();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
