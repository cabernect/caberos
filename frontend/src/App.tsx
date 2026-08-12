import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { api } from "./lib/api";
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

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    api.me()
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false));
  }, []);

  if (authed === null) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-background)]">
        <p className="text-sm text-[var(--color-secondary)]">Loading...</p>
      </div>
    );
  }

  return (
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
  );
}
