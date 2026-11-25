import { useCallback, useEffect, useState } from "react";
import {
  Check,
  ClipboardCopy,
  RefreshCw,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import { openUrl } from "@/lib/openUrl";
import {
  downloadAndInstallUpdate,
  isDesktopMode,
  refreshUpdates,
  restartApp,
  resetUpdater,
  useUpdater,
} from "@/lib/updater";
import { LogoMark } from "@/components/LogoMark";

// Open URLs in the system browser when running inside Tauri,
// fall back to normal browser navigation otherwise.
async function openExternal(e: React.MouseEvent<HTMLAnchorElement>) {
  const href = e.currentTarget.href;
  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    e.preventDefault();
    await openUrl(href);
  }
}

export function AboutTab() {
  const [version, setVersion] = useState<string>("...");
  const [copied, setCopied] = useState(false);
  const updater = useUpdater();
  const { toast } = useConfirm();

  useEffect(() => {
    // In desktop mode, read from Tauri. In web mode, fetch from the backend.
    const isTauri =
      typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
    if (isTauri) {
      // Tauri v2 — read the app version from the package info
      import("@tauri-apps/api/app")
        .then((mod) => mod.getVersion())
        .then(setVersion)
        .catch(() => {
          // Fallback to backend endpoint
          fetch(`${import.meta.env.VITE_API_BASE || ""}/api/version`)
            .then((r) => r.json())
            .then((data) => setVersion(data.version))
            .catch(() => setVersion("unknown"));
        });
    } else {
      fetch(`${import.meta.env.VITE_API_BASE || ""}/api/version`)
        .then((r) => r.json())
        .then((data) => setVersion(data.version))
        .catch(() => setVersion("unknown"));
    }
  }, []);

  const handleCheckUpdates = useCallback(async () => {
    await refreshUpdates().catch(() => {});
  }, []);

  const handleDownload = useCallback(async () => {
    await downloadAndInstallUpdate().catch(() => {});
  }, []);

  const handleRestart = useCallback(async () => {
    await restartApp().catch(() => {});
  }, []);

  const copyDiagnostics = async () => {
    const isTauri =
      typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
    const lines = [
      `CaberOS ${version}`,
      `Shell: ${isTauri ? "Tauri desktop" : "web"}`,
      `User agent: ${navigator.userAgent}`,
      `API: ${api.baseURL || window.location.origin}`,
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast("Copy failed — clipboard permission denied");
    }
  };

  const statusLine = (() => {
    switch (updater.status) {
      case "idle":
        return "Check for updates to see if you're current";
      case "checking":
        return "Checking…";
      case "up-to-date":
        return isDesktopMode()
          ? "You're up to date"
          : "Update checks run in the desktop app";
      case "available":
        return `v${updater.info?.latestVersion} is available`;
      case "downloading":
        return updater.progress.downloaded && updater.progress.total
          ? `Downloading… ${Math.round((updater.progress.downloaded / updater.progress.total) * 100)}%`
          : "Downloading…";
      case "installing":
        return "Installing update…";
      case "ready":
        return "Update ready — restart to apply";
      case "error":
        return updater.error || "Update check failed";
    }
  })();

  const LINKS = [
    {
      label: "GitHub repository",
      sub: "Source and releases",
      href: "https://github.com/cabernect/caberos",
    },
    {
      label: "Report an issue",
      sub: "Include your diagnostics",
      href: "https://github.com/cabernect/caberos/issues",
    },
    {
      label: "Security",
      sub: "How to report a vulnerability",
      href: "https://github.com/cabernect/caberos/security",
    },
  ];

  return (
    <div className="max-w-4xl space-y-8">
      {/* CaberOS */}
      <section id="caberos">
        <div
          className="flex flex-wrap items-center gap-4 rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <span
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl"
            style={{ background: "var(--accent-bg)" }}
          >
            <LogoMark className="h-8 w-8" color="var(--brand)" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-[16px] font-semibold text-[var(--ink)]">
              CaberOS
            </h2>
            <p className="text-[12px] text-[var(--ink-3)]">
              Local-first AI Agent Operating System
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px]">
              <span className="font-mono font-medium text-[var(--ink)]">
                v{version}
              </span>
              <span
                className="text-[var(--ink-3)]"
                style={{
                  color:
                    updater.status === "up-to-date" ||
                    updater.status === "available" ||
                    updater.status === "ready"
                      ? "var(--accent)"
                      : updater.status === "error"
                        ? "var(--danger)"
                        : undefined,
                }}
              >
                · {statusLine}
              </span>
            </p>
          </div>
          <div className="flex w-full shrink-0 flex-wrap items-center gap-2 sm:w-auto">
            {["idle", "up-to-date", "error", "checking"].includes(updater.status) && (
              <button
                onClick={handleCheckUpdates}
                disabled={updater.status === "checking"}
                className="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:cursor-not-allowed disabled:opacity-60"
                style={{ borderColor: "var(--border)" }}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {updater.status === "checking" ? "Checking…" : "Check for updates"}
              </button>
            )}
            {updater.status === "available" && (
              <>
                <button
                  onClick={() => resetUpdater()}
                  className="rounded-lg border px-3 py-2 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                  style={{ borderColor: "var(--border)" }}
                >
                  Later
                </button>
                <button
                  onClick={handleDownload}
                  className="rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90"
                  style={{ background: "var(--ink)", color: "var(--white)" }}
                >
                  Download update
                </button>
              </>
            )}
            {updater.status === "ready" && (
              <button
                onClick={handleRestart}
                className="rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90"
                style={{ background: "var(--ink)", color: "var(--white)" }}
              >
                Restart now
              </button>
            )}
          </div>
        </div>
      </section>

      {/* Built with */}
      <section id="built-with">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Built with
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          What's running under the hood.
        </p>
        <div
          className="rounded-xl p-5"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="grid grid-cols-2 gap-x-6 gap-y-4">
            {[
              ["Backend", "Python 3.12, FastAPI, SQLAlchemy, LiteLLM"],
              ["Frontend", "React 19, Vite, Tailwind CSS 4, Tauri 2"],
              ["Database", "SQLite (WAL) default, PostgreSQL optional"],
              ["Sandbox", "Seatbelt · bubblewrap · Docker · MXC (Windows)"],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-[12px] text-[var(--ink-3)]">{label}</p>
                <p className="mt-0.5 text-[13px] font-medium text-[var(--ink)]">
                  {value}
                </p>
              </div>
            ))}
          </div>
          <div
            className="mt-5 border-t pt-4"
            style={{ borderColor: "var(--border-soft)" }}
          >
            <button
              onClick={copyDiagnostics}
              className="flex items-center gap-1.5 rounded-lg border px-3 py-2 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border)" }}
            >
              {copied ? (
                <Check className="h-3.5 w-3.5 text-[var(--accent)]" />
              ) : (
                <ClipboardCopy className="h-3.5 w-3.5" />
              )}
              {copied ? "Copied" : "Copy diagnostics"}
            </button>
            <p className="mt-1.5 text-[11px] text-[var(--ink-3)]">
              Version, system and shell details for bug reports.
            </p>
          </div>
        </div>
      </section>

      {/* Links */}
      <section id="links">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">Links</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Help and source.
        </p>
        <div
          className="overflow-hidden rounded-xl border"
          style={{
            borderColor: "var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          {LINKS.map((l) => (
            <a
              key={l.label}
              href={l.href}
              target="_blank"
              rel="noopener noreferrer"
              onClick={openExternal}
              className="flex items-center justify-between border-b px-5 py-3 transition last:border-0 hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border-soft)" }}
            >
              <span className="flex items-baseline gap-3">
                <span className="text-[13px] font-medium text-[var(--ink)]">
                  {l.label}
                </span>
                <span className="text-[12px] text-[var(--ink-3)]">{l.sub}</span>
              </span>
              <span className="text-[12px] font-medium text-[var(--accent)]">
                Open
              </span>
            </a>
          ))}
        </div>
      </section>

      {/* License */}
      <section id="license">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">License</h2>
        <div
          className="mt-3 rounded-xl p-5 text-[13px] text-[var(--ink-2)]"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <p>MIT License. Copyright (c) 2026 HoangPH25.</p>
          <p className="mt-1 text-[var(--ink-3)]">
            Fonts: Geist and Geist Mono (SIL Open Font License 1.1).
          </p>
        </div>
      </section>
    </div>
  );
}

