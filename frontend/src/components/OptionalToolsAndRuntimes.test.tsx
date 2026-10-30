/** W11 readiness card — four dependency rows, statuses, recheck guards. */
import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { OptionalToolsAndRuntimes } from "./OptionalToolsAndRuntimes";
import type { RuntimeDependency } from "@/lib/types";

const dep = (over: Partial<RuntimeDependency> = {}): RuntimeDependency => ({
  id: "nodejs",
  label: "Node.js",
  status: "ready",
  source: "system",
  version: "24.21.0",
  executables: { node: "/opt/homebrew/bin/node" },
  detail: null,
  unlocks: "Local MCP servers (stdio)",
  managed_recipe_available: true,
  guidance_url: null,
  ...over,
});

const FOUR: RuntimeDependency[] = [
  dep({ id: "nodejs", label: "Node.js" }),
  dep({ id: "uv", label: "uv", version: "0.12.24" }),
  dep({ id: "git", label: "Git", version: "2.53.0" }),
  dep({ id: "chromium", label: "Chromium", source: "managed", version: "141" }),
];

describe("OptionalToolsAndRuntimes", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders all four rows with statuses, versions and unlocks", async () => {
    vi.spyOn(api, "getDependencies").mockResolvedValue({ dependencies: FOUR });
    render(<OptionalToolsAndRuntimes />);
    await act(async () => {});
    for (const label of ["Node.js", "uv", "Git", "Chromium"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.getAllByText("Ready").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("24.21.0")).toBeTruthy();
    expect(screen.getAllByText(/Unlocks:/).length).toBe(4);
    // No LibreOffice row and no guided-setup affordance for these four.
    expect(screen.queryByText("LibreOffice")).toBeNull();
    expect(screen.queryByText(/Guided setup/)).toBeNull();
  });

  it("shows managed-setup note for missing deps with a recipe", async () => {
    vi.spyOn(api, "getDependencies").mockResolvedValue({
      dependencies: [
        dep({
          id: "uv",
          label: "uv",
          status: "missing",
          source: "none",
          version: null,
        }),
      ],
    });
    render(<OptionalToolsAndRuntimes />);
    await act(async () => {});
    expect(screen.getByText(/Verified download recipe available/)).toBeTruthy();
  });

  it("recheck button POSTs once and swaps in fresh rows", async () => {
    const get = vi
      .spyOn(api, "getDependencies")
      .mockResolvedValue({ dependencies: FOUR });
    const post = vi.spyOn(api, "recheckDependencies").mockResolvedValue({
      dependencies: [
        dep({
          id: "nodejs",
          label: "Node.js",
          status: "missing",
          source: "none",
          version: null,
        }),
      ],
    });
    render(<OptionalToolsAndRuntimes />);
    await act(async () => {});
    const btn = screen.getByRole("button", { name: /Re-check/ });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await act(async () => {});
    expect(post).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Missing")).toBeTruthy();
  });

  it("error surface keeps prior rows and is actionable", async () => {
    vi.spyOn(api, "getDependencies").mockResolvedValue({ dependencies: FOUR });
    vi.spyOn(api, "recheckDependencies").mockRejectedValue(new Error("500"));
    render(<OptionalToolsAndRuntimes />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Re-check/ }));
    await act(async () => {});
    expect(screen.getByText(/Re-check failed/)).toBeTruthy();
    expect(screen.getByText("Node.js")).toBeTruthy(); // rows retained
  });

  it("pending initial GET shows skeleton — recheck cannot interleave", async () => {
    // The generation guard means a late mount GET can never clobber a
    // recheck: the button isn't even rendered until the first load settles.
    vi.spyOn(api, "getDependencies").mockImplementation(
      () => new Promise(() => {}),
    );
    const { container } = render(<OptionalToolsAndRuntimes />);
    await act(async () => {});
    expect(container.querySelector("[aria-busy]")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Re-check/ })).toBeNull();
  });

  it("jobs list failure keeps rows and surfaces an alert that clears on recovery", async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(api, "getDependencies").mockResolvedValue({
        dependencies: FOUR,
      });
      const jobs = vi
        .spyOn(api, "listDependencyJobs")
        .mockRejectedValueOnce(new Error("offline"))
        .mockResolvedValue({ jobs: [] });
      render(<OptionalToolsAndRuntimes />);
      await act(async () => {});
      expect(screen.getByText(/Install progress unavailable/)).toBeTruthy();
      expect(screen.getByText("Node.js")).toBeTruthy();
      expect(jobs).toHaveBeenCalledTimes(1);
      // Idle failure — no auto-retry; the operator's Re-check owns recovery.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByRole("button", { name: /Re-check/i }));
      await act(async () => {});
      expect(jobs).toHaveBeenCalledTimes(2);
      expect(screen.queryByText(/Install progress unavailable/)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("unmount after recheck issues no further state writes", async () => {
    let resolvePost: (v: {
      dependencies: RuntimeDependency[];
    }) => void = () => {};
    vi.spyOn(api, "getDependencies").mockResolvedValue({ dependencies: FOUR });
    const post = vi
      .spyOn(api, "recheckDependencies")
      .mockImplementation(() => new Promise((r) => (resolvePost = r)));
    const { unmount } = render(<OptionalToolsAndRuntimes />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Re-check/ }));
    unmount();
    await act(async () => {
      resolvePost({ dependencies: FOUR });
    });
    expect(post).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Node.js")).toBeNull();
  });
});

describe("idle job monitor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("mounts with no active jobs → exactly one listDependencyJobs call, zero timers", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.spyOn(api, "getDependencies").mockResolvedValue({
        dependencies: FOUR,
      });
      const jobs = vi
        .spyOn(api, "listDependencyJobs")
        .mockResolvedValue({ jobs: [] });
      render(<OptionalToolsAndRuntimes />);
      await act(async () => {});
      expect(jobs).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      // Idle card holds no recurring poll.
      expect(jobs).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("active jobs poll at 2s, then stop when the set goes empty", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.spyOn(api, "getDependencies").mockResolvedValue({
        dependencies: FOUR,
      });
      let first = true;
      const jobs = vi
        .spyOn(api, "listDependencyJobs")
        .mockImplementation(async () => {
          if (first) {
            return {
              jobs: [
                {
                  id: "j1",
                  plan_id: "p1",
                  operator_id: "op",
                  state: "running",
                  progress_bytes: 0,
                  current_dep: "git",
                  created_at: "2026-01-01T00:00:00Z",
                  dependencies: [
                    {
                      id: "git",
                      action: "install",
                      version: null,
                      status: "running",
                      detail: null,
                    },
                  ],
                },
              ],
            };
          }
          return { jobs: [] };
        });
      render(<OptionalToolsAndRuntimes />);
      await act(async () => {});
      expect(jobs).toHaveBeenCalledTimes(1);
      first = false;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(jobs).toHaveBeenCalledTimes(2); // active → next poll
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(2); // empty response → stops
    } finally {
      vi.useRealTimers();
    }
  });

  it("failed GET while known-active retries at 4s; idle failure does not poll", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.spyOn(api, "getDependencies").mockResolvedValue({
        dependencies: FOUR,
      });
      let calls = 0;
      const jobs = vi
        .spyOn(api, "listDependencyJobs")
        .mockImplementation(async () => {
          calls++;
          if (calls === 1)
            return {
              jobs: [
                {
                  id: "j1",
                  plan_id: "p1",
                  operator_id: "op",
                  state: "running",
                  progress_bytes: 0,
                  current_dep: "git",
                  created_at: "2026-01-01T00:00:00Z",
                  dependencies: [
                    {
                      id: "git",
                      action: "install",
                      version: null,
                      status: "running",
                      detail: null,
                    },
                  ],
                },
              ],
            };
          if (calls === 2) throw new Error("offline");
          return { jobs: [] };
        });
      render(<OptionalToolsAndRuntimes />);
      await act(async () => {});
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(jobs).toHaveBeenCalledTimes(2); // errored while known-active
      await act(async () => {
        await vi.advanceTimersByTimeAsync(4_000);
      });
      expect(jobs).toHaveBeenCalledTimes(3); // 4s retry because active jobs known
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(3); // recovered empty → stops
    } finally {
      vi.useRealTimers();
    }
  });

  it("explicit Re-check re-runs both readiness and the jobs snapshot", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.spyOn(api, "getDependencies").mockResolvedValue({
        dependencies: FOUR,
      });
      const post = vi
        .spyOn(api, "recheckDependencies")
        .mockResolvedValue({ dependencies: FOUR });
      const jobs = vi
        .spyOn(api, "listDependencyJobs")
        .mockResolvedValue({ jobs: [] });
      render(<OptionalToolsAndRuntimes />);
      await act(async () => {});
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(1); // idle
      const btn = screen.getByRole("button", { name: /Re-check/i });
      fireEvent.click(btn);
      await act(async () => {});
      expect(post).toHaveBeenCalledTimes(1);
      expect(jobs).toHaveBeenCalledTimes(2); // one fresh snapshot — not a loop
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("hung GET is released by the 15s timeout — active jobs retry at 4s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.spyOn(api, "getDependencies").mockResolvedValue({
        dependencies: FOUR,
      });
      let calls = 0;
      const jobs = vi
        .spyOn(api, "listDependencyJobs")
        .mockImplementation((signal) => {
          calls++;
          if (calls === 1) {
            return Promise.resolve({
              jobs: [
                {
                  id: "j1",
                  plan_id: "p1",
                  operator_id: "op",
                  state: "running",
                  progress_bytes: 0,
                  current_dep: "git",
                  created_at: "2026-01-01T00:00:00Z",
                  dependencies: [
                    {
                      id: "git",
                      action: "install",
                      version: null,
                      status: "running",
                      detail: null,
                    },
                  ],
                },
              ],
            });
          }
          if (calls === 2) {
            // Hung — only resolves via its abort signal.
            return new Promise((_res, rej) => {
              signal?.addEventListener("abort", () =>
                rej(new DOMException("Aborted", "AbortError")),
              );
            });
          }
          return Promise.resolve({ jobs: [] });
        });
      render(<OptionalToolsAndRuntimes />);
      await act(async () => {});
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(jobs).toHaveBeenCalledTimes(2); // poll — request now hung
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      // Timeout released it → error visible while jobs stay busy-tracked.
      expect(screen.getByText(/Install progress unavailable/)).toBeTruthy();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(4_000);
      });
      expect(jobs).toHaveBeenCalledTimes(3); // 4s retry while known-active
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(3); // recovered empty → stops
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("integrated install flow", () => {
  afterEach(() => vi.restoreAllMocks());

  it("start install wakes the monitor; terminal → readiness refresh, then idle", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.spyOn(api, "getDependencies").mockResolvedValue({
        dependencies: [
          dep({ status: "missing", source: "none", version: null }),
        ],
      });
      vi.spyOn(api, "recheckDependencies").mockResolvedValue({
        dependencies: FOUR,
      });
      const queued = {
        id: "j1",
        plan_id: "p1",
        operator_id: "op",
        state: "queued",
        progress_bytes: 0,
        current_dep: "nodejs",
        created_at: "2026-01-01T00:00:00Z",
        dependencies: [
          {
            id: "nodejs",
            action: "install",
            version: null,
            status: "queued",
            detail: null,
          },
        ],
      };
      const done = { ...queued, state: "completed" };
      const jobs = vi
        .spyOn(api, "listDependencyJobs")
        .mockResolvedValue({ jobs: [] });
      vi.spyOn(api, "createDependencyPlan").mockResolvedValue({
        id: "p1",
        operator_id: "op",
        platform: "mac",
        recipe_sha256: "b".repeat(64),
        total_download_bytes: 100,
        dependencies: [
          {
            id: "nodejs",
            label: "Node.js",
            action: "install",
            version: "24",
            publisher: "OpenJS",
            license: "MIT",
            verification: "sha256",
            download_url: "https://nodejs.org/dist/v24/node.tar.xz",
            metadata_url: null,
            sha256: "a".repeat(64),
            download_bytes: 100,
            destination: "/data/node",
            unlocks: "Local MCP servers (stdio)",
          },
        ],
        expires_at: "2026-01-01T01:00:00Z",
      });
      vi.spyOn(api, "startDependencyInstall").mockResolvedValue(queued);
      vi.spyOn(api, "getDependencyJob").mockResolvedValue(done);
      render(<OptionalToolsAndRuntimes />);
      await act(async () => {});
      expect(jobs).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(1); // idle before install

      fireEvent.click(screen.getByRole("button", { name: /Install/i }));
      await act(async () => {});
      // Consent gate — approve then start.
      // The start POST returns the queued job → onStarted wakes the
      // monitor whose immediate GET must see it too.
      jobs.mockResolvedValue({ jobs: [queued] });
      fireEvent.click(screen.getAllByRole("checkbox")[0]);
      fireEvent.click(screen.getByRole("button", { name: /Install now/i }));
      await act(async () => {});
      expect(jobs).toHaveBeenCalledTimes(2); // wake GET saw the queue
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      jobs.mockResolvedValue({ jobs: [done] }); // terminal on next pass
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(jobs).toHaveBeenCalledTimes(4);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(jobs).toHaveBeenCalledTimes(4); // terminal → monitor stops
      // Readiness refreshed exactly when the job went terminal (monitor
      // transition) plus the dialog's own onCompleted refresh — never a loop.
      expect(api.recheckDependencies).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
