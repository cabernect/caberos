import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { Operator } from "@/lib/types";
import type { ThemeMode } from "@/lib/theme";
import { useTheme } from "@/lib/themeHook";
import {
  resetGuidance,
  resetIntroFlags,
  setTourState,
} from "@/components/guidance/guidanceState";
import { NotificationPrefsForm } from "@/components/NotificationPrefsForm";
import { OptionalToolsAndRuntimes } from "@/components/OptionalToolsAndRuntimes";
import { ContextCaptureSettings } from "@/components/ContextCaptureSettings";
import { SettingsSection } from "./shared";

export function GeneralTab({
  operator,
  loading,
  onLogout,
  onOperatorChanged,
}: {
  operator: Operator | null;
  loading: boolean;
  onLogout: () => void;
  onOperatorChanged: (op: Operator) => void;
}) {
  const { mode, setMode, resolvedTheme } = useTheme();

  return (
    <div className="max-w-4xl space-y-6">
      <SettingsSection
        id="operator"
        title="Operator"
        subtitle="The account running this workspace."
      >
        {loading ? (
          <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>
        ) : operator ? (
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div
                className="flex h-10 w-10 items-center justify-center rounded-lg text-[14px] font-semibold"
                style={{
                  background: "var(--accent-bg)",
                  color: "var(--accent)",
                }}
              >
                {operator.username.charAt(0).toUpperCase()}
              </div>
              <div>
                <p className="text-[14px] font-medium text-[var(--ink)]">
                  {operator.username}
                </p>
                <p className="text-[12px] text-[var(--ink-3)]">Administrator</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border)", color: "var(--ink)" }}
            >
              Sign out
            </button>
          </div>
        ) : (
          <p className="text-[13px] text-[var(--ink-2)]">Not logged in</p>
        )}
      </SettingsSection>

      {operator && (
        <SettingsSection
          id="sign-in"
          title="Sign-in"
          subtitle={
            operator.must_change_password
              ? "This workspace still uses the default login — set your own."
              : "Change the password used to open this workspace."
          }
        >
          <CredentialsForm operator={operator} onChanged={onOperatorChanged} />
        </SettingsSection>
      )}

      <SettingsSection
        id="appearance"
        title="Appearance"
        subtitle="Pick how CaberOS looks."
      >
        <ThemeSwatches mode={mode} onChange={setMode} />
        <p className="mt-3 text-[12px] text-[var(--ink-3)]">
          System follows your operating-system setting. Currently using{" "}
          {resolvedTheme} mode.
        </p>
        <HintReset />
      </SettingsSection>

      <SettingsSection
        id="notifications"
        title="Notifications"
        subtitle="Choose what alerts you and when."
      >
        <NotificationPrefsForm />
      </SettingsSection>

      <SettingsSection
        id="capture"
        title="Request Capture"
        subtitle="How long model request and response bodies are kept."
      >
        <ContextCaptureSettings />
      </SettingsSection>

      <SettingsSection
        id="guidance"
        title="Guidance"
        subtitle="Replay the welcome tour and per-page intros."
      >
        <ReplayGuidance />
      </SettingsSection>

      <div id="tools">
        <OptionalToolsAndRuntimes />
      </div>
    </div>
  );
}

/** Re-arms tour + page intros and starts the spotlight tour from Today. */
function ReplayGuidance() {
  const navigate = useNavigate();
  const [replayed, setReplayed] = useState(false);
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-[13px] font-medium text-[var(--ink)]">
          Product tour
        </p>
        <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
          Replay the three-step Today tour, and re-show page hints on your
          next visit to each page.
        </p>
      </div>
      <button
        type="button"
        onClick={() => {
          resetGuidance();
          setTourState("active");
          setReplayed(true);
          navigate("/");
        }}
        className="rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-[var(--hover)]"
        style={{ borderColor: "var(--border)", color: "var(--ink)" }}
      >
        {replayed ? "Tour restarted" : "Replay tour"}
      </button>
    </div>
  );
}

/** Sign-in — change workspace credentials. While the default login is still
 * active (must_change_password), this calls setup-credentials — no old
 * password required, username editable. Afterwards it calls change-password,
 * which needs the current password; the username stays fixed (the backend
 * has no rename path). */
function CredentialsForm({
  operator,
  onChanged,
}: {
  operator: Operator;
  onChanged: (op: Operator) => void;
}) {
  const { toast } = useConfirm();
  const firstRun = operator.must_change_password;
  const [username, setUsername] = useState(operator.username);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputStyle = {
    borderColor: "var(--border)",
    background: "var(--surface)",
    color: "var(--ink)",
  };
  const inputCls =
    "w-full rounded-md border px-3 py-2 text-[13px] transition-colors focus:outline-none focus:border-[var(--accent)]";
  const labelCls = "mb-1 block text-[12px] font-medium text-[var(--ink-2)]";

  const submit = async () => {
    setError(null);
    if (next.length < 8)
      return setError("New password needs at least 8 characters.");
    if (next !== confirm) return setError("Passwords don't match.");
    setBusy(true);
    try {
      if (firstRun) {
        const op = await api.setupCredentials({
          username: username.trim() || undefined,
          new_password: next,
        });
        onChanged(op);
        toast("Sign-in updated");
      } else {
        await api.changePassword({
          old_password: current,
          new_password: next,
        });
        toast("Password updated");
      }
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update sign-in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="max-w-sm space-y-3"
    >
      {firstRun ? (
        <label className="block">
          <span className={labelCls}>Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={inputCls}
            style={inputStyle}
            autoComplete="username"
          />
        </label>
      ) : (
        <label className="block">
          <span className={labelCls}>Current password</span>
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={inputCls}
            style={inputStyle}
            autoComplete="current-password"
          />
        </label>
      )}
      <label className="block">
        <span className={labelCls}>New password</span>
        <input
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className={inputCls}
          style={inputStyle}
          autoComplete="new-password"
        />
      </label>
      <label className="block">
        <span className={labelCls}>Confirm new password</span>
        <input
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className={inputCls}
          style={inputStyle}
          autoComplete="new-password"
        />
      </label>
      {error && (
        <p role="alert" className="text-[12px]" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      )}
      <div>
        <button
          type="submit"
          disabled={
            busy || !next || !confirm || (!firstRun && !current)
          }
          className="rounded-md px-4 py-2 text-[12px] font-medium transition-opacity disabled:opacity-50"
          style={{ background: "var(--ink)", color: "var(--white)" }}
        >
          {busy ? "Saving…" : firstRun ? "Set sign-in" : "Update password"}
        </button>
      </div>
    </form>
  );
}

/** Appearance → "Show page hints" — clears the per-page dismissals and the
 * global don't-show-hints flag so intro cards come back on next visit. */
function HintReset() {
  const [restored, setRestored] = useState(false);
  return (
    <div className="mt-4 flex items-center justify-between gap-4 border-t pt-4" style={{ borderColor: "var(--border-soft, var(--border))" }}>
      <div>
        <p className="text-[13px] font-medium text-[var(--ink)]">Page hints</p>
        <p className="mt-0.5 text-[12px] text-[var(--ink-3)]">
          Intro cards at the top of Agents, Scheduler, Traces and other pages.
        </p>
      </div>
      <button
        type="button"
        onClick={() => {
          resetIntroFlags();
          setRestored(true);
        }}
        className="rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors hover:bg-[var(--hover)]"
        style={{ borderColor: "var(--border)", color: "var(--ink)" }}
      >
        {restored ? "Hints back on" : "Show page hints"}
      </button>
    </div>
  );
}

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

function MiniAppFrame({ dark = false }: { dark?: boolean }) {
  // data-theme-preview scopes the real theme tokens to this subtree (see
  // index.css), so the swatch always mirrors the actual palette.
  return (
    <div
      className="flex h-full w-full"
      data-theme-preview={dark ? "dark" : "light"}
      style={{ background: "var(--ground)" }}
    >
      <div
        className="w-[28%]"
        style={{
          background: "var(--sunken)",
          borderRight: "1px solid var(--line)",
        }}
      />
      <div className="flex flex-1 flex-col gap-1 p-1.5">
        <div
          className="h-1.5 w-3/5 rounded-sm"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
          }}
        />
        <div
          className="h-1.5 w-4/5 rounded-sm"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
          }}
        />
        <div
          className="mt-auto h-1.5 w-2/5 rounded-sm"
          style={{ background: "var(--track)" }}
        />
      </div>
    </div>
  );
}

function ThemeSwatches({
  mode,
  onChange,
}: {
  mode: ThemeMode;
  onChange: (mode: ThemeMode) => void;
}) {
  return (
    <div
      className="grid grid-cols-3 gap-3"
      role="radiogroup"
      aria-label="Theme"
    >
      {THEME_OPTIONS.map((option) => {
        const selected = mode === option.value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className="group text-left"
          >
            <span
              className="relative block h-20 overflow-hidden rounded-lg border-2 transition-colors"
              style={{
                borderColor: selected ? "var(--accent)" : "var(--border)",
              }}
            >
              {option.value === "system" ? (
                <>
                  <MiniAppFrame />
                  <span
                    className="absolute inset-0"
                    style={{
                      clipPath: "polygon(58% 0, 100% 0, 100% 100%, 38% 100%)",
                    }}
                  >
                    <MiniAppFrame dark />
                  </span>
                </>
              ) : (
                <MiniAppFrame dark={option.value === "dark"} />
              )}
            </span>
            <span className="mt-1.5 flex items-center gap-1.5 text-[12px] text-[var(--ink)]">
              <span
                className="flex h-3 w-3 items-center justify-center rounded-full border"
                style={{
                  borderColor: selected ? "var(--accent)" : "var(--ink-3)",
                }}
              >
                {selected && (
                  <span
                    className="h-1.5 w-1.5 rounded-full"
                    style={{ background: "var(--accent)" }}
                  />
                )}
              </span>
              <span className={selected ? "font-semibold" : "font-medium"}>
                {option.label}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

