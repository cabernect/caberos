import { useEffect, useRef, useState } from "react";

const TERMINAL_STATES = new Set([
  "completed",
  "failed",
  "cancelled",
  "interrupted",
]);

/** Only these three have managed recipes in this slice — Chromium keeps
 * its own installer. */
const INSTALLABLE = new Set(["nodejs", "uv", "git"]);
import {
  CheckCircle2,
  CircleAlert,
  CircleOff,
  ExternalLink,
  RefreshCw,
  Wrench,
} from "lucide-react";

import { api } from "../lib/api";
import type { InstallJob, RuntimeDependency } from "../lib/types";
import { RuntimeInstallDialog } from "./RuntimeInstallDialog";

const STATUS_TEXT: Record<string, string> = {
  ready: "Ready",
  missing: "Missing",
  incompatible: "Incompatible",
  error: "Check failed",
};

const SOURCE_TEXT: Record<string, string> = {
  override: "configured path",
  system: "system",
  managed: "managed runtime",
  none: "",
};

/** Optional Tools & Runtimes — readiness only; installation lands in a
 * later slice. Rows are text-labeled, never color-only. */
export function OptionalToolsAndRuntimes() {
  const [deps, setDeps] = useState<RuntimeDependency[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const generation = useRef(0);
  const [installFor, setInstallFor] = useState<string[] | null>(null);
  const [inspectJob, setInspectJob] = useState<string | null>(null);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [activeJobs, setActiveJobs] = useState<InstallJob[]>([]);
  // Bumping this restarts the monitor (mount, explicit Re-check, a new
  // non-terminal job) — idle cards hold zero timers.
  const [jobsRevision, setJobsRevision] = useState(0);
  const knownActive = useRef(new Set<string>()); // survives monitor restarts

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
    };
  }, []);

  const load = async (recheck: boolean) => {
    const gen = ++generation.current;
    if (recheck) setChecking(true);
    try {
      const res = recheck
        ? await api.recheckDependencies()
        : await api.getDependencies();
      if (!mounted.current || gen !== generation.current) return;
      setDeps(res.dependencies);
      setError(null);
    } catch (e) {
      if (mounted.current && gen === generation.current) {
        setError(String(e));
      }
    } finally {
      if (mounted.current && gen === generation.current) {
        setLoading(false);
        setChecking(false);
      }
    }
  };

  // Readiness snapshot — once on mount, once per explicit Re-check.
  useEffect(() => {
    void load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Install-job monitor: ONE snapshot per revision, sequential 2 s polls
  // only while jobs are active; an idle card holds zero timers. A failed
  // GET retries at 4 s only when known-active jobs exist — a cold, idle
  // failure shows the alert and waits for the operator instead of
  // spamming a dead backend.
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ctrl = new AbortController();
    async function pollJobs() {
      // Per-request ownership: the effect-level abort forwards into the
      // in-flight GET, and a hung response is released by a 15 s timeout
      // so an active job monitor can retry instead of freezing.
      const reqCtrl = new AbortController();
      const forwardAbort = () => reqCtrl.abort();
      ctrl.signal.addEventListener("abort", forwardAbort, { once: true });
      const timeout = setTimeout(() => reqCtrl.abort(), 15_000);
      try {
        const { jobs } = await api.listDependencyJobs(reqCtrl.signal);
        if (stop || !mounted.current) return;
        const active = jobs.filter((j) => !TERMINAL_STATES.has(j.state));
        setActiveJobs(active);
        setJobsError(null);
        // A job that just left the active set reached terminal —
        // refresh readiness once, not on every poll.
        const anyTerminal = [...knownActive.current].some(
          (id) => !active.some((j) => j.id === id),
        );
        if (anyTerminal) void load(true);
        knownActive.current = new Set(active.map((j) => j.id));
        if (active.length > 0) timer = setTimeout(pollJobs, 2000);
      } catch (e: any) {
        if (stop || !mounted.current || ctrl.signal.aborted) return;
        // Timeout/abort of THIS request only — the monitor itself lives.
        setJobsError(e?.message ?? "Could not refresh install jobs");
        if (knownActive.current.size > 0) {
          timer = setTimeout(pollJobs, 4000);
        }
      } finally {
        clearTimeout(timeout);
        ctrl.signal.removeEventListener("abort", forwardAbort);
      }
    }
    void pollJobs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
    return () => {
      stop = true;
      ctrl.abort();
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobsRevision]);

  return (
    <div>
      <h2 className="mb-3 text-[14px] font-semibold text-[var(--ink)]">
        Optional Tools &amp; Runtimes
      </h2>
      <div
        className="rounded-xl p-5"
        style={{
          border: "1px solid var(--border-soft)",
          background: "var(--sidebar)",
        }}
      >
        {loading ? (
          <div className="space-y-2" aria-busy="true">
            <div
              className="h-3 w-40 animate-pulse rounded"
              style={{ background: "var(--border)" }}
            />
            <div
              className="h-3 w-56 animate-pulse rounded"
              style={{ background: "var(--border)" }}
            />
          </div>
        ) : (
          <div className="space-y-3">
            {error && (
              <p role="alert" className="text-[13px] text-[var(--danger)]">
                {deps
                  ? `Re-check failed: ${error}`
                  : `Status unavailable: ${error}`}
              </p>
            )}
            {jobsError && (
              <p role="alert" className="text-[13px] text-[var(--danger)]">
                Install progress unavailable: {jobsError}
              </p>
            )}
            <ul className="space-y-2.5">
              {(deps ?? []).map((d) => {
                const active = activeJobs.find((j) =>
                  j.dependencies.some((x) => x.id === d.id),
                );
                return (
                  <DependencyRow
                    key={d.id}
                    dep={d}
                    busy={Boolean(active)}
                    onInstall={() => setInstallFor([d.id])}
                    onInspect={
                      active ? () => setInspectJob(active.id) : undefined
                    }
                  />
                );
              })}
            </ul>
            <div className="flex items-center justify-between gap-3 pt-1">
              <p className="text-[12px] text-[var(--ink-3)]">
                Missing tools only gate the features that use them — remote MCP
                servers and core app features keep working.
              </p>
              <button
                type="button"
                onClick={() => {
                  if (checking) return;
                  void load(true);
                  setJobsRevision((r) => r + 1); // fresh jobs snapshot too
                }}
                disabled={checking}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition-colors hover:bg-[var(--surface)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)] disabled:opacity-50"
                style={{ border: "1px solid var(--border)" }}
              >
                <RefreshCw
                  size={13}
                  className={checking ? "animate-spin" : ""}
                  aria-hidden
                />
                {checking ? "Checking…" : "Re-check"}
              </button>
            </div>
          </div>
        )}
      </div>
      {installFor && (
        <RuntimeInstallDialog
          dependencyIds={installFor}
          onStarted={(job) => {
            if (TERMINAL_STATES.has(job.state)) return; // nothing to watch
            knownActive.current.add(job.id);
            setActiveJobs((prev) =>
              prev.some((j) => j.id === job.id) ? prev : [...prev, job],
            );
            setJobsRevision((r) => r + 1); // resume the monitor if idle
          }}
          onClose={() => setInstallFor(null)}
          onCompleted={() => {
            setInstallFor(null);
            void load(true);
          }}
        />
      )}
      {inspectJob && (
        <RuntimeInstallDialog
          dependencyIds={[]}
          jobId={inspectJob}
          onClose={() => setInspectJob(null)}
          onCompleted={() => {
            setInspectJob(null);
            void load(true);
          }}
        />
      )}
    </div>
  );
}

function DependencyRow({
  dep,
  busy,
  onInstall,
  onInspect,
}: {
  dep: RuntimeDependency;
  busy: boolean;
  onInstall: () => void;
  onInspect?: () => void;
}) {
  const statusText = STATUS_TEXT[dep.status] ?? "Unknown";
  const icon =
    dep.status === "ready" ? (
      <CheckCircle2 size={14} className="text-[var(--accent)]" aria-hidden />
    ) : dep.status === "missing" ? (
      <CircleOff size={14} className="text-[var(--ink-3)]" aria-hidden />
    ) : (
      <CircleAlert size={14} className="text-[var(--danger)]" aria-hidden />
    );
  return (
    <li className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Wrench size={13} className="text-[var(--ink-3)]" aria-hidden />
          <span className="text-[13px] font-medium text-[var(--ink)]">
            {dep.label}
          </span>
          <span className="text-[12px] text-[var(--ink-3)]">{statusText}</span>
          {dep.version && (
            <span className="text-[12px] text-[var(--ink-3)]">
              {dep.version}
            </span>
          )}
          {dep.source !== "none" && (
            <span className="text-[12px] text-[var(--ink-3)]">
              · {SOURCE_TEXT[dep.source] ?? dep.source}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
          Unlocks: {dep.unlocks}
        </p>
        {dep.detail && dep.status !== "ready" && (
          <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">{dep.detail}</p>
        )}
        {dep.status !== "ready" && dep.managed_recipe_available && (
          <>
            <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
              Verified download recipe available.
            </p>
            {dep.source !== "override" && INSTALLABLE.has(dep.id) && !busy && (
              <button
                type="button"
                onClick={onInstall}
                className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-[12px] text-[var(--ink-2)] hover:bg-[var(--hover)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
              >
                Install
              </button>
            )}
            {busy && onInspect && (
              <button
                type="button"
                onClick={onInspect}
                className="mt-1.5 inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1 text-[12px] text-[var(--ink-2)] hover:bg-[var(--hover)]"
              >
                Inspect progress
              </button>
            )}
          </>
        )}
        {dep.status !== "ready" &&
          !dep.managed_recipe_available &&
          (dep.guidance_url ? (
            <a
              href={dep.guidance_url}
              target="_blank"
              rel="noreferrer"
              className="mt-0.5 inline-flex items-center gap-1 text-[12px] text-[var(--accent)] hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
            >
              Guided setup <ExternalLink size={11} aria-hidden />
            </a>
          ) : (
            <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
              Managed setup is not supported on this platform.
            </p>
          ))}
      </div>
      {icon}
    </li>
  );
}
