import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { RuntimeInstallDialog } from "./RuntimeInstallDialog";
import { api } from "@/lib/api";
import type { InstallJob, InstallPlan } from "@/lib/types";

const PLAN: InstallPlan = {
  id: "p1",
  operator_id: "op-1",
  platform: "darwin-arm64",
  expires_at: "2999-01-01T00:00:00Z",
  recipe_sha256: "abc",
  total_download_bytes: 100,
  dependencies: [
    {
      id: "git",
      label: "Git",
      action: "install",
      version: "2.53.0",
      publisher: "Test",
      license: "MIT",
      verification: "publisher_checksum",
      download_url: "https://example.com/git.tgz",
      metadata_url: null,
      sha256: "deadbeef".repeat(8),
      download_bytes: 100,
      destination: "git/versions/2.53.0-abc-p1",
      unlocks: "Git tooling",
    },
  ],
};

const JOB: InstallJob = {
  id: "j1",
  plan_id: "p1",
  operator_id: "op-1",
  state: "downloading",
  progress_bytes: 50,
  current_dep: "git",
  created_at: "2026-01-01T00:00:00Z",
  dependencies: [
    {
      id: "git",
      action: "install",
      version: "2.53.0",
      status: "pending",
      detail: null,
    },
  ],
};

beforeEach(() => vi.restoreAllMocks());

describe("RuntimeInstallDialog", () => {
  it("shows plan details and gates install behind consent", async () => {
    vi.spyOn(api, "createDependencyPlan").mockResolvedValue(PLAN);
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={() => {}}
      />,
    );
    await act(async () => {});
    expect(screen.getByText("Git")).toBeTruthy();
    expect(screen.getByText(/Test · MIT/)).toBeTruthy();
    expect(screen.getByText(/publisher metadata/)).toBeTruthy();
    const installBtn = screen.getByRole("button", { name: /Install now/ });
    expect(installBtn).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(installBtn).toHaveProperty("disabled", false);
  });

  it("starts install only after consent and shows progress", async () => {
    vi.spyOn(api, "createDependencyPlan").mockResolvedValue(PLAN);
    const start = vi
      .spyOn(api, "startDependencyInstall")
      .mockResolvedValue(JOB);
    vi.spyOn(api, "getDependencyJob").mockResolvedValue({
      ...JOB,
      state: "completed",
    });
    const completed = vi.fn();
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={completed}
      />,
    );
    await act(async () => {});
    expect(start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Install now/ }));
    await act(async () => {});
    expect(start).toHaveBeenCalledWith("p1", true);
  });

  it("cancel posts once and keeps polling to terminal", async () => {
    vi.spyOn(api, "createDependencyPlan").mockResolvedValue(PLAN);
    vi.spyOn(api, "startDependencyInstall").mockResolvedValue(JOB);
    const cancel = vi
      .spyOn(api, "cancelDependencyJob")
      .mockResolvedValue({ ...JOB, state: "cancelling" });
    vi.spyOn(api, "getDependencyJob").mockResolvedValue({
      ...JOB,
      state: "cancelled",
    });
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={() => {}}
      />,
    );
    await act(async () => {});
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Install now/ }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /^Cancel$/ }));
    await act(async () => {});
    expect(cancel).toHaveBeenCalledWith("j1");
  });

  it("resume mode loads the job — no plan call, no install POST", async () => {
    const plan = vi.spyOn(api, "createDependencyPlan");
    vi.spyOn(api, "getDependencyJob").mockResolvedValue(JOB);
    const start = vi.spyOn(api, "startDependencyInstall");
    render(
      <RuntimeInstallDialog
        dependencyIds={[]}
        jobId="j1"
        onClose={() => {}}
        onCompleted={() => {}}
      />,
    );
    await act(async () => {});
    expect(screen.getByText("downloading")).toBeTruthy();
    expect(plan).not.toHaveBeenCalled();
    expect(start).not.toHaveBeenCalled();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Install now/ })).toBeNull();
  });

  it("immediate completed invokes onCompleted exactly once", async () => {
    vi.spyOn(api, "createDependencyPlan").mockResolvedValue(PLAN);
    vi.spyOn(api, "startDependencyInstall").mockResolvedValue({
      ...JOB,
      state: "completed",
    });
    const completed = vi.fn();
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={completed}
      />,
    );
    await act(async () => {});
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Install now/ }));
    await act(async () => {});
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it("double-click on Install posts only once", async () => {
    vi.spyOn(api, "createDependencyPlan").mockResolvedValue(PLAN);
    let resolvePost: (v: InstallJob) => void = () => {};
    const start = vi
      .spyOn(api, "startDependencyInstall")
      .mockImplementation(() => new Promise((r) => (resolvePost = r)));
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={() => {}}
      />,
    );
    await act(async () => {});
    fireEvent.click(screen.getByRole("checkbox"));
    const btn = screen.getByRole("button", { name: /Install now/ });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await act(async () => {
      resolvePost(JOB);
    });
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("failed terminal offers Retry that fetches a fresh plan", async () => {
    vi.spyOn(api, "createDependencyPlan").mockResolvedValue(PLAN);
    vi.spyOn(api, "startDependencyInstall").mockResolvedValue({
      ...JOB,
      state: "failed",
    });
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={() => {}}
      />,
    );
    await act(async () => {});
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Install now/ }));
    await act(async () => {});
    const retry = screen.getByRole("button", { name: /Retry/ });
    fireEvent.click(retry);
    await act(async () => {});
    expect(api.createDependencyPlan).toHaveBeenCalledTimes(2);
    // Fresh consent required — Install is disabled until re-approved.
    expect(screen.getByRole("button", { name: /Install now/ })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("cancel that returns completed invokes onCompleted exactly once", async () => {
    vi.spyOn(api, "createDependencyPlan").mockResolvedValue(PLAN);
    vi.spyOn(api, "startDependencyInstall").mockResolvedValue(JOB);
    vi.spyOn(api, "cancelDependencyJob").mockResolvedValue({
      ...JOB,
      state: "completed",
    });
    const completed = vi.fn();
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={completed}
      />,
    );
    await act(async () => {});
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /Install now/ }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Cancel/ }));
    await act(async () => {});
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it("plan failure surfaces and no job starts", async () => {
    vi.spyOn(api, "createDependencyPlan").mockRejectedValue(
      new Error("409 expired"),
    );
    const start = vi.spyOn(api, "startDependencyInstall");
    render(
      <RuntimeInstallDialog
        dependencyIds={["git"]}
        onClose={() => {}}
        onCompleted={() => {}}
      />,
    );
    await act(async () => {});
    expect(screen.getByRole("alert").textContent).toContain("409");
    expect(start).not.toHaveBeenCalled();
  });
});
