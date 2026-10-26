import { useState } from "react";
import { api } from "@/lib/api";
import type { Operator } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { BootShell } from "@/components/BootChrome";

const fieldClass =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-[14px] text-ink outline-none transition-colors focus:border-[var(--accent)]";

export function Login() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [freshOperator, setFreshOperator] = useState<Operator | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = await api.login(username, password);
      // First run: the default login just worked — offer to replace it right
      // here instead of reloading into an onboarding step that asks again.
      if (resp.must_change_password) {
        setFreshOperator(resp.operator);
        setLoading(false);
        return;
      }
      // Reload so App re-checks auth via api.me() with the stored bearer token
      window.location.reload();
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sign-in failed");
      setLoading(false);
    }
  };

  if (freshOperator) {
    return (
      <BootShell spinning={false}>
        <FirstRunCredentials operator={freshOperator} />
      </BootShell>
    );
  }

  return (
    <BootShell spinning={false}>
      <div className="rise-in mt-8 flex w-full max-w-sm flex-col items-center">
        <h1 className="text-[22px] font-semibold text-ink">Welcome back</h1>
        <p className="mt-1.5 text-[14px] text-[var(--ink-2)]">
          Sign in to run your agents.
        </p>

        <form
          onSubmit={handleSubmit}
          className="mt-7 w-full space-y-3.5 rounded-xl border border-line bg-surface p-5"
        >
          <div className="space-y-1.5">
            <label className="block text-[12px] font-medium text-[var(--ink-2)]" htmlFor="username">
              Username
            </label>
            <input
              id="username"
              type="text"
              placeholder="admin"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className={fieldClass}
            />
          </div>
          <div className="space-y-1.5">
            <label className="block text-[12px] font-medium text-[var(--ink-2)]" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={fieldClass}
            />
          </div>
          {error && (
            <p className="rounded-lg bg-danger-tint px-3 py-2 text-[13px] text-danger">{error}</p>
          )}
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "Signing in…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-4 text-[12px] text-[var(--ink-3)]">Default: admin / admin</p>
      </div>
    </BootShell>
  );
}

/** First-run stage, shown after a successful default login — replace
 * admin/admin before entering the app. Calls setup-credentials (the session
 * is already authenticated); skipping keeps the default login and the
 * onboarding wizard will offer the same step once more. */
function FirstRunCredentials({ operator }: { operator: Operator }) {
  const [username, setUsername] = useState(operator.username);
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (next.length < 8)
      return setError("New password needs at least 8 characters.");
    if (next !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    try {
      await api.setupCredentials({
        username: username.trim() || undefined,
        new_password: next,
      });
      window.location.reload();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not set credentials.",
      );
      setBusy(false);
    }
  };

  return (
    <div className="rise-in mt-8 flex w-full max-w-sm flex-col items-center">
      <h1 className="text-[22px] font-semibold text-ink">Set your sign-in</h1>
      <p className="mt-1.5 text-center text-[14px] text-[var(--ink-2)]">
        This is the first sign-in — replace the default login before you
        continue.
      </p>

      <form
        onSubmit={submit}
        className="mt-7 w-full space-y-3.5 rounded-xl border border-line bg-surface p-5"
      >
        <div className="space-y-1.5">
          <label
            className="block text-[12px] font-medium text-[var(--ink-2)]"
            htmlFor="new-username"
          >
            Username
          </label>
          <input
            id="new-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={fieldClass}
            autoComplete="username"
          />
        </div>
        <div className="space-y-1.5">
          <label
            className="block text-[12px] font-medium text-[var(--ink-2)]"
            htmlFor="new-password"
          >
            New password
          </label>
          <input
            id="new-password"
            type="password"
            placeholder="••••••••"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className={fieldClass}
            autoComplete="new-password"
            autoFocus
          />
        </div>
        <div className="space-y-1.5">
          <label
            className="block text-[12px] font-medium text-[var(--ink-2)]"
            htmlFor="confirm-password"
          >
            Confirm password
          </label>
          <input
            id="confirm-password"
            type="password"
            placeholder="••••••••"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={fieldClass}
            autoComplete="new-password"
          />
        </div>
        {error && (
          <p className="rounded-lg bg-danger-tint px-3 py-2 text-[13px] text-danger">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy || !next || !confirm} className="w-full">
          {busy ? "Setting…" : "Set sign-in"}
        </Button>
      </form>

      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-4 cursor-pointer text-[12px] text-[var(--ink-3)] underline"
        style={{ background: "none", border: "none" }}
      >
        Skip for now — keep the default login
      </button>
    </div>
  );
}
