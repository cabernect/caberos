import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DownloadEvent } from "@tauri-apps/plugin-updater";
import { UpdateChecker } from "@/components/UpdateChecker";
import { downloadAndInstallUpdate, refreshUpdates, resetUpdater, useUpdater } from "./updater";

const mocks = vi.hoisted(() => ({
  check: vi.fn(),
  notify: vi.fn(async () => {}),
}));
vi.mock("@tauri-apps/plugin-updater", () => ({ check: mocks.check }));
vi.mock("@tauri-apps/api/app", () => ({ getVersion: async () => "0.2.3" }));
vi.mock("@/lib/api", () => ({ api: { emitNotification: mocks.notify } }));

function Status() {
  const updater = useUpdater();
  return <output>{updater.status}</output>;
}

function available(version = "0.2.4") {
  return {
    currentVersion: "0.2.3", version, body: "",
    close: vi.fn(async () => {}),
    downloadAndInstall: vi.fn<(
      onEvent: (event: DownloadEvent) => void,
    ) => Promise<void>>(async () => {}),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("__TAURI_INTERNALS__", {});
  mocks.check.mockReset().mockResolvedValue(null);
  resetUpdater();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("update polling", () => {
  it("checks after startup, retries a failure at the next interval, and cleans timers", async () => {
    mocks.check.mockRejectedValueOnce(new Error("offline"));
    const view = render(<><UpdateChecker /><Status /></>);
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(screen.getByText("error")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000));
    expect(screen.getByText("up-to-date")).toBeInTheDocument();
    expect(mocks.check).toHaveBeenCalledTimes(2);
    view.unmount();
    await vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000);
    expect(mocks.check).toHaveBeenCalledTimes(2);
  });

  it("does not check in web mode", async () => {
    vi.unstubAllGlobals();
    render(<UpdateChecker />);
    await vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000);
    expect(mocks.check).not.toHaveBeenCalled();
  });

  it("keeps a dismissed version hidden but shows a newer version", async () => {
    mocks.check.mockResolvedValue(available());
    render(<UpdateChecker />);
    await act(() => vi.advanceTimersByTimeAsync(3000));
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    await act(() => vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000));
    expect(screen.queryByText("New update available")).not.toBeInTheDocument();
    mocks.check.mockResolvedValue(available("0.2.5"));
    await act(() => vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000));
    expect(screen.getByText(/v0.2.5 is ready/)).toBeInTheDocument();
  });

  it("deduplicates simultaneous checks and allows a later manual recheck", async () => {
    const update = available();
    mocks.check.mockResolvedValue(update);
    await Promise.all([refreshUpdates(), refreshUpdates()]);
    expect(mocks.check).toHaveBeenCalledTimes(1);
    expect(update.close).toHaveBeenCalledTimes(1);
    await refreshUpdates();
    expect(mocks.check).toHaveBeenCalledTimes(2);
  });

  it("allows retry after a failed download and releases its resource", async () => {
    const update = available();
    update.downloadAndInstall.mockRejectedValueOnce(new Error("network lost"));
    mocks.check.mockResolvedValue(update);
    render(<Status />);
    await act(async () => {
      await expect(downloadAndInstallUpdate()).rejects.toThrow("network lost");
    });
    expect(screen.getByText("error")).toBeInTheDocument();
    expect(update.close).toHaveBeenCalledOnce();
    await act(async () => { await refreshUpdates(); });
    expect(screen.getByText("available")).toBeInTheDocument();
  });

  it("protects downloading, installing and restart-ready states from polls and resets", async () => {
    let finish!: () => void;
    let onEvent!: (event: DownloadEvent) => void;
    const update = available();
    update.downloadAndInstall.mockImplementation(async (callback) => {
      onEvent = callback;
      await new Promise<void>((resolve) => { finish = resolve; });
    });
    mocks.check.mockResolvedValue(update);
    render(<><UpdateChecker /><Status /></>);
    await act(() => vi.advanceTimersByTimeAsync(3000));
    let install!: Promise<void>;
    await act(async () => { install = downloadAndInstallUpdate(); });
    expect(screen.getByText("downloading")).toBeInTheDocument();
    const checks = mocks.check.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000));
    await act(async () => { await refreshUpdates(); resetUpdater(); });
    expect(mocks.check).toHaveBeenCalledTimes(checks);
    expect(screen.getByText("downloading")).toBeInTheDocument();
    await act(async () => { onEvent({ event: "Finished" }); });
    expect(screen.getByText("installing")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000));
    expect(mocks.check).toHaveBeenCalledTimes(checks);
    await act(async () => { finish(); await install; });
    expect(screen.getByText("ready")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(4 * 60 * 60 * 1000));
    expect(mocks.check).toHaveBeenCalledTimes(checks);
  });
});
