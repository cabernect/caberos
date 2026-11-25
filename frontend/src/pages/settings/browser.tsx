import { useCallback, useEffect, useState } from "react";
import {
  Check,
  Play,
  Plus,
  Save,
  Search,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import { CHROME_PATH_EXAMPLE } from "@/lib/platform";

// --- Browser automation (W4) -----------------------------------------------

interface BrowserRuntime {
  status: string;
  binary?: string;
  managed?: boolean;
  managed_binary?: string | null;
  source?: "override" | "system" | "managed";
  version?: string;
  installable?: boolean;
  detail?: string;
  install_progress?: {
    phase: string;
    downloaded: number;
    total: number | null;
  } | null;
}

interface BrowserProfileRow {
  id: string;
  name: string;
  allowed_domains: string[];
  description: string | null;
}

export function BrowserTab() {
  const { confirm } = useConfirm();
  const [runtime, setRuntime] = useState<BrowserRuntime | null>(null);
  const [binaryOverride, setBinaryOverride] = useState("");
  const [overrideSource, setOverrideSource] = useState<
    "env" | "persisted" | "none"
  >("none");
  const [resolvedBinary, setResolvedBinary] = useState<string | null>(null);
  const [detected, setDetected] = useState<{ name: string; path: string }[]>(
    [],
  );
  const [profiles, setProfiles] = useState<BrowserProfileRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [newName, setNewName] = useState("");
  const [newDomains, setNewDomains] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [anySite, setAnySite] = useState(false);
  const [customPath, setCustomPath] = useState("");
  const [pickingCustom, setPickingCustom] = useState(false);
  const [pickingBuiltin, setPickingBuiltin] = useState(false);
  const [showLocation, setShowLocation] = useState(false);
  const [testingWindow, setTestingWindow] = useState(false);
  const [privateAllowlist, setPrivateAllowlist] = useState("");
  const [allowlistPinned, setAllowlistPinned] = useState(false);
  const [savingAllowlist, setSavingAllowlist] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [settings, profileList, network] = await Promise.all([
        api.getBrowserSettings(),
        api.listBrowserProfiles(),
        api.getNetworkSettings(),
      ]);
      setPrivateAllowlist(network.web_private_allowlist.join("\n"));
      setAllowlistPinned(network.pinned);
      setBinaryOverride(settings.binary_override);
      setOverrideSource(settings.override_source);
      setResolvedBinary(settings.resolved_binary);
      setDetected(settings.detected);
      if (
        settings.binary_override &&
        !settings.detected.some((d) => d.path === settings.binary_override)
      ) {
        setCustomPath(settings.binary_override);
      }
      setRuntime(settings.runtime);
      setProfiles(profileList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const applyOverride = async (path: string) => {
    setError(null);
    setNotice(null);
    try {
      const result = await api.updateBrowserSettings(path.trim());
      setBinaryOverride(result.binary_override);
      setOverrideSource(result.override_source);
      setResolvedBinary(result.resolved_binary);
      setDetected(result.detected);
      setRuntime(result.runtime);
      setNotice(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const managedBinary = runtime?.managed_binary ?? null;
  const engineValue = pickingCustom
    ? "custom"
    : pickingBuiltin
      ? "builtin"
      : !binaryOverride
        ? "auto"
        : managedBinary && binaryOverride === managedBinary
          ? "builtin"
          : detected.some((d) => d.path === binaryOverride)
            ? binaryOverride
            : "custom";

  const install = async () => {
    setInstalling(true);
    setError(null);
    const poller = setInterval(() => {
      void api
        .getBrowserSettings()
        .then((s) => setRuntime(s.runtime))
        .catch(() => {});
    }, 800);
    try {
      const result = await api.installBrowserRuntime();
      if (
        (result.status === "installed" || result.status === "ok") &&
        result.binary
      ) {
        setPickingBuiltin(false);
        await applyOverride(result.binary);
        setNotice("Browser installed — agents can now browse the web.");
      } else {
        setNotice(result.detail ?? `Status: ${result.status}`);
        await loadAll();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      clearInterval(poller);
      setInstalling(false);
    }
  };

  const removeRuntime = async () => {
    const ok = await confirm({
      title: "Remove built-in browser?",
      message:
        "Agents won't be able to browse until you install it again or pick your own browser.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) {
      return;
    }
    try {
      await api.removeBrowserRuntime();
      if (managedBinary && binaryOverride === managedBinary) {
        await applyOverride("");
      }
      setNotice("Built-in browser removed.");
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const createProfile = async () => {
    setError(null);
    try {
      const domains = anySite
        ? []
        : newDomains
            .split(",")
            .map((d) => d.trim())
            .filter(Boolean);
      await api.createBrowserProfile(
        newName.trim(),
        domains,
        newDesc.trim() || undefined,
      );
      setNewName("");
      setNewDomains("");
      setNewDesc("");
      setAnySite(false);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const openTestWindow = async () => {
    setTestingWindow(true);
    setError(null);
    try {
      const r = await api.openBrowserTestWindow();
      setNotice(
        `Test window opened — it closes by itself after ~${r.auto_close_seconds}s, or when you close it.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTestingWindow(false);
    }
  };

  const removeProfile = async (id: string) => {
    const ok = await confirm({
      title: "Forget this saved login?",
      message: "The agent will be logged out of these sites.",
      confirmLabel: "Forget",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteBrowserProfile(id);
      await loadAll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (loading) {
    return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;
  }

  const status = runtime?.status ?? "runtime_unavailable";
  const available = status === "ok" || status === "installed";

  const selectEngine = (v: string) => {
    setPickingCustom(false);
    setPickingBuiltin(false);
    if (v === "custom") {
      setPickingCustom(true);
      setCustomPath(
        binaryOverride &&
          binaryOverride !== managedBinary &&
          !detected.some((d) => d.path === binaryOverride)
          ? binaryOverride
          : "",
      );
    } else if (v === "builtin" && !managedBinary) {
      setPickingBuiltin(true);
    } else {
      void applyOverride(
        v === "auto" ? "" : v === "builtin" ? (managedBinary ?? "") : v,
      );
    }
  };

  const engineRow = (value: string, title: string, sub: string) => (
    <label
      key={value}
      className={`flex cursor-pointer items-start gap-2.5 border-b py-2.5 last:border-0 ${
        overrideSource === "env" ? "cursor-not-allowed opacity-60" : ""
      }`}
      style={{ borderColor: "var(--border-soft)" }}
    >
      <input
        type="radio"
        name="browser-engine"
        value={value}
        checked={engineValue === value}
        disabled={overrideSource === "env"}
        onChange={() => selectEngine(value)}
        className="mt-0.5 h-4 w-4 shrink-0"
        style={{ accentColor: "var(--accent)" }}
      />
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-[var(--ink)]">
          {title}
        </span>
        <span className="block text-[11px] text-[var(--ink-3)] break-all">
          {sub}
        </span>
      </span>
    </label>
  );

  return (
    <div className="max-w-4xl space-y-8">
      {error && (
        <div
          className="rounded-lg border px-4 py-3 text-[12px]"
          style={{
            borderColor: "var(--danger)",
            background: "color-mix(in srgb, var(--danger) 10%, transparent)",
            color: "var(--danger)",
          }}
        >
          {error}
        </div>
      )}
      {notice && (
        <div
          className="rounded-lg border px-4 py-3 text-[12px]"
          style={{
            borderColor: "var(--border)",
            background: "var(--accent-bg)",
            color: "var(--ink)",
          }}
        >
          {notice}
        </div>
      )}

      {/* Agent browser */}
      <section id="agent-browser">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Agent browser
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Choose the browser agents use to open websites.
        </p>
        <div
          className="rounded-xl p-5 space-y-3"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[13px] font-medium text-[var(--ink)]">
                {available
                  ? runtime?.managed
                    ? "Built-in browser"
                    : runtime?.source === "system"
                      ? "Your browser (auto-detected)"
                      : "Your own browser"
                  : "No browser set up"}
              </p>
              <p className="mt-0.5 text-[12px] text-[var(--ink-3)] break-all">
                {available
                  ? runtime?.managed
                    ? `CaberOS's own copy of Chrome ${runtime.version ?? ""} — kept separate from your personal browser.`.trim()
                    : runtime?.source === "system"
                      ? `${resolvedBinary} — found on this machine, nothing to install`
                      : resolvedBinary
                  : "Install a browser and your agents can open websites, fill forms, and read pages for you."}
              </p>
            </div>
            <span
              className="rounded-full px-3 py-1 text-[11px] font-medium shrink-0"
              style={
                available
                  ? {
                      background:
                        "color-mix(in srgb, var(--success) 15%, transparent)",
                      color: "var(--success)",
                    }
                  : {
                      background:
                        "color-mix(in srgb, var(--warning) 15%, transparent)",
                      color: "var(--warning)",
                    }
              }
            >
              {available ? "Ready" : "Not installed"}
            </span>
          </div>

          {/* Engine radios */}
          <div
            className="border-t pt-3"
            style={{ borderColor: "var(--border)" }}
          >
            <p className="mb-1 text-[12px] font-medium text-[var(--ink)]">
              Browser engine
            </p>
            <div>
              {engineRow(
                "auto",
                "Automatic",
                "Use a browser already on this machine, otherwise the built-in one.",
              )}
              {detected.map((d) => engineRow(d.path, d.name, d.path))}
              {engineRow(
                "builtin",
                "CaberOS browser (built-in)",
                managedBinary
                  ? "Always use the built-in copy."
                  : "Not installed — downloads on select.",
              )}
              {engineRow(
                "custom",
                "Custom path",
                "Point to a browser CaberOS didn't detect.",
              )}
            </div>

            {engineValue === "builtin" && !managedBinary && (
              <div className="mt-2 space-y-2">
                <div className="flex items-center gap-2">
                  <button
                    onClick={install}
                    disabled={installing}
                    className="cursor-pointer rounded-md px-3 py-1.5 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
                    style={{
                      background: "var(--accent)",
                      color: "var(--white)",
                    }}
                  >
                    {installing
                      ? "Installing…"
                      : "Download & install (~160 MB)"}
                  </button>
                  {!installing && (
                    <p className="text-[11px] text-[var(--ink-3)]">
                      CaberOS's own private copy of Chrome — one-time download.
                    </p>
                  )}
                </div>
                {installing &&
                  (() => {
                    const p = runtime?.install_progress;
                    const mb = (n: number) => (n / 1048576).toFixed(0);
                    const phaseLabel =
                      p?.phase === "downloading"
                        ? p.total
                          ? `Downloading… ${mb(p.downloaded)} / ${mb(p.total)} MB`
                          : `Downloading… ${mb(p.downloaded)} MB`
                        : p?.phase === "extracting"
                          ? "Extracting…"
                          : p?.phase === "verifying"
                            ? "Verifying install…"
                            : "Preparing download…";
                    const pct =
                      p?.phase === "downloading" && p.total
                        ? Math.min(100, (p.downloaded / p.total) * 100)
                        : null;
                    return (
                      <div className="space-y-1.5">
                        <div
                          className="h-1.5 w-full overflow-hidden rounded-full"
                          style={{ background: "var(--accent-bg)" }}
                        >
                          {pct !== null ? (
                            <div
                              className="h-full rounded-full transition-[width] duration-300"
                              style={{
                                width: `${pct}%`,
                                background: "var(--accent)",
                              }}
                            />
                          ) : (
                            <div
                              className="pulse h-full w-1/3 rounded-full"
                              style={{ background: "var(--accent)" }}
                            />
                          )}
                        </div>
                        <p className="text-[11px] text-[var(--ink-3)]">
                          {phaseLabel} — keep this tab open.
                        </p>
                      </div>
                    );
                  })()}
              </div>
            )}
            {engineValue === "custom" && (
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="text"
                  value={customPath}
                  onChange={(e) => setCustomPath(e.target.value)}
                  disabled={overrideSource === "env"}
                  placeholder={CHROME_PATH_EXAMPLE}
                  className="flex-1 rounded-lg border px-3 py-2 font-mono text-[12px] transition-colors hover:border-[var(--ink-3)] disabled:opacity-60"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                    color: "var(--ink)",
                  }}
                />
                <button
                  onClick={() => {
                    setPickingCustom(false);
                    void applyOverride(customPath);
                  }}
                  disabled={overrideSource === "env" || !customPath.trim()}
                  className="flex cursor-pointer items-center gap-1 rounded-lg px-3 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: "var(--ink)", color: "var(--white)" }}
                >
                  <Save className="h-3.5 w-3.5" /> Save
                </button>
              </div>
            )}
            {overrideSource === "env" && (
              <p
                className="mt-2 rounded-md border px-3 py-2 text-[12px]"
                style={{
                  borderColor: "var(--warning)",
                  background:
                    "color-mix(in srgb, var(--warning) 10%, transparent)",
                  color: "var(--warning)",
                }}
              >
                Set by <code>AGENTOS_BROWSER_BINARY</code> in your environment
                or <code>.env</code> file — remove it there to change it here.
              </p>
            )}
          </div>

          {/* Action row */}
          <div
            className="flex flex-wrap items-center gap-2 border-t pt-3"
            style={{ borderColor: "var(--border)" }}
          >
            <button
              onClick={openTestWindow}
              disabled={testingWindow || !resolvedBinary}
              className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-50"
              style={{ borderColor: "var(--border)" }}
            >
              <Play className="h-3 w-3" />
              {testingWindow ? "Opening…" : "Open a test window"}
            </button>
            <button
              onClick={() => setShowLocation((s) => !s)}
              className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
              style={{ borderColor: "var(--border)" }}
            >
              <Search className="h-3 w-3" />
              {showLocation ? "Hide location" : "Show location"}
            </button>
            {managedBinary && (
              <button
                onClick={removeRuntime}
                className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium transition hover:opacity-80"
                style={{
                  borderColor:
                    "color-mix(in srgb, var(--danger) 40%, transparent)",
                  color: "var(--danger)",
                }}
              >
                <Trash2 className="h-3 w-3" />
                Remove built-in browser
              </button>
            )}
          </div>
          {showLocation && (
            <p
              className="rounded-lg px-3 py-2 font-mono text-[11px] text-[var(--ink-2)] break-all"
              style={{ background: "var(--sunken)" }}
            >
              {resolvedBinary ?? "No engine resolved yet"}
              {managedBinary && managedBinary !== resolvedBinary
                ? `\nbuilt-in: ${managedBinary}`
                : ""}
            </p>
          )}

          <p className="text-[11px] text-[var(--ink-3)]">
            Agents browse in their own private copy of Chrome — your personal
            browser, passwords, and logins are never touched. Works even if you
            only have Safari.
          </p>
        </div>
      </section>

      {/* Private-network access */}
      <section id="network-policy">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Private-network access
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Local services agents may reach, by exact hostname.
        </p>
        <div
          className="rounded-xl p-5 space-y-3"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <p className="text-[12px] text-[var(--ink-3)]">
            Web fetch and browser navigation are limited to public internet
            addresses by default — agents cannot read localhost, LAN devices,
            routers, or cloud metadata endpoints. Add a hostname here only if
            an agent should reach a specific local service (an intranet wiki, a
            home server). One exact host per line; subdomains are not implied.
          </p>
          <textarea
            value={privateAllowlist}
            disabled={allowlistPinned || savingAllowlist}
            onChange={(e) => setPrivateAllowlist(e.target.value)}
            placeholder={"wiki.internal\n192.168.1.20"}
            rows={3}
            className="w-full rounded-lg border px-3 py-2 font-mono text-[12px] text-[var(--ink)] disabled:opacity-60"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          />
          {allowlistPinned && (
            <p className="text-[11px] text-[var(--ink-3)]">
              Pinned by AGENTOS_WEB_PRIVATE_ALLOWLIST — edit it in the
              environment or .env to change this list.
            </p>
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={allowlistPinned || savingAllowlist}
              onClick={async () => {
                setSavingAllowlist(true);
                setError(null);
                try {
                  const entries = privateAllowlist
                    .split(/[\n,]+/)
                    .map((s) => s.trim())
                    .filter(Boolean);
                  const result = await api.updateNetworkSettings(entries);
                  setPrivateAllowlist(result.web_private_allowlist.join("\n"));
                  setNotice("Private-network exceptions saved.");
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e));
                } finally {
                  setSavingAllowlist(false);
                }
              }}
              className="cursor-pointer rounded-lg px-3 py-1.5 text-[12px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: "var(--accent)" }}
            >
              {savingAllowlist ? "Saving…" : "Save exceptions"}
            </button>
          </div>
        </div>
      </section>

      {/* Saved logins */}
      <section id="saved-logins">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Saved logins
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Keep agents signed in, only where you allow it.
        </p>
        <div
          className="rounded-xl p-5 space-y-4"
          style={{
            border: "1px solid var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <p className="text-[12px] text-[var(--ink-3)]">
            Let an agent stay logged in to a website between runs. You sign in
            once yourself and the agent reuses it. Each login only works on the
            sites you list.
          </p>

          {profiles.length === 0 ? (
            <p
              className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-[12px]"
              style={{
                background:
                  "color-mix(in srgb, var(--success) 12%, transparent)",
                color: "var(--success)",
              }}
            >
              <Check className="h-3.5 w-3.5" />
              No saved logins. Agents start logged out on every run.
            </p>
          ) : (
            <div className="space-y-2">
              {profiles.map((p) => (
                <div
                  key={p.id}
                  className="flex items-center justify-between rounded-lg border px-3 py-2"
                  style={{ borderColor: "var(--border)" }}
                >
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-[var(--ink)]">
                      {p.name}
                    </p>
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {p.allowed_domains.length > 0
                        ? `only: ${p.allowed_domains.join(", ")}`
                        : "any website"}
                      {p.description ? ` — ${p.description}` : ""}
                    </p>
                  </div>
                  <button
                    onClick={() => removeProfile(p.id)}
                    className="cursor-pointer rounded-md p-1.5 text-[var(--ink-3)] transition-colors hover:text-red-600"
                    title="Forget this login"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div
            className="space-y-3 border-t pt-4"
            style={{ borderColor: "var(--border)" }}
          >
            <p className="text-[12px] font-medium text-[var(--ink)]">
              Add a saved login
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="login-name"
                  className="mb-1 block text-[11px] font-medium text-[var(--ink-3)]"
                >
                  Name
                </label>
                <input
                  id="login-name"
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. shopping"
                  className="w-full rounded-lg border px-3 py-2 text-[12px] transition-colors hover:border-[var(--ink-3)]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                    color: "var(--ink)",
                  }}
                />
              </div>
              <div>
                <label
                  htmlFor="login-note"
                  className="mb-1 block text-[11px] font-medium text-[var(--ink-3)]"
                >
                  Note (optional)
                </label>
                <input
                  id="login-note"
                  type="text"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="What this login is for"
                  className="w-full rounded-lg border px-3 py-2 text-[12px] transition-colors hover:border-[var(--ink-3)]"
                  style={{
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                    color: "var(--ink)",
                  }}
                />
              </div>
            </div>
            <div>
              <label
                htmlFor="login-sites"
                className="mb-1 block text-[11px] font-medium text-[var(--ink-3)]"
              >
                Allowed sites
              </label>
              <input
                id="login-sites"
                type="text"
                value={newDomains}
                onChange={(e) => setNewDomains(e.target.value)}
                disabled={anySite}
                placeholder="saucedemo.com, github.com"
                className="w-full rounded-lg border px-3 py-2 text-[12px] transition-colors hover:border-[var(--ink-3)] disabled:opacity-50"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--surface)",
                  color: "var(--ink)",
                }}
              />
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-[12px] text-[var(--ink-2)]">
              <input
                type="checkbox"
                checked={anySite}
                onChange={(e) => setAnySite(e.target.checked)}
                className="h-4 w-4"
                style={{ accentColor: "var(--accent)" }}
              />
              Allow on any site{" "}
              <span style={{ color: "var(--warning, #b45309)" }}>
                (not recommended)
              </span>
            </label>
            <button
              onClick={createProfile}
              disabled={!newName.trim() || (!anySite && !newDomains.trim())}
              className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-[12px] font-medium transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{
                background: "var(--ink)",
                color: "var(--white)",
                border: "1px solid var(--ink)",
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Add login
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

