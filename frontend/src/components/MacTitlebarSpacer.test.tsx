import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MacTitlebarSpacer } from "./MacTitlebarSpacer";

const platform = vi.hoisted(() => ({ mac: true }));
vi.mock("@/lib/platform", () => ({
  get IS_MAC() { return platform.mac; },
}));

afterEach(() => {
  vi.unstubAllGlobals();
  platform.mac = true;
});

describe("MacTitlebarSpacer", () => {
  it("reserves a nonshrinking, draggable controls area in the macOS shell", () => {
    vi.stubGlobal("__TAURI_INTERNALS__", {});
    render(<MacTitlebarSpacer />);
    const spacer = screen.getByTestId("mac-titlebar-spacer");
    expect(spacer).toHaveStyle({ height: "32px", flexShrink: "0" });
    expect(spacer).toHaveAttribute("data-tauri-drag-region");
  });

  it("does not add titlebar spacing in a browser", () => {
    render(<MacTitlebarSpacer />);
    expect(screen.queryByTestId("mac-titlebar-spacer")).not.toBeInTheDocument();
  });

  it("does not add macOS controls spacing on Windows or Linux", () => {
    vi.stubGlobal("__TAURI_INTERNALS__", {});
    platform.mac = false;
    render(<MacTitlebarSpacer />);
    expect(screen.queryByTestId("mac-titlebar-spacer")).not.toBeInTheDocument();
  });
});
