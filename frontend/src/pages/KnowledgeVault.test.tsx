import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KnowledgeScopeCard } from "./KnowledgeVault";
import { formatBytes } from "@/lib/knowledge";

const scope = {
  id: "shared",
  name: "Shared Knowledge",
  document_count: 3,
  chunk_count: 18,
};

describe("Knowledge Vault", () => {
  it("formats document sizes for humans", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
  });

  it("opens a scope with click and keyboard activation", () => {
    const onClick = vi.fn();
    render(<KnowledgeScopeCard scope={scope} onClick={onClick} />);

    expect(screen.getByText("Shared Knowledge")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button"));
    fireEvent.keyDown(screen.getByRole("button"), { key: "Enter" });
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});
