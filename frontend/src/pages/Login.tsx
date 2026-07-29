import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot } from "lucide-react";
import { api } from "../lib/api";

export function Login() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.login(username, password);
      navigate("/");
    } catch {
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-background)]">
      <div className="w-full max-w-sm space-y-6 p-8">
        <div className="flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--color-surface)]">
            <Bot className="h-7 w-7 text-[var(--color-cta)]" />
          </div>
          <h1 className="text-[var(--text-2xl)] font-bold text-[var(--color-text)]">
            CaberOS
          </h1>
          <p className="text-sm text-[var(--color-secondary)]">
            Sign in to your agents
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              type="text"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-[var(--color-text)] outline-none focus:border-[var(--color-cta)]"
            />
          </div>
          <div>
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-[var(--color-text)] outline-none focus:border-[var(--color-cta)]"
            />
          </div>
          {error && (
            <p className="text-sm text-[var(--color-danger)]">{error}</p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full cursor-pointer rounded-[var(--radius-md)] bg-[var(--color-cta)] px-4 py-3 font-medium text-white transition hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="text-center text-xs text-[var(--color-secondary)]">
          Default: admin / admin
        </p>
      </div>
    </div>
  );
}
