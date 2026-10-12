import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Loader2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { InstallJob, InstallPlan } from "@/lib/types";

const TERMINAL = new Set(["completed", "failed", "cancelled", "interrupted"]);

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "size unknown";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function RuntimeInstallDialog({
  dependencyIds,
  jobId,
  onStarted,
  onClose,
  onCompleted,
}: {
  dependencyIds: string[];
  /** Resume an in-flight job — no plan fetch, no second approval. */
  jobId?: string;
  onStarted?: (job: InstallJob) => void;
  onClose: () => void;
  onCompleted: () => void;
}) {
  const [plan, setPlan] = useState<InstallPlan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [job, setJob] = useState<InstallJob | null>(null);
  const [consent, setConsent] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [starting, setStarting] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const gen = useRef(0);
  const mounted = useRef(true);
  const dialogRef = useRef<HTMLDivElement>(null);
  const completedOnce = useRef(false);

  const active = job != null && !TERMINAL.has(job.state);
  const hasDownload =
    plan?.dependencies.some((d) => d.action === "install") ?? false;

  // Resume an in-flight job — never creates a plan or re-approves.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    api
      .getDependencyJob(jobId)
      .then((j) => {
        if (!cancelled && mounted.current) setJob(j);
      })
      .catch((e) => {
        if (!cancelled && mounted.current)
          setPlanError(e?.message ?? "Could not load the job");
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // Fetch the frozen plan once — never auto-installs.
  useEffect(() => {
    if (jobId) return;
    const g = ++gen.current;
    let cancelled = false;
    api
      .createDependencyPlan(dependencyIds)
      .then((p) => {
        if (!cancelled && gen.current === g) setPlan(p);
      })
      .catch((e) => {
        if (!cancelled && gen.current === g)
          setPlanError(e?.message ?? "Could not create an install plan");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dependencyIds.join(","), jobId]);

  // Sequential 1s polling — one in-flight request at a time.
  useEffect(() => {
    if (!job || TERMINAL.has(job.state)) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function tick() {
      try {
        const next = await api.getDependencyJob(job!.id);
        if (stop || !mounted.current) return;
        setJob(next);
        if (!TERMINAL.has(next.state)) {
          timer = setTimeout(tick, 1000);
        } else if (next.state === "completed" && !completedOnce.current) {
          completedOnce.current = true;
          onCompleted();
        }
      } catch (e: any) {
        if (stop || !mounted.current) return;
        setPollError(e?.message ?? "Status check failed");
        timer = setTimeout(tick, 2000); // backoff, keep last known progress
      }
    }
    timer = setTimeout(tick, 1000);
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id]);

  useEffect(() => {
    mounted.current = true;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    dialogRef.current?.querySelector<HTMLElement>("button")?.focus();
    return () => {
      mounted.current = false;
      gen.current++;
      previouslyFocused?.focus?.();
    };
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape" && !active && !starting) onClose();
      if (e.key === "Tab") {
        // Simple focus trap inside the dialog.
        const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
        );
        if (!focusables?.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [active, starting, onClose],
  );

  const startInstall = async () => {
    if (!plan || !consent || starting) return;
    setStarting(true);
    setInstallError(null);
    try {
      const j = await api.startDependencyInstall(plan.id, true);
      if (mounted.current) {
        setJob(j);
        onStarted?.(j);
        if (j.state === "completed" && !completedOnce.current) {
          completedOnce.current = true;
          onCompleted();
        }
      }
    } catch (e: any) {
      if (mounted.current) setInstallError(e?.message ?? "Install failed");
    } finally {
      if (mounted.current) setStarting(false);
    }
  };

  const cancelJob = async () => {
    if (!job) return;
    setCancelling(true);
    try {
      const j = await api.cancelDependencyJob(job.id);
      if (mounted.current) {
        setJob(j);
        if (j.state === "completed" && !completedOnce.current) {
          completedOnce.current = true;
          onCompleted();
        }
      }
    } catch (e: any) {
      if (mounted.current)
        setInstallError(
          e?.message ?? "Cancel failed — the job is still running",
        );
    } finally {
      if (mounted.current) setCancelling(false);
    }
  };

  const progress =
    plan && plan.total_download_bytes
      ? Math.min(
          100,
          Math.round(
            ((job?.progress_bytes ?? 0) / plan.total_download_bytes) * 100,
          ),
        )
      : null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Install runtimes"
      onKeyDown={handleKeyDown}
    >
      <div
        ref={dialogRef}
        className="max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--sidebar)] p-5 shadow-xl"
      >
        <div className="flex items-start justify-between">
          <h2 className="text-[15px] font-semibold text-[var(--ink)]">
            Install runtimes
          </h2>
          <button
            onClick={onClose}
            disabled={starting}
            title={
              starting
                ? "Starting — please wait"
                : active
                  ? "Hide — the job keeps running in the background"
                  : "Close"
            }
            aria-label={active ? "Hide — job keeps running" : "Close dialog"}
            className="rounded-md p-1 text-[var(--ink-3)] hover:text-[var(--ink)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          >
            <X size={16} aria-hidden />
          </button>
        </div>

        {planError && (
          <p role="alert" className="mt-3 text-[13px] text-[var(--danger)]">
            {planError}
          </p>
        )}

        {!jobId && !plan && !planError && (
          <p className="mt-4 flex items-center gap-2 text-[13px] text-[var(--ink-2)]">
            <Loader2 size={14} className="animate-spin" aria-hidden />
            Preparing install plan…
          </p>
        )}

        {plan && (
          <ul className="mt-4 space-y-3">
            {plan.dependencies.map((d) => (
              <li key={d.id} className="text-[13px]">
                <div className="flex items-center gap-2 text-[var(--ink-2)]">
                  {d.action === "install" ? (
                    <Download size={13} aria-hidden />
                  ) : (
                    <CheckCircle2 size={13} aria-hidden />
                  )}
                  <span className="font-medium text-[var(--ink)]">
                    {d.label}
                  </span>
                  <span>
                    {d.action === "install" ? "Install" : "Use existing"}
                  </span>
                  <span className="text-[var(--ink-3)]">{d.version}</span>
                </div>
                {d.action === "install" && (
                  <p className="mt-1 break-all pl-5 text-[12px] text-[var(--ink-2)]">
                    {d.publisher}
                    {d.license ? ` · ${d.license}` : ""}
                    {" · "}
                    {fmtBytes(d.download_bytes)}
                    {d.download_url && (
                      <>
                        <br />
                        From {new URL(d.download_url).hostname}
                      </>
                    )}
                    <br />
                    To {d.destination}
                    <br />
                    Checksum will be verified against publisher metadata
                    {d.sha256 ? ` (sha256 ${d.sha256.slice(0, 12)}…)` : ""} —
                    nothing is trusted before the check.
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        {!jobId && plan && !job && (
          <label className="mt-4 flex items-start gap-2 text-[13px] text-[var(--ink-2)]">
            <input
              type="checkbox"
              checked={consent}
              disabled={starting}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-[var(--accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
            />
            <span>
              {hasDownload
                ? "I approve these downloads into CaberOS private storage"
                : "I confirm using these existing runtimes"}
            </span>
          </label>
        )}

        {job && (
          <div className="mt-4">
            <div className="flex items-center gap-2 text-[13px] text-[var(--ink-2)]">
              {active ? (
                <Loader2 size={14} className="animate-spin" aria-hidden />
              ) : job.state === "completed" ? (
                <CheckCircle2
                  size={14}
                  className="text-[var(--ok)]"
                  aria-hidden
                />
              ) : (
                <AlertTriangle
                  size={14}
                  className="text-[var(--danger)]"
                  aria-hidden
                />
              )}
              <span className="capitalize">{job.state}</span>
              {job.current_dep && (
                <span className="text-[var(--ink-3)]">· {job.current_dep}</span>
              )}
              {progress != null && (
                <span className="ml-auto text-[12px]">{progress}%</span>
              )}
            </div>
            {progress != null && (
              <div className="mt-2 h-1.5 rounded-full bg-[var(--border)]">
                <div
                  className="h-1.5 rounded-full bg-[var(--accent)] transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            )}
            {job.dependencies.some((d) => d.status === "failed") && (
              <p role="alert" className="mt-2 text-[12px] text-[var(--danger)]">
                {job.dependencies.find((d) => d.status === "failed")?.detail ??
                  "Install failed"}
              </p>
            )}
          </div>
        )}

        {pollError && job && !TERMINAL.has(job.state) && (
          <p role="alert" className="mt-3 text-[12px] text-[var(--danger)]">
            Status polling failed: {pollError} — retrying…
          </p>
        )}

        {installError && (
          <p role="alert" className="mt-3 text-[12px] text-[var(--danger)]">
            {installError}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          {active && (
            <button
              onClick={cancelJob}
              disabled={cancelling}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] text-[var(--ink-2)] hover:bg-[var(--hover)] disabled:opacity-50"
            >
              {cancelling ? "Cancelling…" : "Cancel"}
            </button>
          )}
          {job && TERMINAL.has(job.state) ? (
            <>
              {job.state === "failed" && !jobId && (
                <button
                  onClick={async () => {
                    setRetrying(true);
                    try {
                      setJob(null);
                      setConsent(false);
                      setPlan(null);
                      setPlanError(null);
                      setInstallError(null);
                      const g = ++gen.current;
                      const p = await api.createDependencyPlan(dependencyIds);
                      if (mounted.current && gen.current === g) setPlan(p);
                    } catch (e: any) {
                      if (mounted.current)
                        setInstallError(
                          e?.message ?? "Could not create a new plan",
                        );
                    } finally {
                      if (mounted.current) setRetrying(false);
                    }
                  }}
                  disabled={retrying}
                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] text-[var(--ink-2)] hover:bg-[var(--hover)]"
                >
                  Retry
                </button>
              )}
              <button
                onClick={onClose}
                className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[13px] text-[var(--bg)] hover:opacity-90"
              >
                Done
              </button>
            </>
          ) : (
            !jobId &&
            !job && (
              <button
                onClick={startInstall}
                disabled={!plan || !consent || starting}
                className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-[13px] text-[var(--bg)] hover:opacity-90 disabled:opacity-50"
              >
                {starting ? "Starting…" : "Install now"}
              </button>
            )
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
