import { useState } from "react";
import { api } from "@/lib/api";
import { LogoFull } from "@/components/LogoFull";

export function Login() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.login(username, password);
      // Reload so App re-checks auth via api.me() with the stored bearer token
      window.location.reload();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sign-in failed");
      setLoading(false);
    }
  };

  return (
    <div
      className="flex min-h-screen items-center justify-center"
      style={{ background: "var(--surface)" }}
    >
      <div
        className="w-full max-w-sm rounded-xl border p-8 shadow-sm"
        style={{
          background: "var(--white)",
          borderColor: "var(--border)",
          boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04)",
        }}
      >
        <div className="flex flex-col items-center gap-2 pb-2">
          <LogoFull className="h-20 w-auto" color="var(--brand)" />
          <p className="text-[13px] text-[var(--ink-2)]">
            Sign in to your agents
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3 pt-4">
          <div className="space-y-1.5">
            <label
              className="block text-[12px] font-medium text-[var(--ink-2)]"
              htmlFor="username"
            >
              Username
            </label>
            <input
              id="username"
              type="text"
              placeholder="admin"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-[6px] border px-3 py-2 text-[14px] outline-none transition"
              style={{
                borderColor: "var(--border)",
                background: "var(--surface)",
                color: "var(--ink)",
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = "var(--accent)";
                e.currentTarget.style.background = "var(--white)";
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = "var(--border)";
                e.currentTarget.style.background = "var(--surface)";
              }}
            />
          </div>
          <div className="space-y-1.5">
            <label
              className="block text-[12px] font-medium text-[var(--ink-2)]"
              htmlFor="password"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-[6px] border px-3 py-2 text-[14px] outline-none transition"
              style={{
                borderColor: "var(--border)",
                background: "var(--surface)",
                color: "var(--ink)",
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = "var(--accent)";
                e.currentTarget.style.background = "var(--white)";
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = "var(--border)";
                e.currentTarget.style.background = "var(--surface)";
              }}
            />
          </div>
          {error && (
            <p
              className="rounded-[5px] px-3 py-2 text-[13px]"
              style={{
                color: "var(--danger)",
                background: "rgba(220, 38, 38, 0.06)",
              }}
            >
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-[6px] py-2.5 text-[14px] font-medium transition"
            style={{
              background: "var(--accent)",
              color: "var(--white)",
              border: "none",
              cursor: loading ? "default" : "pointer",
              opacity: loading ? 0.6 : 1,
            }}
            onMouseEnter={(e) => {
              if (!loading) e.currentTarget.style.opacity = "0.9";
            }}
            onMouseLeave={(e) => {
              if (!loading) e.currentTarget.style.opacity = "1";
            }}
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="pt-5 text-center text-[12px] text-[var(--ink-3)]">
          Default: admin / admin
        </p>
      </div>
    </div>
  );
}
