import { describe, expect, it } from "vitest";
import { collectFileRefs, type ToolCallData } from "./ToolCallBlock";

function call(partial: Partial<ToolCallData>): ToolCallData {
  return {
    id: "c1",
    capability: "read_file",
    args: {},
    status: "complete",
    ...partial,
  };
}

describe("collectFileRefs", () => {
  it("collects produced files from write_file", () => {
    const refs = collectFileRefs([
      call({
        capability: "write_file",
        args: { path: "notes/todo.md" },
        result: { path: "notes/todo.md", action: "created", bytes: 10 },
      }),
    ]);
    expect(refs).toEqual([
      { source: { path: "notes/todo.md" }, name: "todo.md", produced: true },
    ]);
  });

  it("skips unchanged write_file results", () => {
    const refs = collectFileRefs([
      call({
        capability: "write_file",
        args: { path: "a.md" },
        result: { path: "a.md", action: "unchanged", bytes: 5 },
      }),
    ]);
    expect(refs).toEqual([]);
  });

  it("read_file calls never chip — inputs are not outputs", () => {
    const refs = collectFileRefs([
      call({ args: { path: "src/main.py" }, result: { content: "x" } }),
      call({ args: { path: "attachments/dup-test.txt" }, result: { content: "x" } }),
    ]);
    expect(refs).toEqual([]);
  });

  it("a file the run read then rewrote chips once, as produced", () => {
    const refs = collectFileRefs([
      call({ args: { path: "a.md" }, result: { content: "x" } }),
      call({
        capability: "write_file",
        args: { path: "a.md" },
        result: { path: "a.md", action: "modified", bytes: 5 },
      }),
    ]);
    expect(refs).toHaveLength(1);
    expect(refs[0].produced).toBe(true);
  });

  it("artifact results dedupe by id and keep the produced revision", () => {
    const refs = collectFileRefs([
      call({
        capability: "artifact_create",
        args: { path: "deck.pptx" },
        result: { artifact_id: "A1", revision_id: "r1", path: "deck.pptx" },
      }),
      call({
        capability: "artifact_revise",
        args: { artifact_id: "A1" },
        result: { revision_id: "r2", revision_number: 2, path: "deck.pptx" },
      }),
    ]);
    expect(refs).toHaveLength(1);
    expect(refs[0].source).toEqual({ artifactId: "A1", revisionId: "r2" });
    expect(refs[0].name).toBe("deck.pptx");
    expect(refs[0].produced).toBe(true);
  });

  it("artifact_export_pdf maps to the pdf artifact", () => {
    const refs = collectFileRefs([
      call({
        capability: "artifact_export_pdf",
        args: { artifact_id: "A1" },
        result: { export_status: "exported", pdf_artifact_id: "A2", pdf_path: "deck.pdf" },
      }),
    ]);
    expect(refs).toEqual([
      { source: { artifactId: "A2" }, name: "deck.pdf", produced: true },
    ]);
  });

  it("skips failed, errored, and non-file calls", () => {
    const refs = collectFileRefs([
      call({ capability: "write_file", args: { path: "a.md" }, status: "failed" }),
      call({
        capability: "write_file",
        args: { path: "b.md" },
        result: { error: "denied" },
      }),
      call({ capability: "web_fetch", args: { url: "https://x" }, result: { url: "https://x" } }),
      call({ capability: "artifact_history", args: { artifact_id: "A1" }, result: { revisions: [] } }),
    ]);
    expect(refs).toEqual([]);
  });
});
