import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { api } from "./lib/api";
import type { Agent, Operator, Provider } from "./lib/types";
import { ConfirmProvider } from "./lib/confirm";
import { useConfirm } from "./lib/confirmHook";
import { Login } from "./pages/Login";
import { AgentList } from "./pages/AgentList";
import { Conversation } from "./pages/Conversation";
import { ProvidersSettings } from "./pages/ProvidersSettings";
import { KnowledgeVault } from "./pages/KnowledgeVault";
import { Skills } from "./pages/Skills";
import { Scheduler } from "./pages/Scheduler";
import { Mcps } from "./pages/Mcps";
import { Channels } from "./pages/Channels";
import { Observability } from "./pages/Observability";
import { Traces } from "./pages/Traces";
import { Notifications } from "./pages/Notifications";
import { Today } from "./pages/Today";
import { CommandPalette } from "./components/CommandPalette";
import { BootShell } from "./components/BootChrome";
import { Button } from "./components/ui/button";
import { UpdateChecker } from "./components/UpdateChecker";
import { GuidanceHost } from "./components/guidance/GuidanceHost";
import { NotificationToasts } from "./components/NotificationToasts";
import { ThemeProvider } from "./lib/theme";

export default function App() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  );
}

function AppContent() {
  const [gatewayReady, setGatewayReady] = useState<boolean | null>(null);
  const [gatewayAttempt, setGatewayAttempt] = useState(0);
  const [gatewayError, setGatewayError] = useState<string | null>(null);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [setupData, setSetupData] = useState<{ operator: Operator | null; providers: Provider[]; agents: Agent[] } | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    let attempts = 0;
    const checkGateway = async () => {
      try {
        await api.gatewayHealth();
        if (!cancelled) {
          setGatewayReady(true);
        }
      } catch {
        if (!cancelled) {
          setGatewayReady(false);
          attempts += 1;
          // Give a slow gateway a fair window, then check whether it has
          // already died (e.g. a foreign process holding the port) so the
          // screen can name the cause instead of spinning forever.
          if (attempts === 8) {
            void api.gatewayError().then((error) => {
              if (!cancelled && error) setGatewayError(error);
            });
          }
          retryTimer = setTimeout(checkGateway, 1500);
        }
      }
    };

    void checkGateway();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [gatewayAttempt]);

  useEffect(() => {
    if (!gatewayReady) return;
    api.me()
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false));
  }, [gatewayReady]);

  useEffect(() => {
    if (!authed) {
      setSetupData(null);
      return;
    }
    let cancelled = false;
    refreshSetupData().then((data) => {
      if (!cancelled) setSetupData(data);
    });
    return () => { cancelled = true; };
  }, [authed]);

  if (gatewayReady !== true) {
    return (
      <GatewayStatus
        key={gatewayAttempt}
        retrying={gatewayReady === false}
        error={gatewayError}
        onRetry={() => {
          setGatewayReady(null);
          setGatewayAttempt((attempt) => attempt + 1);
        }}
      />
    );
  }

  if (authed === null) {
    return <BootShell />;
  }

  return (
    <>
    <ConfirmProvider>
    <QuitConfirmationBridge />
    <div className="screen-in">
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={authed ? <Navigate to="/" /> : <Login />} />
        <Route path="/" element={authed ? <Today /> : <Navigate to="/login" />} />
        <Route path="/agents" element={authed ? <AgentList /> : <Navigate to="/login" />} />
        <Route
          path="/agents/:id/chat"
          element={authed ? <Conversation /> : <Navigate to="/login" />}
        />
        <Route
          path="/settings"
          element={authed ? <ProvidersSettings /> : <Navigate to="/login" />}
        />
        <Route
          path="/vault"
          element={authed ? <KnowledgeVault /> : <Navigate to="/login" />}
        />
        <Route
          path="/vault/:scope"
          element={authed ? <KnowledgeVault /> : <Navigate to="/login" />}
        />
        <Route
          path="/skills"
          element={authed ? <Skills /> : <Navigate to="/login" />}
        />
        <Route
          path="/scheduler"
          element={authed ? <Scheduler /> : <Navigate to="/login" />}
        />
        <Route
          path="/mcps"
          element={authed ? <Mcps /> : <Navigate to="/login" />}
        />
        <Route
          path="/channels"
          element={authed ? <Channels /> : <Navigate to="/login" />}
        />
        <Route
          path="/observability"
          element={authed ? <Observability /> : <Navigate to="/login" />}
        />
        <Route
          path="/traces"
          element={authed ? <Traces /> : <Navigate to="/login" />}
        />
        <Route
          path="/traces/:agentId"
          element={authed ? <Traces /> : <Navigate to="/login" />}
        />
        <Route
          path="/traces/:agentId/:runId"
          element={authed ? <Traces /> : <Navigate to="/login" />}
        />
        <Route
          path="/notifications"
          element={authed ? <Notifications /> : <Navigate to="/login" />}
        />
      </Routes>
      {setupData && authed && (
        <GuidanceHost
          operator={setupData.operator}
          providers={setupData.providers}
          agents={setupData.agents}
          onSetupRefresh={() => {
            void refreshSetupData().then(setSetupData);
          }}
        />
      )}
      {authed && <NotificationToasts />}
      {authed && <CommandPalette />}
    </BrowserRouter>
    </div>
    </ConfirmProvider>
    <UpdateChecker />
    </>
  );
}

async function refreshSetupData(): Promise<{
  operator: Operator | null;
  providers: Provider[];
  agents: Agent[];
}> {
  try {
    const [operator, providers, agents] = await Promise.all([
      api.me(),
      api.listProviders(),
      api.listAgents(),
    ]);
    return { operator, providers, agents };
  } catch {
    return { operator: null, providers: [], agents: [] };
  }
}

function QuitConfirmationBridge() {
  const { confirm } = useConfirm();

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
    let cancelled = false;
    let unlisten: (() => void) | undefined;

    void listen("caberos://quit-requested", async () => {
      if (cancelled) return;
      const shouldQuit = await confirm({
        title: "Quit CaberOS?",
        message: "Active runs will be stopped.",
        confirmLabel: "Quit",
        cancelLabel: "Keep open",
      });
      if (shouldQuit && !cancelled) await invoke("quit_app");
    }).then((cleanup) => {
      if (cancelled) cleanup();
      else unlisten = cleanup;
    }).catch(() => {});

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [confirm]);

  return null;
}

function GatewayStatus({
  retrying,
  error,
  onRetry,
}: {
  retrying: boolean;
  error?: string | null;
  onRetry: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  const [showDetails, setShowDetails] = useState(false);
  const [logPath, setLogPath] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const isDesktop =
    typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

  useEffect(() => {
    const timer = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const failed = Boolean(error);
  const slow = !failed && elapsed >= 12;

  const openLogFolder = async () => {
    try {
      const path = await api.gatewayLogPath();
      const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
      await revealItemInDir(path);
    } catch {
      // Best-effort — the diagnostics copy below still carries the path.
    }
  };

  const copyDiagnostics = async () => {
    const lines = [
      `CaberOS ${__APP_VERSION__}`,
      `Platform: ${navigator.userAgent}`,
      `Shell: ${isDesktop ? "desktop" : "web"}`,
      `Phase: ${failed ? "failed" : slow ? "slow-start" : "starting"}`,
      `Elapsed: ${elapsed}s`,
      error ? `Error: ${error}` : null,
      logPath ? `Log: ${logPath}` : null,
      `Time: ${new Date().toISOString()}`,
    ].filter(Boolean);
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard may be unavailable — the error text stays visible.
    }
  };

  const phase = failed ? "failed" : slow ? "slow" : "starting";

  return (
    <BootShell failed={failed} spinning={!failed}>
      <div
        key={phase}
        className="rise-in mt-8 flex flex-col items-center text-center"
        role="status"
        aria-live="polite"
      >
        <h1 className="text-[22px] font-semibold text-ink">
          {failed ? "CaberOS couldn't start" : slow ? "Still starting…" : "Starting CaberOS"}
        </h1>
        <p className="mt-2 max-w-sm text-[14px] text-[var(--ink-2)]">
          {failed
            ? "The local engine didn't respond. Try again, or check the details."
            : slow
              ? "This is taking longer than usual. You don't need to do anything yet."
              : "Getting your agents ready."}
        </p>

        {failed && error && (
          <p className="mt-5 w-full max-w-md rounded-xl border border-line bg-surface px-4 py-3 text-left font-mono text-[12px] text-[var(--ink-2)]">
            {error}
          </p>
        )}

        {failed && (
          <p className="mt-2 max-w-sm text-[12px] text-[var(--ink-3)]">
            Free the port and relaunch CaberOS — or if another CaberOS window is
            already running, close this one and use it.
          </p>
        )}

        <div className="mt-7 flex items-center gap-2.5">
          {failed ? (
            <>
              <Button onClick={onRetry}>Try again</Button>
              {isDesktop && (
                <Button variant="outline" onClick={() => void openLogFolder()}>
                  Open log folder
                </Button>
              )}
            </>
          ) : slow ? (
            <>
              <Button variant="outline" onClick={() => setShowDetails((v) => !v)}>
                {showDetails ? "Hide details" : "Show details"}
              </Button>
              {retrying && (
                <Button variant="outline" onClick={onRetry}>
                  Retry now
                </Button>
              )}
            </>
          ) : null}
        </div>

        {(failed || (slow && showDetails)) && (
          <button
            type="button"
            className="mt-3 text-[12px] font-medium text-accent hover:underline"
            onClick={() => {
              if (!logPath) void api.gatewayLogPath().then(setLogPath).catch(() => {});
              void copyDiagnostics();
            }}
          >
            {copied ? "Copied" : "Copy diagnostics"}
          </button>
        )}

        {slow && showDetails && (
          <div className="mt-5 w-full max-w-md rounded-xl border border-line bg-surface px-4 py-3 text-left text-[12px] text-[var(--ink-2)]">
            <p>CaberOS checks the local engine every 1.5 seconds and continues automatically.</p>
            {logPath ? (
              <p className="mt-1.5 break-all font-mono text-[11px] text-[var(--ink-3)]">{logPath}</p>
            ) : (
              <button
                type="button"
                className="mt-1.5 font-medium text-accent hover:underline"
                onClick={() => void api.gatewayLogPath().then(setLogPath).catch(() => {})}
              >
                Show log path
              </button>
            )}
          </div>
        )}
      </div>
    </BootShell>
  );
}


