import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { api } from "./lib/api";
import { Login } from "./pages/Login";
import { AgentList } from "./pages/AgentList";
import { Conversation } from "./pages/Conversation";

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
        <Route path="/login" element={authed ? <Navigate to="/" /> : <Login />} />
        <Route path="/" element={authed ? <AgentList /> : <Navigate to="/login" />} />
        <Route
          path="/agents/:id/chat"
          element={authed ? <Conversation /> : <Navigate to="/login" />}
        />
      </Routes>
    </BrowserRouter>
  );
}
