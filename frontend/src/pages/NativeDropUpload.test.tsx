/** Native Tauri file-drop regressions: surfaces that only registered DOM
 * drag/drop handlers never see a native drop — the webview intercepts it.
 * The useDesktopFileDrop hook must be mounted on the page. */
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider } from "@/lib/theme";
import { api } from "@/lib/api";

type DragDropPayload = { type: "enter" | "over" | "drop" | "leave"; paths: string[]; position: { x: number; y: number } };
type DragDropEvent = { payload: DragDropPayload };
let nativeHandler: ((e: DragDropEvent) => void) | null = null;

vi.mock("@tauri-apps/api/webviewWindow", () => ({
  getCurrentWebviewWindow: () => ({
    onDragDropEvent: (fn: (e: DragDropEvent) => void) => {
      nativeHandler = fn;
      return Promise.resolve(() => {});
    },
  }),
}));
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (_cmd: string, args: { path: string }) => ({
    name: args.path.split("/").pop(),
    bytes: Array.from(new TextEncoder().encode("zip-bytes")),
  })),
}));

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return {
    ...real,
    api: {
      ...real.api,
      listKnowledgeOverview: vi.fn(async () => ({ scopes: [] })),
      listKnowledgeScope: vi.fn(async () => ({ documents: [] })),
      listProviders: vi.fn(async () => []),
      listAgents: vi.fn(async () => []),
      me: vi.fn(async () => ({ id: "op1", username: "test" })),
      searchKnowledge: vi.fn(async () => ({ results: [] })),
      searchKnowledgeScope: vi.fn(async () => ({ results: [] })),
      uploadKnowledgeScope: vi.fn(async () => ({ documents: [] })),
    },
  };
});

vi.mock("@/lib/confirmHook", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true), toast: vi.fn() }),
}));

const stubGlobals = () => {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => false,
  }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
};
stubGlobals();

import { KnowledgeVault } from "./KnowledgeVault";
import { ProvidersSettings } from "./ProvidersSettings";

const dropEvent = (paths: string[]) =>
  nativeHandler!({ payload: { type: "drop", paths, position: { x: 0, y: 0 } } });

const mountVault = (route = "/vault") =>
  render(
    <MemoryRouter initialEntries={[route]}>
      <ThemeProvider>
        <Routes>
          <Route path="/vault" element={<KnowledgeVault />} />
          <Route path="/vault/:scope" element={<KnowledgeVault />} />
        </Routes>
      </ThemeProvider>
    </MemoryRouter>,
  );

describe("Native Tauri drop", () => {
  beforeEach(() => {
    nativeHandler = null;
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {};
    stubGlobals();
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  });

  it("shared vault overview uploads a native drop", async () => {
    mountVault();
    await waitFor(() => expect(nativeHandler).not.toBeNull());
    await dropEvent(["/tmp/doc.md"]);
    await waitFor(() =>
      expect(api.uploadKnowledgeScope).toHaveBeenCalledWith(
        "shared",
        expect.objectContaining({ name: "doc.md" }),
      ),
    );
  });

  it("scoped vault page uploads a native drop to its scope", async () => {
    mountVault("/vault/a1");
    await waitFor(() => expect(nativeHandler).not.toBeNull());
    await dropEvent(["/tmp/doc.md"]);
    await waitFor(() =>
      expect(api.uploadKnowledgeScope).toHaveBeenCalledWith(
        "a1",
        expect.objectContaining({ name: "doc.md" }),
      ),
    );
  });

  it("migration tab previews a native .zip drop without importing", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({
        status: "ok", tables: [], agent_files: 1, workspace_files: 0,
        has_secret_key: false, secret_keys_match: null,
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    render(
      <MemoryRouter initialEntries={["/settings?tab=migration"]}>
        <ThemeProvider>
          <Routes>
            <Route path="/settings" element={<ProvidersSettings />} />
          </Routes>
        </ThemeProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(nativeHandler).not.toBeNull());
    await dropEvent(["/tmp/agent.yaml.zip"]);
    await waitFor(() =>
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/data/preview"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const urls = fetchSpy.mock.calls.map((c) => String(c[0]));
    expect(urls.every((u) => !u.includes("/api/data/import"))).toBe(true);
    const previewCall = fetchSpy.mock.calls.find((c) => String(c[0]).includes("/api/data/preview"));
    const body = previewCall?.[1]?.body as FormData;
    expect(body.get("file")).toBeInstanceOf(File);
    expect((body.get("file") as File).name).toBe("agent.yaml.zip");
  });

  it("migration tab rejects a non-zip native drop with a toast and no fetch", async () => {
    const fetchSpy = vi.fn<typeof fetch>(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    render(
      <MemoryRouter initialEntries={["/settings?tab=migration"]}>
        <ThemeProvider>
          <Routes>
            <Route path="/settings" element={<ProvidersSettings />} />
          </Routes>
        </ThemeProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(nativeHandler).not.toBeNull());
    await dropEvent(["/tmp/not-a-zip.txt"]);
    // give the handler a beat — no preview request should fire
    await new Promise((r) => setTimeout(r, 50));
    const previewCalls = fetchSpy.mock.calls.filter((c) => String(c[0]).includes("/api/data/"));
    expect(previewCalls).toHaveLength(0);
  });
});
