import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { api } from "./lib/api";
import { ConfirmProvider } from "./lib/confirm";
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
import { UpdateChecker } from "./components/UpdateChecker";

export default function App() {
  const [gatewayReady, setGatewayReady] = useState<boolean | null>(null);
  const [gatewayAttempt, setGatewayAttempt] = useState(0);
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const checkGateway = async () => {
      try {
        await api.gatewayHealth();
        if (!cancelled) {
          setGatewayReady(true);
        }
      } catch {
        if (!cancelled) {
          setGatewayReady(false);
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

  if (gatewayReady !== true) {
    return (
      <GatewayStatus
        retrying={gatewayReady === false}
        onRetry={() => {
          setGatewayReady(null);
          setGatewayAttempt((attempt) => attempt + 1);
        }}
      />
    );
  }

  if (authed === null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-background)]">
        <p className="text-sm text-[var(--color-secondary)]">Loading...</p>
      </div>
    );
  }

  return (
    <>
    <ConfirmProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={authed ? <Navigate to="/agents" /> : <Login />} />
        <Route path="/" element={<Navigate to="/agents" />} />
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
      </Routes>
    </BrowserRouter>
    </ConfirmProvider>
    <UpdateChecker />
    </>
  );
}

function GatewayStatus({ retrying, onRetry }: { retrying: boolean; onRetry: () => void }) {
  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[var(--color-background)] px-6"
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-col items-center text-center">
        <div className="relative h-12 w-12" aria-hidden="true">
          <div className="absolute inset-0 rounded-full border-2 border-[var(--border)]" />
          <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-[var(--accent)]" />
        </div>
        <h1 className="mt-6 text-lg font-semibold text-[var(--ink)]">Starting CaberOS</h1>
        <p className="mt-2 text-sm text-[var(--ink-2)]">
          {retrying ? "Starting the local gateway…" : "Preparing your workspace…"}
        </p>
        <p className="mt-2 max-w-sm text-xs text-[var(--ink-3)]">
          CaberOS will continue automatically when the gateway is ready.
        </p>
        {retrying && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-8 rounded-md border px-4 py-2 text-sm font-medium transition-colors"
            style={{ borderColor: "var(--border)", color: "var(--ink-2)" }}
          >
            Retry now
          </button>
        )}
      </div>
    </div>
  );
}
