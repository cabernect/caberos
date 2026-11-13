import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe("W4 preview experience", () => {
  it("ignores a late failure from a previous source", async () => {
    let rejectA!: (e: Error) => void;
    const be = backend(vi.fn((source: { path?: string }) =>
      source.path === "a.md"
        ? new Promise<PreviewPayload>((_, rej) => { rejectA = rej; })
        : Promise.resolve(payload({ kind: "markdown", name: "b.md", path: "b.md", content: "Beta body" })),
    ));
    const view = (path: string) => (
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path }} backend={be} />
      </ConfirmProvider>
    );
    const { rerender } = render(view("a.md"));
    rerender(view("b.md"));
    expect(await screen.findByText("Beta body")).toBeVisible();
    rejectA(new Error("a.md exploded"));
    await waitFor(() => expect(screen.queryByText("a.md exploded")).not.toBeInTheDocument());
    expect(screen.getByText("Beta body")).toBeVisible();
  });

  it("navigates slides with buttons, counter, and arrow keys", async () => {
    const be = backend(vi.fn().mockResolvedValue(payload({
      path: "deck-nav.pptx",
      slides: [
        { title: "One", elements: [] },
        { title: "Two", elements: [] },
        { title: "Three", elements: [] },
      ],
      slide_count: 3,
    })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "deck-nav.pptx" }} backend={be} />
      </ConfirmProvider>,
    );
    expect(await screen.findByText("1 / 3")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next slide" }));
    expect(await screen.findByText("2 / 3")).toBeVisible();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(await screen.findByText("3 / 3")).toBeVisible();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(await screen.findByText("2 / 3")).toBeVisible();
    expect(screen.getByRole("button", { name: "Previous slide" })).toBeEnabled();
  });

  it("prefills an editable revise draft with artifact, revision, and focus", async () => {
    const onRevise = vi.fn();
    const be = backend(vi.fn().mockResolvedValue(payload({
      path: "deck-revise.pptx",
      artifact: {
        id: "art-1", format: "pptx", tracking_status: "tracked",
        current_path: "deck.pptx", current_revision_id: "rev-9",
        current_revision_number: 9, revision_count: 9,
        viewing_revision_id: null, viewing_revision_number: null,
        newer_exists: false,
      },
      slides: [
        { title: "One", elements: [] },
        { title: "Two", elements: [] },
      ],
      slide_count: 2,
    })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "deck-revise.pptx" }} backend={be} onRevise={onRevise} />
      </ConfirmProvider>,
    );
    await screen.findByRole("button", { name: "Revise" });
    // Flush the renderer's focus-reporting effect before clicking —
    // in the app this always lands before the user can click.
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Revise" }));
    expect(onRevise).toHaveBeenCalledTimes(1);
    const draft = onRevise.mock.calls[0][0] as string;
    expect(draft).toContain("art-1");
    expect(draft).toContain("rev-9");
    expect(draft).toContain("slide 1 of 2");
    expect(draft).toContain("Changes:");
  });

  it("restores slide position and zoom per source, not globally", async () => {
    const be = backend(vi.fn().mockResolvedValue(payload({
      path: "deck-persist.pptx",
      slides: [
        { title: "One", elements: [] },
        { title: "Two", elements: [] },
        { title: "Three", elements: [] },
      ],
      slide_count: 3,
    })));
    const view = () => (
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "deck-persist.pptx" }} backend={be} />
      </ConfirmProvider>
    );
    const first = render(view());
    fireEvent.click(await screen.findByRole("button", { name: "Next slide" }));
    expect(await screen.findByText("2 / 3")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(await screen.findByText("125%")).toBeVisible();
    first.unmount();
    render(view());
    expect(await screen.findByText("2 / 3")).toBeVisible();
    expect(screen.getByText("125%")).toBeVisible();
  });
});

describe("isolated deck playback", () => {
  it("renders an admitted deck in a scripts-only sandboxed iframe", async () => {
    const be: PreviewBackend = {
      ...backend(vi.fn().mockResolvedValue(
        payload({
          kind: "deck",
          name: "deck.html",
          path: "deck.html",
          deck: { runtime: "deck-rt2", title: "Review", slides: 3 },
        }),
      )),
      deckUrl: vi.fn().mockResolvedValue("/api/agents/a1/workspace/deck?path=deck.html"),
    };
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="a1" source={{ path: "deck.html" }} backend={be} />
      </ConfirmProvider>,
    );
    const frame = await screen.findByTitle("Review");
    expect(frame.tagName).toBe("IFRAME");
    // allow-scripts ONLY — never allow-same-origin: deck JS gets an opaque
    // origin with no access to app cookies, storage, or DOM.
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("sandbox")).not.toContain("allow-same-origin");
    expect(frame.getAttribute("src")).toContain("/workspace/deck");
    // Platform chrome shows position fallback from admission metadata.
    expect(await screen.findByText("1 / 3")).toBeVisible();
  });

  it("shows an honest notice when the surface can't play decks", async () => {
    const be = backend(vi.fn().mockResolvedValue(
      payload({
        kind: "deck",
        name: "deck.html",
        path: "deck.html",
        deck: { runtime: "deck-rt2", slides: 2 },
      }),
    ));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "deck.html" }} backend={be} />
      </ConfirmProvider>,
    );
    expect(
      await screen.findByText(/playback isn't available/i),
    ).toBeVisible();
  });
});
