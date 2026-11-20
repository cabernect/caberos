import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type PreviewSource } from "@/lib/api";
import { WorkspacePanel } from "./WorkspacePanel";

vi.mock("@/components/previews/PreviewPanel", () => ({
  PreviewPanel: ({ source }: { source: PreviewSource }) => (
    <aside aria-label="File preview">{source.path}</aside>
  ),
}));

function Panel() {
  const [selected, setSelected] = useState<PreviewSource | null>(null);
  return (
    <WorkspacePanel
      agentId="agent-1"
      agentName="Caber"
      sessionId="session-1"
      selected={selected}
      onSelect={setSelected}
      changedPaths={new Set()}
      citations={[]}
      runStatus={null}
    />
  );
}

beforeEach(() => {
  vi.spyOn(api, "listWorkspace").mockImplementation(async (_agent, path) => ({
    type: "dir",
    path: path ?? "",
    entries: path === "artifacts"
      ? [{ name: "report.docx", type: "file", size: 100 }]
      : [{ name: "artifacts", type: "dir", size: 0 }],
  }));
});

afterEach(() => vi.restoreAllMocks());

describe("Workspace file browser", () => {
  it("exposes folder expansion and the selected file while keeping the session root", async () => {
    render(<Panel />);
    const folder = await screen.findByRole("button", { name: "artifacts" });
    expect(folder).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(folder);
    expect(folder).toHaveAttribute("aria-expanded", "true");
    const file = await screen.findByRole("button", { name: "report.docx" });
    fireEvent.click(file);
    expect(file).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("complementary", { name: "File preview" })).toHaveTextContent("artifacts/report.docx");
    expect(api.listWorkspace).toHaveBeenCalledWith("agent-1", "artifacts", "session-1");
  });

  it("hides the file list without losing the selected preview or expanded folders", async () => {
    render(<Panel />);
    fireEvent.click(await screen.findByRole("button", { name: "artifacts" }));
    fireEvent.click(await screen.findByRole("button", { name: "report.docx" }));
    fireEvent.click(screen.getByRole("button", { name: "Hide files" }));
    expect(screen.queryByRole("region", { name: "Workspace files" })).not.toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "File preview" })).toHaveTextContent("report.docx");
    expect(screen.getByRole("button", { name: "Show files" })).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByRole("button", { name: "Show files" }));
    const files = screen.getByRole("region", { name: "Workspace files" });
    expect(within(files).getByRole("button", { name: "report.docx" })).toHaveAttribute("aria-current", "true");
    expect(api.listWorkspace).toHaveBeenCalledTimes(2);
  });

  it("can reopen the browser from the empty preview without resetting its filter", async () => {
    render(<Panel />);
    await screen.findByRole("button", { name: "artifacts" });
    fireEvent.change(screen.getByRole("textbox", { name: "Find file" }), {
      target: { value: "art" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Hide files" }));
    fireEvent.click(screen.getByRole("button", { name: "Browse files" }));
    expect(screen.getByRole("textbox", { name: "Find file" })).toHaveValue("art");
    expect(screen.getByRole("button", { name: "artifacts" })).toBeVisible();
  });
});
