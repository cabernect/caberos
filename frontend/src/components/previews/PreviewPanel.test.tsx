import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  it("separates speaker notes from slide content and resets notes when navigating", async () => {
    const be = backend(vi.fn().mockResolvedValue(payload({
      path: "notes-preview.pptx",
      slide_width: 1280,
      slide_height: 720,
      slides: [
        { title: "First slide", elements: [
          { type: "paragraph", text: "Visible body" },
          { type: "notes", text: "Private presenter reminder" },
        ] },
        { title: "Second slide", elements: [{ type: "notes", text: "Second reminder" }] },
      ],
    })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "notes-preview.pptx" }} backend={be} />
      </ConfirmProvider>,
    );
    const body = await screen.findByRole("region", { name: "Slide 1 content" });
    expect(body).toHaveStyle({ aspectRatio: "1280 / 720" });
    expect(body).toHaveTextContent("Visible body");
    expect(body).not.toHaveTextContent("Private presenter reminder");
    const notes = screen.getByText("Speaker notes").closest("details")!;
    expect(notes).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Speaker notes"));
    expect(notes).toHaveAttribute("open");
    expect(screen.getByText("Private presenter reminder")).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Go to slide" }), { target: { value: "1" } });
    expect(screen.getByRole("region", { name: "Slide 2 content" })).toHaveTextContent("No extractable body content");
    expect(screen.getByRole("region", { name: "Slide 2 content" })).toHaveStyle({ aspectRatio: "1280 / 720" });
    expect(screen.getByText("Speaker notes").closest("details")).not.toHaveAttribute("open");
    expect(screen.queryByText("Private presenter reminder")).not.toBeInTheDocument();
  });

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

describe("static HTML preview", () => {
  it("renders ordinary HTML in a no-scripts sandbox with a source toggle, not slide controls", async () => {
    const source = "<h1>Long report</h1>";
    const be = backend(vi.fn().mockResolvedValue(payload({
      kind: "html", name: "report.html", path: "report.html",
      content: source, html_document: source,
    })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "report.html" }} backend={be} />
      </ConfirmProvider>,
    );
    const frame = await screen.findByTitle("HTML preview: report.html");
    expect(frame).toHaveAttribute("sandbox", "");
    expect(frame).toHaveAttribute("srcdoc", source);
    expect(screen.queryByRole("button", { name: "Next slide" })).not.toBeInTheDocument();
    expect(screen.getByText(/Scripts, links, forms/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.queryByTitle("HTML preview: report.html")).not.toBeInTheDocument();
    expect(screen.getByText(source)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Rendered" }));
    expect(screen.getByTitle("HTML preview: report.html")).toHaveAttribute("sandbox", "");
  });

  it("does not render truncated HTML as a complete document", async () => {
    const be = backend(vi.fn().mockResolvedValue(payload({
      kind: "html", name: "huge.html", content: "<p>partial", truncated: true,
    })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "huge.html" }} backend={be} />
      </ConfirmProvider>,
    );
    expect(await screen.findByRole("button", { name: "Rendered" })).toBeDisabled();
    expect(screen.getByText(/Preview truncated/)).toBeVisible();
    expect(screen.queryByTitle("HTML preview: huge.html")).not.toBeInTheDocument();
  });
});

describe("presentation spec decks", () => {
  const deckPayload = (overrides: Partial<PreviewPayload> = {}) =>
    payload({
      kind: "deck",
      name: "review.deck.json",
      path: "review.deck.json",
      spec: {
        kind: "deck",
        version: 1,
        title: "Review",
        theme: { background: "#ffffff", accent: "#315c73", text: "#202a31", font: "sans" },
        slides: [
          { id: "s1", layout: "title", title: "Quarterly Review", blocks: [] },
          {
            id: "s2",
            title: "Highlights",
            blocks: [
              { type: "bullets", items: ["Revenue up", "Costs flat"] },
              { type: "paragraph", text: "Details inside." },
            ],
          },
        ],
      },
      source: { kind: "live_file", artifact_id: null, revision_id: null, sha256: "exact-hash" },
      ...overrides,
    });

  it("renders spec slides directly with navigation — no iframe", async () => {
    const be = backend(vi.fn().mockResolvedValue(deckPayload()));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "review.deck.json" }} backend={be} />
      </ConfirmProvider>,
    );
    expect(await screen.findByText("Quarterly Review")).toBeVisible();
    expect(screen.getByText("1 / 2")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next slide" }));
    expect(await screen.findByText("Highlights")).toBeVisible();
    expect(screen.getByText("Revenue up")).toBeVisible();
    expect(screen.getByText("2 / 2")).toBeVisible();
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("exports native PPTX pinned to the previewed source hash", async () => {
    const exportDeckPptx = vi.fn().mockResolvedValue(undefined);
    const source = { path: "review.deck.json" };
    const be: PreviewBackend = {
      ...backend(vi.fn().mockResolvedValue(deckPayload())),
      exportDeckPptx,
    };
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={source} backend={be} />
      </ConfirmProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Export PPTX" }));
    await waitFor(() =>
      expect(exportDeckPptx).toHaveBeenCalledWith(source, "review.pptx", "exact-hash"),
    );
  });

  it("reveals bullets and blocks before advancing and reverses reveals on Back", async () => {
    const be = backend(vi.fn().mockResolvedValue(deckPayload({
      spec: { slides: [
        { id: "a", title: "Reveal slide", blocks: [
          { type: "bullets", items: ["First point", "Second point"], reveal: "items" },
          { type: "paragraph", text: "Closing thought", reveal: true },
        ] },
        { id: "b", title: "Next page", blocks: [] },
      ] },
    })));
    render(<ConfirmProvider><PreviewPanel agentId="" source={{ path: "motion.deck.json" }} backend={be} /></ConfirmProvider>);
    expect(await screen.findByText("First point")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Slideshow" }));
    const player = within(screen.getByRole("dialog"));
    expect(player.getByText("First point")).not.toBeVisible();
    fireEvent.click(player.getByRole("button", { name: "Advance presentation" }));
    expect(player.getByText("First point")).toBeVisible();
    expect(player.getByText("Second point")).not.toBeVisible();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(player.getByText("Closing thought")).toBeVisible();
    expect(player.getByText("1 / 2")).toBeVisible();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(player.getByText("Next page")).toBeVisible();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(player.getByText("Closing thought")).toBeVisible();
    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(player.getByText("Closing thought")).not.toBeVisible();
  });

  it("shows every reveal immediately with reduced motion", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    try {
      const be = backend(vi.fn().mockResolvedValue(deckPayload({ spec: { slides: [
        { id: "a", title: "Reduced", blocks: [{ type: "paragraph", text: "Already visible", reveal: true }] },
        { id: "b", title: "Destination" },
      ] } })));
      render(<ConfirmProvider><PreviewPanel agentId="" source={{ path: "reduced.deck.json" }} backend={be} /></ConfirmProvider>);
      fireEvent.click(await screen.findByRole("button", { name: "Slideshow" }));
      const player = within(screen.getByRole("dialog"));
      expect(player.getByText("Already visible")).toBeVisible();
      fireEvent.keyDown(window, { key: "ArrowRight" });
      expect(player.getByText("Destination")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("reveals a whole bullet block together without leaking nested visibility", async () => {
    const be = backend(vi.fn().mockResolvedValue(deckPayload({ spec: { slides: [
      { id: "group", blocks: [{ type: "bullets", items: ["Grouped one", "Grouped two"], reveal: true }] },
    ] } })));
    render(<ConfirmProvider><PreviewPanel agentId="" source={{ path: "group.deck.json" }} backend={be} /></ConfirmProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Slideshow" }));
    const player = within(screen.getByRole("dialog"));
    expect(getComputedStyle(player.getByText("Grouped one")).visibility).toBe("hidden");
    expect(getComputedStyle(player.getByText("Grouped two")).visibility).toBe("hidden");
    fireEvent.click(player.getByRole("button", { name: "Advance presentation" }));
    expect(player.getByText("Grouped one")).toBeVisible();
    expect(player.getByText("Grouped two")).toBeVisible();
    expect(player.getByRole("button", { name: "Next slide" })).toBeDisabled();
  });

  it("presents from the current slide and exits without closing the preview when fullscreen is unavailable", async () => {
    const onClose = vi.fn();
    const be = backend(vi.fn().mockResolvedValue(deckPayload()));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "review.deck.json" }} backend={be} onClose={onClose} />
      </ConfirmProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Next slide" }));
    fireEvent.click(screen.getByRole("button", { name: "Expand preview" }));
    const start = screen.getByRole("button", { name: "Slideshow" });
    start.focus();
    fireEvent.click(start);
    const dialog = screen.getByRole("dialog", { name: "Presentation slideshow" });
    expect(within(dialog).getByText("Highlights")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Next slide" })).toBeDisabled();
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(window, { key: "Home" });
    expect(within(dialog).getByText("Quarterly Review")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Previous slide" })).toBeDisabled();
    fireEvent.keyDown(window, { key: " " });
    expect(within(dialog).getByText("Highlights")).toBeVisible();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Restore panel size" })).toBeVisible();
    expect(screen.getByText("2 / 2")).toBeVisible();
    expect(start).toHaveFocus();
  });

  it("closes the slideshow with its exit button and keeps Source view separate", async () => {
    const be = backend(vi.fn().mockResolvedValue(deckPayload({ content: '{"kind":"deck"}' })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "review.deck.json" }} backend={be} />
      </ConfirmProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Slideshow" }));
    fireEvent.click(screen.getByRole("button", { name: "Exit slideshow" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.queryByRole("button", { name: "Slideshow" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Slides" }));
    expect(screen.getByRole("button", { name: "Slideshow" })).toBeVisible();
    expect(screen.getByText("Quarterly Review")).toBeVisible();
  });

  it("surfaces export failures without losing the preview", async () => {
    const exportDeckPptx = vi.fn().mockRejectedValue(new Error("slide 2 needs image fallback"));
    const be: PreviewBackend = {
      ...backend(vi.fn().mockResolvedValue(deckPayload())),
      exportDeckPptx,
    };
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "review.deck.json" }} backend={be} />
      </ConfirmProvider>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Export PPTX" }));
    expect(await screen.findByText(/image fallback/)).toBeVisible();
    expect(screen.getByText("Quarterly Review")).toBeVisible();
  });

  it("toggles between rendered slides and the raw spec source", async () => {
    const specJson = JSON.stringify({ version: 1, title: "Review", slides: [] });
    const be = backend(vi.fn().mockResolvedValue(deckPayload({ content: specJson })));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "review.deck.json" }} backend={be} />
      </ConfirmProvider>,
    );
    expect(await screen.findByText("Quarterly Review")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(screen.queryByText("Quarterly Review")).not.toBeInTheDocument();
    expect(screen.getByText(/"version"/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Slides" }));
    expect(await screen.findByText("Quarterly Review")).toBeVisible();
  });

  it("shows an honest notice when the spec is missing", async () => {
    const be = backend(vi.fn().mockResolvedValue(
      payload({ kind: "deck", name: "broken.deck.json", path: "broken.deck.json" }),
    ));
    render(
      <ConfirmProvider>
        <PreviewPanel agentId="" source={{ path: "broken.deck.json" }} backend={be} />
      </ConfirmProvider>,
    );
    expect(await screen.findByText(/couldn't be rendered/i)).toBeVisible();
  });
});
