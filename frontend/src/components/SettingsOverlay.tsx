import { useEffect, useRef, useState, useCallback } from "react";
import {
  X, Save, Copy, Download, Upload, Power, Trash2, ArrowLeft,
  FileText, Folder, ChevronRight, ChevronDown, FolderOpen,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type {
  Agent,
  CapabilityGrant,
  CapabilityInfo,
  ChannelInfo,
  ModelInfo,
  Provider,
  Skill,
  SkillInfo,
  WorkspaceEntry,
} from "@/lib/types";
import { ModelSelect } from "@/components/ModelSelect";
import { ThinkingToggle } from "@/components/ThinkingToggle";
import { PreviewPanel } from "@/components/previews/PreviewPanel";

interface SettingsOverlayProps {
  agent: Agent | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  providers: Provider[];
}

const TABS = ["General", "Capabilities", "Memory", "Skills", "Workspace", "Channels"] as const;
type Tab = (typeof TABS)[number];

export function SettingsOverlay({ agent, open, onClose, onSaved, providers }: SettingsOverlayProps) {
  const [tab, setTab] = useState<Tab>("General");
  const [savedMsg, setSavedMsg] = useState("");
  const [loadedAgent, setLoadedAgent] = useState<Agent | null>(agent);

  useEffect(() => {
    if (!open || !agent || agent.capabilities !== undefined) {
      setLoadedAgent(agent);
      return;
    }

    let cancelled = false;
    api.getAgent(agent.id)
      .then((fullAgent) => {
        if (!cancelled) setLoadedAgent(fullAgent);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [agent, open]);

  const effectiveAgent = loadedAgent?.id === agent?.id ? loadedAgent : agent;

  if (!open) return null;

  const showSaved = (msg: string) => {
    setSavedMsg(msg);
    setTimeout(() => setSavedMsg(""), 2000);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.25)" }}
      onClick={onClose}
    >
      <div
        className="flex h-[80vh] w-full max-w-2xl flex-col rounded-lg border shadow-2xl"
        style={{ background: "var(--white)", borderColor: "var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex shrink-0 items-center justify-between px-6 py-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <h2 className="text-[16px] font-semibold text-[var(--ink)]">
            {effectiveAgent?.name || "Agent"} Settings
          </h2>
          <div className="flex items-center gap-3">
            {savedMsg && (
              <span className="text-[12px] font-mono" style={{ color: "var(--success)" }}>
                {savedMsg}
              </span>
            )}
            <button
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
              style={{ border: "none", background: "none", cursor: "pointer" }}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div
          className="flex shrink-0 gap-1 overflow-x-auto px-6"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="whitespace-nowrap border-b-2 px-3 py-2.5 text-[13px] transition"
              style={{
                borderColor: tab === t ? "var(--accent)" : "transparent",
                color: tab === t ? "var(--ink)" : "var(--ink-2)",
                background: "none",
                cursor: "pointer",
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Content — scrollable */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === "General" && (
            <GeneralTab agent={effectiveAgent} providers={providers} onSaved={onSaved} onClose={onClose} showSaved={showSaved} />
          )}
          {tab === "Capabilities" && (
            <CapabilitiesTab agent={effectiveAgent} onSaved={onSaved} onClose={onClose} showSaved={showSaved} />
          )}
          {tab === "Memory" && <MemoryTab agentId={agent?.id || ""} onClose={onClose} showSaved={showSaved} />}
          {tab === "Skills" && <SkillsTab agentId={agent?.id || ""} showSaved={showSaved} />}
          {tab === "Workspace" && <WorkspaceTab agentId={agent?.id || ""} showSaved={showSaved} />}
          {tab === "Channels" && <ChannelsTab agentId={agent?.id || ""} />}
        </div>
      </div>
    </div>
  );
}

// --- General Tab (merged: identity, limits, versions, actions) ---

function GeneralTab({
  agent,
  providers,
  onSaved,
  onClose,
  showSaved,
}: {
  agent: Agent | null;
  providers: Provider[];
  onSaved: () => void;
  onClose: () => void;
  showSaved: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [providerId, setProviderId] = useState("");
  const [modelName, setModelName] = useState("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [soul, setSoul] = useState("");
  const [persona, setPersona] = useState("");
  const [task, setTask] = useState("");
  const [maxTurns, setMaxTurns] = useState(15);
  const [maxCost, setMaxCost] = useState(500);
  const [idleTimeout, setIdleTimeout] = useState(60);
  const [maxContext, setMaxContext] = useState<number | null>(null);
  const [sandboxMode, setSandboxMode] = useState<"strict" | "open">("strict");
  const [thinkingEnabled, setThinkingEnabled] = useState<boolean | null>(null);
  const [thinkingEffort, setThinkingEffort] = useState<string>("medium");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (agent) {
      setName(agent.name);
      setProviderId(agent.provider_id || "");
      setModelName(agent.model || "");
      setSoul(agent.soul || "");
      setPersona(agent.persona || "");
      setTask(agent.task || "");
      if (agent.limits) {
        setMaxTurns(agent.limits.max_turns_per_run);
        setMaxCost(agent.limits.max_cost_per_run);
        setIdleTimeout(agent.limits.session_idle_timeout_min);
        setMaxContext(agent.limits.max_context_tokens);
      }
      setSandboxMode(agent.sandbox_mode || "strict");
      setThinkingEnabled(agent.thinking_enabled ?? null);
      setThinkingEffort(agent.thinking_effort || "medium");
    }
  }, [agent]);

  // Fetch models when provider changes
  useEffect(() => {
    if (!providerId) {
      setModels([]);
      return;
    }
    setLoadingModels(true);
    api.listModels(providerId)
      .then((r) => setModels(r.models))
      .catch(() => setModels([]))
      .finally(() => setLoadingModels(false));
  }, [providerId]);

  const handleSave = async () => {
    if (!agent) return;
    setSaving(true);
    try {
      await api.updateAgent(agent.id, {
        name, provider_id: providerId, model_name: modelName,
        thinking_enabled: thinkingEnabled,
        thinking_effort: thinkingEnabled ? thinkingEffort : null,
        soul, persona, task,
        sandbox_mode: sandboxMode,
        limits: {
          max_turns_per_run: maxTurns,
          max_cost_per_run: maxCost,
          session_idle_timeout_min: idleTimeout,
          max_context_tokens: maxContext,
        },
      });
      onSaved();
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const handleDisable = async () => {
    if (!agent) return;
    if (agent.enabled) await api.disableAgent(agent.id);
    else await api.enableAgent(agent.id);
    // Reload the agent so the button label updates
    const updated = await api.getAgent(agent.id);
    onSaved();
    // Force re-render with updated agent
    if (updated) {
      agent.enabled = updated.enabled;
    }
    showSaved(updated?.enabled ? "Agent enabled" : "Agent disabled");
  };

  const handleDuplicate = async () => {
    if (!agent) return;
    await api.duplicateAgent(agent.id, `${agent.id}-copy`, `${agent.name} (copy)`);
    onSaved();
    showSaved("Agent duplicated");
  };

  const handleExport = async () => {
    if (!agent) return;
    const result = await api.exportAgent(agent.id);
    const blob = new Blob([result.yaml], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${agent.id}.yaml`;
    a.click();
    URL.revokeObjectURL(url);
    showSaved("Exported YAML");
  };

  const handleImport = async () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".yaml,.yml";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const yaml = await file.text();
      await api.importAgent(yaml);
      onSaved();
      showSaved("Agent imported");
    };
    input.click();
  };

  if (!agent) return <p className="text-[13px] text-[var(--ink-2)]">Loading...</p>;

  return (
    <div className="space-y-8">
      {/* Section: Basic */}
      <Section title="Basic">
        <Field label="Agent ID">
          <input
            value={agent.id}
            disabled
            className="w-full rounded-[5px] border px-3 py-2 font-mono text-[12px] text-[var(--ink-3)]"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          />
        </Field>
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Provider">
            <select
              value={providerId}
              onChange={(e) => setProviderId(e.target.value)}
              className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }}
            >
              <option value="">— Select —</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </Field>
          <Field label="Default Model">
            <ModelSelect
              value={modelName}
              onChange={setModelName}
              models={models}
              loading={loadingModels}
              disabled={loadingModels || !providerId}
              placeholder={loadingModels ? "Loading…" : !providerId ? "Select a provider first" : "Search or type a model name…"}
            />
          </Field>
        </div>
        {(() => {
          const selectedModel = models.find((m) => m.id === modelName || m.name === modelName);
          if (!selectedModel?.supports_thinking) return null;
          return (
            <Field label="Default Thinking">
              <div className="flex items-center gap-2">
                <ThinkingToggle
                  enabled={thinkingEnabled}
                  effort={thinkingEffort}
                  efforts={selectedModel.thinking_efforts || ["low", "medium", "high"]}
                  onToggle={(enabled) => setThinkingEnabled(enabled)}
                  onEffortChange={setThinkingEffort}
                />
                <span className="text-[11px] text-[var(--ink-3)]">
                  {thinkingEnabled === null
                    ? "Model default — no explicit thinking"
                    : thinkingEnabled
                    ? "Thinking enabled by default for all messages"
                    : "Thinking disabled by default"}
                </span>
              </div>
            </Field>
          );
        })()}
      </Section>

      {/* Section: Identity */}
      <Section title="Identity">
        <Field label="Soul — identity, values, principles">
          <textarea
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            placeholder="What this agent believes in, its core values and principles..."
            rows={4}
            className="w-full resize-y rounded-[5px] border px-3 py-2 text-[13px] leading-[1.6] text-[var(--ink)] outline-none"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          />
        </Field>
        <Field label="Persona — tone, communication style">
          <textarea
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            placeholder="How this agent talks, its personality and communication style..."
            rows={4}
            className="w-full resize-y rounded-[5px] border px-3 py-2 text-[13px] leading-[1.6] text-[var(--ink)] outline-none"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          />
        </Field>
        <Field label="Task — mission, instructions">
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="What this agent should do, its mission and instructions..."
            rows={4}
            className="w-full resize-y rounded-[5px] border px-3 py-2 text-[13px] leading-[1.6] text-[var(--ink)] outline-none"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          />
        </Field>
      </Section>

      {/* Section: Limits */}
      <Section title="Limits & Sandbox">
        <Field label="Sandbox mode">
          <select
            value={sandboxMode}
            onChange={(e) => setSandboxMode(e.target.value as "strict" | "open")}
            className="w-full rounded-[5px] px-2.5 py-1.5 text-[13px]"
            style={{ border: "1px solid var(--border)", background: "var(--surface)" }}
          >
            <option value="strict">Strict — workspace only</option>
            <option value="open">Open — full filesystem access</option>
          </select>
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Max turns per run">
            <NumberInput value={maxTurns} onChange={(v) => setMaxTurns(v ?? 0)} />
          </Field>
          <Field label="Max cost per run ($)">
            <NumberInput value={maxCost} onChange={(v) => setMaxCost(v ?? 0)} step={0.01} />
          </Field>
          <Field label="Session idle timeout (min)">
            <NumberInput value={idleTimeout} onChange={(v) => setIdleTimeout(v ?? 0)} />
          </Field>
          <Field label="Max context tokens">
            <NumberInput value={maxContext} onChange={setMaxContext} placeholder="auto (model default)" />
          </Field>
        </div>
        <p className="text-[12px] text-[var(--ink-3)]">
          Heartbeat scheduling is configured in the{" "}
          <a href="/scheduler" className="underline" style={{ color: "var(--accent)" }}>Scheduler</a> page.
        </p>
      </Section>

      {/* Section: Actions */}
      <Section title="Actions">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleDisable}
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] transition"
            style={{
              border: "1px solid var(--border)",
              background: "none",
              cursor: "pointer",
              color: agent.enabled ? "var(--danger)" : "var(--success)",
            }}
          >
            <Power className="h-3.5 w-3.5" /> {agent.enabled ? "Disable" : "Enable"}
          </button>
          <button
            onClick={handleDuplicate}
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] text-[var(--ink-2)] transition"
            style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
          >
            <Copy className="h-3.5 w-3.5" /> Duplicate
          </button>
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] text-[var(--ink-2)] transition"
            style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
          >
            <Download className="h-3.5 w-3.5" /> Export YAML
          </button>
          <button
            onClick={handleImport}
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] text-[var(--ink-2)] transition"
            style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
          >
            <Upload className="h-3.5 w-3.5" /> Import YAML
          </button>
        </div>
      </Section>

      {/* Single save for everything above */}
      <div className="pt-2">
        <SaveButton onClick={handleSave} disabled={saving} label="Save" />
      </div>
    </div>
  );
}

// --- Capabilities Tab ---

// Capabilities are fetched from the backend API (single source of truth)
// Falls back to empty list if the API call fails.
const FALLBACK_CAPABILITIES: CapabilityInfo[] = [];
type GrantMode = "none" | "on_demand" | "always";
const SERVER_GRANT_PREFIX = "mcp_server:";

function grantMode(grant: CapabilityGrant | undefined, kind: string): GrantMode {
  if (!grant || grant.enabled === false) return "none";
  if (grant.always_loaded === true) return "always";
  if (grant.always_loaded === false) return "on_demand";
  return kind === "mcp_tool" ? "on_demand" : "always";
}

function capabilityState(agent: Agent | null, allCaps: CapabilityInfo[]) {
  const grantModes = new Map<string, GrantMode>();
  const serverModes = new Map<string, GrantMode>();
  const approvals = new Set<string>();
  const serverApprovals = new Map<string, boolean>();
  const denied = new Set<string>();

  if (agent?.capabilities) {
    for (const grant of agent.capabilities) {
      if (grant.name.startsWith(SERVER_GRANT_PREFIX)) {
        const serverId = grant.name.slice(SERVER_GRANT_PREFIX.length);
        const mode = grantMode(grant, "mcp_tool");
        if (mode !== "none") serverModes.set(serverId, mode);
        serverApprovals.set(serverId, grant.require_approval);
        continue;
      }
      const kind = allCaps.find((cap) => cap.name === grant.name)?.kind || "tool";
      const mode = grantMode(grant, kind);
      if (mode === "none") denied.add(grant.name);
      else grantModes.set(grant.name, mode);
      if (grant.require_approval) approvals.add(grant.name);
    }
  } else {
    for (const cap of allCaps) {
      if (cap.kind !== "mcp_tool") {
        grantModes.set(cap.name, "always");
        if (cap.require_approval) approvals.add(cap.name);
      }
    }
  }

  return { grantModes, serverModes, approvals, serverApprovals, denied };
}

function CapabilitiesTab({
  agent,
  onSaved,
  showSaved,
}: {
  agent: Agent | null;
  onSaved: () => void;
  onClose: () => void;
  showSaved: (msg: string) => void;
}) {
  const [grantModes, setGrantModes] = useState<Map<string, GrantMode>>(new Map());
  const [serverModes, setServerModes] = useState<Map<string, GrantMode>>(new Map());
  const [approvals, setApprovals] = useState<Set<string>>(new Set());
  const [serverApprovals, setServerApprovals] = useState<Map<string, boolean>>(new Map());
  const [denied, setDenied] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [allCaps, setAllCaps] = useState<CapabilityInfo[]>(FALLBACK_CAPABILITIES);
  const [yoloMode, setYoloMode] = useState(false);

  // Fetch YOLO mode state
  useEffect(() => {
    api.getYoloMode().then((r) => setYoloMode(r.yolo_mode)).catch(() => {});
  }, []);

  const toggleYolo = async () => {
    const next = !yoloMode;
    setYoloMode(next);
    try {
      await api.setYoloMode(next);
      showSaved(next ? "YOLO mode ON — approvals disabled" : "YOLO mode OFF");
    } catch {
      setYoloMode(!next); // revert on error
    }
  };

  // Fetch capability list from backend (single source of truth)
  useEffect(() => {
    api.listCapabilities().then(setAllCaps).catch(() => {});
  }, []);

  useEffect(() => {
    const state = capabilityState(agent, allCaps);
    setGrantModes(state.grantModes);
    setServerModes(state.serverModes);
    setApprovals(state.approvals);
    setServerApprovals(state.serverApprovals);
    setDenied(state.denied);
  }, [agent, allCaps]);

  const modeFor = (cap: CapabilityInfo): GrantMode => {
    if (cap.kind === "mcp_tool") {
      // Explicit entries beat the server wildcard (same precedence as backend).
      if (denied.has(cap.name)) return "none";
      if (grantModes.has(cap.name)) return grantModes.get(cap.name)!;
      if (cap.server_id && serverModes.has(cap.server_id)) {
        return serverModes.get(cap.server_id) || "none";
      }
      return "none";
    }
    return grantModes.get(cap.name) || "none";
  };

  const saveCapabilities = async (
    modeMap: Map<string, GrantMode> = grantModes,
    serverModeMap: Map<string, GrantMode> = serverModes,
    approvalSet: Set<string> = approvals,
    serverApprovalMap: Map<string, boolean> = serverApprovals,
    deniedSet: Set<string> = denied,
  ) => {
    if (!agent) return;
    setSaving(true);
    setSaveError("");
    try {
      const caps: CapabilityGrant[] = [];
      const builtinCaps = allCaps.filter((cap) => cap.kind !== "mcp_tool");
      for (const cap of builtinCaps) {
        const mode = modeMap.get(cap.name) || "none";
        if (mode !== "none") {
          caps.push({
            name: cap.name,
            subject: "none",
            require_approval: approvalSet.has(cap.name),
            always_loaded: mode === "always",
          });
        }
      }

      const mcpServers = new Map<string, CapabilityInfo[]>();
      for (const cap of allCaps) {
        if (cap.kind !== "mcp_tool") continue;
        const key = cap.server_id || "other";
        if (!mcpServers.has(key)) mcpServers.set(key, []);
        mcpServers.get(key)!.push(cap);
      }
      for (const [serverId, serverCaps] of mcpServers) {
        const serverMode = serverModeMap.get(serverId) || "none";
        const serverGranted = serverId !== "other" && serverMode !== "none";
        if (serverGranted) {
          caps.push({
            name: `${SERVER_GRANT_PREFIX}${serverId}`,
            subject: "none",
            require_approval:
              serverApprovalMap.get(serverId) ?? serverCaps.some((cap) => cap.egress),
            always_loaded: serverMode === "always",
          });
        }
        for (const cap of serverCaps) {
          // Explicit deny overrides the wildcard — keep the grant so the
          // backend honors it (exact match beats the server grant).
          if (deniedSet.has(cap.name)) {
            caps.push({
              name: cap.name,
              enabled: false,
              subject: "none",
              require_approval: false,
              always_loaded: false,
            });
            continue;
          }
          const mode = modeMap.get(cap.name) || "none";
          if (mode !== "none") {
            caps.push({
              name: cap.name,
              subject: "none",
              require_approval: approvalSet.has(cap.name),
              always_loaded: mode === "always",
            });
          }
        }
      }

      await api.updateAgent(agent.id, { capabilities: caps });
      onSaved();
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      setSaveError(
        message.startsWith("503:")
          ? "The database is busy. Nothing was saved; please retry."
          : "Could not save capability settings; please retry.",
      );
      try {
        const serverAgent = await api.getAgent(agent.id);
        const state = capabilityState(serverAgent, allCaps);
        setGrantModes(state.grantModes);
        setServerModes(state.serverModes);
        setApprovals(state.approvals);
        setServerApprovals(state.serverApprovals);
        setDenied(state.denied);
        onSaved();
      } catch {
      }
    } finally {
      setSaving(false);
    }
  };

  const updateMode = (name: string, mode: GrantMode) => {
    const cap = allCaps.find((c) => c.name === name);
    const next = new Map(grantModes);
    const nextDenied = new Set(denied);
    const inherited =
      cap?.kind === "mcp_tool" && cap.server_id
        ? serverModes.get(cap.server_id) || "none"
        : "none";
    if (cap?.kind === "mcp_tool" && inherited !== "none") {
      // Under a granted server: explicit entries only exist as overrides —
      // matching the inherited mode falls back to inheriting, "none" writes
      // an explicit deny, anything else writes an explicit grant.
      if (mode === inherited) {
        next.delete(name);
        nextDenied.delete(name);
      } else if (mode === "none") {
        next.delete(name);
        nextDenied.add(name);
      } else {
        next.set(name, mode);
        nextDenied.delete(name);
      }
    } else {
      if (mode === "none") next.delete(name);
      else next.set(name, mode);
      nextDenied.delete(name);
    }
    setGrantModes(next);
    setDenied(nextDenied);
    void saveCapabilities(next, serverModes, approvals, serverApprovals, nextDenied);
  };

  const updateServerMode = (serverId: string, mode: GrantMode, caps: CapabilityInfo[]) => {
    const next = new Map(serverModes);
    const nextApprovals = new Map(serverApprovals);
    if (mode === "none") {
      next.delete(serverId);
      nextApprovals.delete(serverId);
    } else {
      next.set(serverId, mode);
      if (!nextApprovals.has(serverId)) {
        nextApprovals.set(serverId, caps.some((cap) => cap.egress));
      }
    }
    setServerModes(next);
    setServerApprovals(nextApprovals);
    void saveCapabilities(grantModes, next, approvals, nextApprovals);
  };

  const updateServerApproval = (serverId: string, required: boolean) => {
    const next = new Map(serverApprovals);
    next.set(serverId, required);
    setServerApprovals(next);
    void saveCapabilities(grantModes, serverModes, approvals, next);
  };

  const toggleApproval = (name: string) => {
    const next = new Set(approvals);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setApprovals(next);
    void saveCapabilities(grantModes, serverModes, next, serverApprovals);
  };

  const setAllModes = (caps: CapabilityInfo[], enable: boolean) => {
    const next = new Map(grantModes);
    const nextDenied = new Set(denied);
    for (const cap of caps) {
      if (enable) next.set(cap.name, cap.kind === "mcp_tool" ? "on_demand" : "always");
      else next.delete(cap.name);
      nextDenied.delete(cap.name);
    }
    setGrantModes(next);
    setDenied(nextDenied);
    void saveCapabilities(next, serverModes, approvals, serverApprovals, nextDenied);
  };

  // A row inherits when the server wildcard covers it and it has no explicit
  // grant or deny of its own (backend: exact match beats the wildcard).
  const isInherited = (cap: CapabilityInfo) =>
    cap.kind === "mcp_tool" &&
    !!cap.server_id &&
    serverModes.has(cap.server_id) &&
    !denied.has(cap.name) &&
    !grantModes.has(cap.name);

  // Group capabilities: built-in vs MCP (grouped by stable server ID)
  const builtinCaps = allCaps.filter((cap) => cap.kind !== "mcp_tool");
  const mcpServers = new Map<string, CapabilityInfo[]>();
  for (const cap of allCaps) {
    if (cap.kind === "mcp_tool") {
      const serverId = cap.server_id || "other";
      if (!mcpServers.has(serverId)) mcpServers.set(serverId, []);
      mcpServers.get(serverId)!.push(cap);
    }
  }

  return (
    <div className="space-y-3">
      {/* YOLO mode banner */}
      <div
        className="flex items-center justify-between rounded-[6px] border px-4 py-3"
        style={{
          borderColor: yoloMode ? "var(--danger)" : "var(--border)",
          background: yoloMode ? "rgba(239,68,68,0.05)" : "transparent",
        }}
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-[var(--ink)]">YOLO Mode</span>
            {yoloMode && (
              <span
                className="rounded-full px-2 py-0.5 text-[9px] font-mono uppercase"
                style={{ background: "var(--danger)", color: "#fff" }}
              >
                Active
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-[var(--ink-3)]">
            Skip all approval gates. Tools execute immediately without confirmation.
          </p>
        </div>
        <button
          onClick={toggleYolo}
          className="rounded-[5px] px-3 py-1.5 text-[12px] font-medium transition"
          style={{
            border: "1px solid var(--border)",
            background: yoloMode ? "var(--danger)" : "none",
            color: yoloMode ? "#fff" : "var(--ink-2)",
            cursor: "pointer",
          }}
        >
          {yoloMode ? "Disable" : "Enable"}
        </button>
      </div>

      <p className="text-[12px] text-[var(--ink-3)]">
        Permit tools directly or make large MCP integrations discoverable on demand. Egress tools can require approval.
      </p>
      <CapabilityGroup
        title="Built-in Tools"
        caps={builtinCaps}
        modeFor={modeFor}
        isInherited={isInherited}
        onModeChange={updateMode}
        onSetAll={setAllModes}
        approvals={approvals}
        toggleApproval={toggleApproval}
        defaultExpanded
      />
      {Array.from(mcpServers.entries()).map(([serverId, caps]) => {
        const serverMode = serverModes.get(serverId) || "none";
        const serverRequiresApproval = serverApprovals.get(serverId) ?? caps.some((cap) => cap.egress);
        const serverName = caps[0]?.server_name || serverId;
        return (
          <CapabilityGroup
            key={serverId}
            title={`MCP: ${serverName}`}
            caps={caps}
            modeFor={modeFor}
            isInherited={isInherited}
            onModeChange={updateMode}
            onSetAll={setAllModes}
            approvals={approvals}
            toggleApproval={toggleApproval}
            serverMode={serverId === "other" ? undefined : serverMode}
            onServerModeChange={serverId === "other" ? undefined : (mode) => updateServerMode(serverId, mode, caps)}
            serverRequiresApproval={serverId === "other" ? undefined : serverRequiresApproval}
            onServerApprovalChange={serverId === "other" ? undefined : (required) => updateServerApproval(serverId, required)}
            defaultExpanded={false}
          />
        );
      })}
      {saveError && (
        <p role="alert" className="font-mono text-[11px]" style={{ color: "var(--danger)" }}>
          {saveError}
        </p>
      )}
      {saving && (
        <p className="font-mono text-[11px] text-[var(--ink-3)]">Saving…</p>
      )}
    </div>
  );
}

function CapabilityGroup({
  title,
  caps,
  modeFor,
  isInherited,
  onModeChange,
  onSetAll,
  approvals,
  toggleApproval,
  serverMode,
  onServerModeChange,
  serverRequiresApproval,
  onServerApprovalChange,
  defaultExpanded,
}: {
  title: string;
  caps: CapabilityInfo[];
  modeFor: (cap: CapabilityInfo) => GrantMode;
  isInherited: (cap: CapabilityInfo) => boolean;
  onModeChange: (name: string, mode: GrantMode) => void;
  onSetAll: (caps: CapabilityInfo[], enable: boolean) => void;
  approvals: Set<string>;
  toggleApproval: (name: string) => void;
  serverMode?: GrantMode;
  onServerModeChange?: (mode: GrantMode) => void;
  serverRequiresApproval?: boolean;
  onServerApprovalChange?: (required: boolean) => void;
  defaultExpanded: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [expandedDesc, setExpandedDesc] = useState<string | null>(null);
  const serverGrantActive = serverMode !== undefined;
  const grantedCount = caps.filter((cap) => modeFor(cap) !== "none").length;
  const allGranted = caps.length > 0 && grantedCount === caps.length;

  const handleToggleAll = () => {
    if (serverGrantActive && onServerModeChange) {
      onServerModeChange(serverMode === "none" ? "on_demand" : "none");
    } else {
      onSetAll(caps, !allGranted);
    }
  };

  return (
    <div className="rounded-[6px] border" style={{ borderColor: "var(--border)" }}>
      <div
        className="flex items-center gap-2 px-4 py-2.5 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5" style={{ color: "var(--ink-3)" }} />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" style={{ color: "var(--ink-3)" }} />
        )}
        <span className="font-mono text-[12px] font-medium uppercase tracking-wider" style={{ color: "var(--ink-2)" }}>
          {title}
        </span>
        <span className="font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
          {grantedCount}/{caps.length}
        </span>
        {serverGrantActive ? (
          <select
            value={serverMode}
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => onServerModeChange?.(event.target.value as GrantMode)}
            className="ml-auto rounded-[4px] border px-1.5 py-1 text-[10px]"
            style={{ borderColor: "var(--border)", color: "var(--ink-2)", background: "var(--white)" }}
          >
            <option value="none">Not permitted</option>
            <option value="on_demand">Permitted on demand</option>
            <option value="always">Always available</option>
          </select>
        ) : (
          <button
            onClick={(event) => { event.stopPropagation(); handleToggleAll(); }}
            className="ml-auto rounded-[4px] px-2 py-0.5 font-mono text-[10px] transition"
            style={{
              background: "none",
              border: "1px solid var(--border)",
              color: "var(--ink-3)",
              cursor: "pointer",
            }}
          >
            {allGranted ? "Disable all" : "Enable all"}
          </button>
        )}
        {serverGrantActive && serverMode !== "none" && caps.some((cap) => cap.egress) && (
          <label className="flex items-center gap-1.5 text-[10px] text-[var(--ink-2)]" onClick={(event) => event.stopPropagation()}>
            <input
              type="checkbox"
              checked={serverRequiresApproval}
              onChange={(event) => onServerApprovalChange?.(event.target.checked)}
              style={{ cursor: "pointer" }}
            />
            approval
          </label>
        )}
      </div>
      {expanded && (
        <div className="space-y-1.5 px-4 pb-3">
          {caps.map((cap) => {
            const mode = modeFor(cap);
            const viaServer = serverGrantActive && serverMode !== "none" && isInherited(cap);
            const needsApproval = approvals.has(cap.name);
            return (
              <div
                key={cap.name}
                className="flex items-center justify-between rounded-[5px] px-3 py-2"
                style={{ background: "var(--surface)" }}
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[12px] font-medium text-[var(--ink)]">{cap.name}</span>
                      {cap.egress && (
                        <span className="rounded-full px-1.5 py-0.5 text-[9px] font-mono" style={{ background: "rgba(245,158,11,0.1)", color: "var(--warning)" }}>
                          egress
                        </span>
                      )}
                    </div>
                    <p
                      className="text-[11px] text-[var(--ink-2)]"
                      style={{ cursor: cap.description.length > 80 ? "pointer" : "default" }}
                      title={cap.description.length > 80 ? cap.description : undefined}
                      onClick={() => cap.description.length > 80 && setExpandedDesc(expandedDesc === cap.name ? null : cap.name)}
                    >
                      {cap.description.length > 80
                        ? (expandedDesc === cap.name ? cap.description : cap.description.slice(0, 80) + "…")
                        : cap.description}
                      {cap.description.length > 80 && (
                        <span className="ml-1 font-mono text-[10px] text-[var(--ink-3)]">
                          {expandedDesc === cap.name ? "[-]" : "[+]"}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {viaServer && (
                    <span className="font-mono text-[10px] text-[var(--ink-3)]">via server</span>
                  )}
                  <select
                    value={mode}
                    onChange={(event) => onModeChange(cap.name, event.target.value as GrantMode)}
                    className="rounded-[4px] border px-1.5 py-1 text-[10px]"
                    style={{ borderColor: "var(--border)", color: "var(--ink-2)", background: "var(--white)" }}
                  >
                    <option value="none">Not permitted</option>
                    <option value="on_demand">On demand</option>
                    <option value="always">Always</option>
                  </select>
                  {!viaServer && mode !== "none" && cap.egress && (
                    <label className="flex items-center gap-1.5 text-[10px] text-[var(--ink-2)]">
                      <input type="checkbox" checked={needsApproval} onChange={() => toggleApproval(cap.name)} style={{ cursor: "pointer" }} />
                      approval
                    </label>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// --- Memory Tab ---

function MemoryTab({ agentId, onClose }: { agentId: string; onClose: () => void; showSaved: (msg: string) => void }) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!agentId) return;
    (async () => {
      try {
        const result = await api.getMemory(agentId);
        setContent(result.content);
      } catch {} finally {
        setLoading(false);
      }
    })();
  }, [agentId]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateMemory(agentId, content);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-[var(--ink-3)]">
        MEMORY.md is the agent's living notebook. Not versioned — changes take effect immediately.
      </p>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="# Memory\n\nThe agent's long-term notes go here…"
        rows={18}
        className="w-full resize-y rounded-[5px] border px-3 py-2 font-mono text-[12px] leading-[1.6] text-[var(--ink)] outline-none"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      />
      <SaveButton onClick={handleSave} disabled={saving} label="Save" />
    </div>
  );
}

// --- Skills Tab ---

function SkillsTab({ agentId, showSaved }: { agentId: string; showSaved: (msg: string) => void }) {
  const [systemSkills, setSystemSkills] = useState<SkillInfo[]>([]);
  const [agentSkills, setAgentSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const { confirm } = useConfirm();

  const load = useCallback(async () => {
    try {
      const [globalData, agentData] = await Promise.all([
        api.listSkills(),
        api.listAgentSkills(agentId),
      ]);
      setSystemSkills(globalData.skills);
      setAgentSkills(agentData);
    } catch {} finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { load(); }, [load]);

  const handleDeleteAgentSkill = async (name: string) => {
    const ok = await confirm({
      title: "Delete skill?",
      message: `Delete agent skill "${name}"?`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    await api.deleteAgentSkill(agentId, name);
    load();
    showSaved("Skill deleted");
  };

  const handlePromote = async (name: string) => {
    try {
      await api.promoteSkill(name, agentId);
      load();
      showSaved(`Promoted "${name}" to global`);
    } catch (e) {
      showSaved(`Promote failed: ${e instanceof Error ? e.message : "error"}`);
    }
  };

  if (loading) return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-[12px] font-medium text-[var(--ink-2)]">
            Global Skills ({systemSkills.length})
          </p>
          <a
            href="/skills"
            className="text-[12px] text-[var(--accent)] hover:underline"
          >
            Manage in Skills page →
          </a>
        </div>
        <p className="text-[11px] text-[var(--ink-3)] mb-3">
          Available to all agents. Use /skillname in chat to activate.
        </p>
        {systemSkills.length === 0 ? (
          <p className="py-4 text-center text-[13px] text-[var(--ink-3)]">No global skills installed.</p>
        ) : (
          <div className="space-y-1.5">
            {systemSkills.map((skill) => (
              <div
                key={skill.name}
                className="flex items-center justify-between rounded-[5px] border px-4 py-2.5"
                style={{ borderColor: "var(--border)", background: "var(--surface)" }}
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[13px] font-medium text-[var(--ink)]">{skill.name}</p>
                  {skill.description && (
                    <p className="text-[12px] text-[var(--ink-2)] truncate">{skill.description}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: "16px" }}>
        <p className="text-[12px] font-medium text-[var(--ink-2)] mb-2">
          Agent Skills ({agentSkills.length})
        </p>
        <p className="text-[11px] text-[var(--ink-3)] mb-3">
          Created by this agent via skill-creator. Promote to global to share with other agents.
        </p>
        {agentSkills.length === 0 ? (
          <p className="py-4 text-center text-[13px] text-[var(--ink-3)]">
            No agent-specific skills. Use the skill-creator skill in chat to create one.
          </p>
        ) : (
          <div className="space-y-1.5">
            {agentSkills.map((skill) => (
              <div
                key={skill.name}
                className="flex items-center justify-between rounded-[5px] border px-4 py-2.5"
                style={{ borderColor: "var(--border)", background: "var(--surface)" }}
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[13px] font-medium text-[var(--ink)]">{skill.name}</p>
                  {skill.description && (
                    <p className="text-[12px] text-[var(--ink-2)] truncate">{skill.description}</p>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-2">
                  <button
                    onClick={() => handlePromote(skill.name)}
                    className="text-[12px] text-[var(--accent)] transition hover:underline"
                    style={{ border: "none", background: "none", cursor: "pointer" }}
                    title="Promote to global"
                  >
                    Promote
                  </button>
                  <button
                    onClick={() => handleDeleteAgentSkill(skill.name)}
                    className="text-[var(--ink-3)] transition hover:text-[var(--danger)]"
                    style={{ border: "none", background: "none", cursor: "pointer" }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// --- Workspace Tab ---
//
// Split file-browser/preview (W3): the directory stays navigable on the
// left while the shared PreviewPanel renders the selected file on the
// right. Narrow layouts fall back to a full-width preview with Back.

function WorkspaceTab({ agentId, showSaved }: { agentId: string; showSaved: (msg: string) => void }) {
  const { confirm } = useConfirm();
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<WorkspaceEntry[]>([]);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);
  // Saved when the preview opens: where the browser was scrolled and which
  // row was selected, so closing the preview lands the operator back
  // exactly where they left off.
  const browseStateRef = useRef<{ scrollTop: number; selected: string | null }>({
    scrollTop: 0,
    selected: null,
  });

  const load = useCallback(async (p: string) => {
    if (!agentId) return;
    setLoading(true);
    try {
      const result = await api.listWorkspace(agentId, p);
      if (result.type === "dir") {
        setEntries(result.entries || []);
      }
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { load(""); }, [load]);

  const navigate = (entry: WorkspaceEntry) => {
    const newPath = path ? `${path}/${entry.name}` : entry.name;
    if (entry.type === "dir") {
      setPath(newPath);
      load(newPath);
    } else {
      browseStateRef.current = {
        scrollTop: listRef.current?.scrollTop ?? 0,
        selected: newPath,
      };
      setPreviewPath(newPath);
    }
  };

  const closePreview = () => {
    const saved = browseStateRef.current;
    setPreviewPath(null);
    // Restore the browser's scroll + focus after React remounts the list.
    requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = saved.scrollTop;
      if (saved.selected) {
        listRef.current
          ?.querySelector<HTMLButtonElement>(`[data-path="${CSS.escape(saved.selected)}"]`)
          ?.focus();
      }
    });
  };

  const goUp = () => {
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    const up = parts.join("/");
    setPath(up);
    load(up);
  };

  const errDetail = (e: unknown) => {
    const m = e instanceof Error ? e.message : String(e);
    try {
      return JSON.parse(m.replace(/^\d+:\s*/, "")).detail ?? m;
    } catch {
      return m;
    }
  };

  const handleDelete = async (entry: WorkspaceEntry) => {
    const rel = path ? `${path}/${entry.name}` : entry.name;
    const ok = await confirm({
      title: `Delete ${entry.type === "dir" ? "folder" : "file"}?`,
      message: `Delete "${rel}"${entry.type === "dir" ? " and everything inside it" : ""}? This cannot be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteWorkspaceEntry(agentId, rel);
      if (previewPath === rel || previewPath?.startsWith(`${rel}/`)) closePreview();
      showSaved(`Deleted ${entry.name}`);
      load(path);
    } catch (e) {
      showSaved(`Delete failed: ${errDetail(e)}`);
    }
  };

  const breadcrumbs = path ? path.split("/").filter(Boolean) : [];

  const fileList = (
    <div ref={listRef} className="h-full space-y-1 overflow-auto">
      {path && (
        <button
          onClick={goUp}
          className="flex w-full items-center gap-2 rounded-[5px] px-3 py-2 text-[13px] text-[var(--ink-2)] transition hover:bg-[var(--surface)]"
          style={{ border: "none", background: "none", cursor: "pointer" }}
        >
          <FolderOpen className="h-4 w-4" /> ..
        </button>
      )}
      {entries.map((entry) => (
        <div
          key={entry.name}
          className="group flex w-full items-center rounded-[5px] transition hover:bg-[var(--surface)]"
          style={{
            background:
              previewPath === (path ? `${path}/${entry.name}` : entry.name)
                ? "var(--surface)"
                : "none",
          }}
        >
          <button
            data-path={path ? `${path}/${entry.name}` : entry.name}
            onClick={() => navigate(entry)}
            className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-[13px]"
            style={{ border: "none", background: "none", cursor: "pointer", color: "var(--ink)" }}
          >
            {entry.type === "dir" ? (
              <Folder className="h-4 w-4" style={{ color: "var(--accent)" }} />
            ) : (
              <FileText className="h-4 w-4" style={{ color: "var(--ink-3)" }} />
            )}
            <span className="truncate">{entry.name}</span>
            {entry.type === "file" && (
              <span className="ml-auto shrink-0 font-mono text-[11px] text-[var(--ink-3)]">
                {entry.size > 1024 ? `${(entry.size / 1024).toFixed(1)}KB` : `${entry.size}B`}
              </span>
            )}
          </button>
          <button
            onClick={() => void handleDelete(entry)}
            aria-label={`Delete ${entry.name}`}
            title={`Delete ${entry.name}`}
            className="mr-1 shrink-0 rounded-[3px] p-1 text-[var(--ink-3)] opacity-0 transition hover:bg-[var(--white)] hover:text-[var(--danger)] group-hover:opacity-100"
            style={{ border: "none", cursor: "pointer" }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      {entries.length === 0 && !loading && (
        <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Empty directory.</p>
      )}
    </div>
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1 text-[12px] text-[var(--ink-2)]">
        <button onClick={() => { setPath(""); load(""); }} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--accent)" }}>
          workspace
        </button>
        {breadcrumbs.map((part, i) => (
          <span key={i} className="flex items-center gap-1">
            <ChevronRight className="h-3 w-3" />
            <button
              onClick={() => {
                const p = breadcrumbs.slice(0, i + 1).join("/");
                setPath(p);
                load(p);
              }}
              style={{ border: "none", background: "none", cursor: "pointer", color: i === breadcrumbs.length - 1 ? "var(--ink)" : "var(--accent)" }}
            >
              {part}
            </button>
          </span>
        ))}
      </div>

      {loading ? (
        <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>
      ) : previewPath ? (
        <div>
          {/* Narrow layouts get a full-width preview with a way back —
              the split browser column only exists at md+. */}
          <button
            onClick={closePreview}
            className="mb-2 flex items-center gap-1.5 rounded-[5px] px-2 py-1 text-[12px] text-[var(--ink-2)] transition hover:bg-[var(--surface)] md:hidden"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Back to Workspace
          </button>
          <div className="flex gap-0 overflow-hidden rounded-[5px] border border-[var(--border)]" style={{ height: "60vh" }}>
            <div className="hidden w-56 shrink-0 overflow-auto border-r border-[var(--border)] p-2 md:block">
              {fileList}
            </div>
            <div className="min-w-0 flex-1">
              <PreviewPanel
                agentId={agentId}
                source={{ path: previewPath }}
                onClose={closePreview}
                onDeleted={(p) => {
                  closePreview();
                  showSaved(`Deleted ${p.split("/").pop()}`);
                  load(path);
                }}
              />
            </div>
          </div>
        </div>
      ) : (
        <div style={{ maxHeight: "60vh" }}>{fileList}</div>
      )}
    </div>
  );
}

// --- Channels Tab ---

function ChannelsTab({ agentId }: { agentId: string }) {
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listChannels()
      .then((all) => setChannels(all.filter((c) => c.agent_id === agentId)))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [agentId]);

  const platformIcons: Record<string, string> = {
    telegram: "✈️",
    discord: "🎮",
    zalo: "💬",
  };

  return (
    <div className="space-y-2">
      {/* Dashboard chat — always active */}
      <div
        className="flex items-center justify-between rounded-[5px] border px-4 py-3"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <div>
          <p className="text-[13px] font-medium text-[var(--ink)]">Dashboard</p>
          <p className="text-[12px] text-[var(--ink-2)]">Built-in web chat channel</p>
        </div>
        <span className="rounded-full px-2 py-0.5 text-[11px] font-mono" style={{ background: "rgba(22,163,74,0.1)", color: "var(--success)" }}>
          Active
        </span>
      </div>

      {/* External channels connected to this agent */}
      {loading ? (
        <p className="py-2 text-[12px] text-[var(--ink-3)]">Loading...</p>
      ) : channels.length === 0 ? (
        <div
          className="rounded-[5px] border px-4 py-3"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <p className="text-[13px] text-[var(--ink-2)]">No external channels connected</p>
          <p className="mt-1 text-[12px] text-[var(--ink-3)]">
            Go to the Channels page to connect Telegram, Discord, and other messaging platforms to this agent.
          </p>
        </div>
      ) : (
        channels.map((ch) => (
          <div
            key={ch.id}
            className="flex items-center justify-between rounded-[5px] border px-4 py-3"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          >
            <div className="flex items-center gap-2">
              <span className="text-lg">{platformIcons[ch.platform] || "📡"}</span>
              <div>
                <p className="text-[13px] font-medium text-[var(--ink)]">
                  {ch.platform.charAt(0).toUpperCase() + ch.platform.slice(1)}
                </p>
                <p className="text-[12px] text-[var(--ink-2)]">
                  {ch.mode === "polling" ? "Polling" : "Webhook"} mode
                </p>
              </div>
            </div>
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-mono"
              style={{
                background: ch.enabled ? "rgba(22,163,74,0.1)" : "rgba(100,100,100,0.1)",
                color: ch.enabled ? "var(--success)" : "var(--ink-3)",
              }}
            >
              {ch.enabled ? "Active" : "Disabled"}
            </span>
          </div>
        ))
      )}

      <p className="pt-2 text-[12px] text-[var(--ink-3)]">
        Manage channels in the <a href="/channels" className="underline">Channels page</a>.
      </p>
    </div>
  );
}

// --- Shared components ---

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h3 className="text-[14px] font-semibold text-[var(--ink)]" style={{ paddingBottom: "4px", borderBottom: "1px solid var(--border)" }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-[var(--ink-2)]">{label}</label>
      {children}
    </div>
  );
}

function NumberInput({ value, onChange, step, placeholder }: { value: number | null; onChange: (v: number | null) => void; step?: number; placeholder?: string }) {
  return (
    <input
      type="number"
      value={value ?? ""}
      step={step || 1}
      placeholder={placeholder}
      onChange={(e) => {
        const v = e.target.value;
        onChange(v === "" ? null : parseFloat(v) || 0);
      }}
      className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
    />
  );
}

function SaveButton({ onClick, disabled, label }: { onClick: () => void; disabled: boolean; label: string }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-1.5 rounded-[6px] px-4 py-2 text-[13px] font-medium transition"
      style={{
        background: "var(--ink)",
        color: "var(--white)",
        border: "1px solid var(--ink)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <Save className="h-3.5 w-3.5" /> {label}
    </button>
  );
}
