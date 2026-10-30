import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentScopeRow } from "./KnowledgeVault";
import { formatBytes } from "@/lib/knowledge";

const scope = {
  id: "agent-1",
  name: "Researcher",
  document_count: 0,
  chunk_count: 0,
};

describe("Knowledge Vault", () => {
  it("formats document sizes for humans", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
  });

  it("agent scope row shows Empty and opens via Add", () => {
    const onOpen = vi.fn();
    render(<AgentScopeRow scope={scope} onOpen={onOpen} />);

    expect(screen.getByText("Researcher")).toBeInTheDocument();
    expect(screen.getByText("Empty")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("agent scope row shows doc count and Open when populated", () => {
    const onOpen = vi.fn();
    render(
      <AgentScopeRow
        scope={{ ...scope, document_count: 3, chunk_count: 18 }}
        onOpen={onOpen}
      />,
    );
    expect(screen.getByText("3 docs · 18 chunks")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
