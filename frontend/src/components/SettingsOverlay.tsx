import { useEffect, useRef, useState, useCallback } from "react";
import {
  X, Save, Copy, Download, Upload, Power, Trash2,
  ChevronRight, ChevronDown,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
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
} from "@/lib/types";
import { ModelSelect } from "@/components/ModelSelect";
import { ThinkingToggle } from "@/components/ThinkingToggle";
import { Button } from "@/components/ui/button";
import { FilterPills } from "@/components/ui/filter-pills";
import { Select } from "@/components/ui/select";

interface SettingsOverlayProps {
  agent: Agent | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  providers: Provider[];
}

const TABS = ["General", "Capabilities", "Memory", "Skills", "Channels"] as const;
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/25"
      onClick={onClose}
    >
      <div
        className="flex h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">
              {effectiveAgent?.name || "Agent"} settings
            </h2>
            <p className="mt-0.5 text-[12px] text-ink-3">
              Identity, model, capabilities, memory and data.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {savedMsg && (
              <span className="rounded-full bg-accent-tint px-2.5 py-0.5 text-[11px] font-medium text-accent">
                {savedMsg}
              </span>
            )}
            <button
              onClick={onClose}
              className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Tabs — segmented */}
        <div className="shrink-0 border-b border-line px-5 py-3">
          <FilterPills
            pills={TABS.map((t) => ({ key: t, label: t }))}
            active={tab}
            onChange={(k) => setTab(k as Tab)}
            variant="segmented"
          />
        </div>

        {/* Content — scrollable */}
        <div className="flex-1 overflow-y-auto p-5">
          {tab === "General" && (
            <GeneralTab agent={effectiveAgent} providers={providers} onSaved={onSaved} onClose={onClose} showSaved={showSaved} />
          )}
          {tab === "Capabilities" && (
            <CapabilitiesTab agent={effectiveAgent} onSaved={onSaved} onClose={onClose} showSaved={showSaved} />
          )}
          {tab === "Memory" && <MemoryTab agentId={agent?.id || ""} onClose={onClose} showSaved={showSaved} />}
          {tab === "Skills" && <SkillsTab agentId={agent?.id || ""} showSaved={showSaved} />}
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
  const [maxTurns, setMaxTurns] = useState(200);
  const [maxCost, setMaxCost] = useState(500);
  const [idleTimeout, setIdleTimeout] = useState(5);
  const [maxContext, setMaxContext] = useState<number | null>(null);
  const [coreMax, setCoreMax] = useState<number | null>(null);
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
        setCoreMax(agent.limits.core_max_tokens ?? 32768);
      }
      setSandboxMode(agent.sandbox_mode || "strict");
      setThinkingEnabled(agent.thinking_enabled ?? null);
      setThinkingEffort(agent.thinking_effort || "medium");
    }
  }, [agent]);

  // Fetch models when provider changes — cancelled so a late response
  // from the previous provider can't clobber the new one's list.
  useEffect(() => {
    if (!providerId) {
      setModels([]);
      return;
    }
    let cancelled = false;
    setLoadingModels(true);
    api
      .listModels(providerId)
      .then((r) => {
        if (!cancelled) setModels(r.models);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false);
      });
    return () => {
      cancelled = true;
    };
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
          core_max_tokens: coreMax ?? 32768,
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

  if (!agent) return <p className="text-[13px] text-ink-2">Loading...</p>;

  return (
    <div className="space-y-8">
      {/* Section: Basic */}
      <Section title="Basic">
        <Field label="Agent ID">
          <input
            value={agent.id}
            disabled
            className="w-full rounded-md border px-3 py-2 font-mono text-[12px] text-ink-3"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          />
        </Field>
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border px-3 py-2 text-[13px] text-ink outline-none"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Provider">
            <Select
              value={providerId}
              onChange={setProviderId}
              options={providers.map((p) => ({ value: p.id, label: p.name }))}
              className="w-full rounded-md border border-[var(--border)] bg-ground px-3 py-2 text-[13px] text-ink outline-none"
              align="left" panelClassName="text-[13px]"
            />
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
                <span className="text-[11px] text-ink-3">
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
            className="w-full resize-y rounded-md border px-3 py-2 text-[13px] leading-[1.6] text-ink outline-none"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          />
        </Field>
        <Field label="Persona — tone, communication style">
          <textarea
            value={persona}
            onChange={(e) => setPersona(e.target.value)}
            placeholder="How this agent talks, its personality and communication style..."
            rows={4}
            className="w-full resize-y rounded-md border px-3 py-2 text-[13px] leading-[1.6] text-ink outline-none"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          />
        </Field>
        <Field label="Task — mission, instructions">
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="What this agent should do, its mission and instructions..."
            rows={4}
            className="w-full resize-y rounded-md border px-3 py-2 text-[13px] leading-[1.6] text-ink outline-none"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          />
        </Field>
      </Section>

      {/* Section: Limits */}
      <Section title="Limits & Sandbox">
        <Field label="Sandbox mode">
          <Select
            value={sandboxMode}
            onChange={(v) => setSandboxMode(v as "strict" | "open")}
            options={[
              { value: "strict", label: "Strict — workspace only" },
              { value: "open", label: "Open — full filesystem access" },
            ]}
            className="w-full rounded-md border border-line bg-ground px-2.5 py-1.5 text-[13px]"
            align="left" panelClassName="text-[13px]"
          />
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
          <Field label="Core memory ceiling (tokens)">
            <NumberInput value={coreMax} onChange={(v) => setCoreMax(v ?? 32768)} placeholder="32768" />
          </Field>
        </div>
        <p className="text-[12px] text-ink-3">
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
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] text-ink-2 transition"
            style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
          >
            <Copy className="h-3.5 w-3.5" /> Duplicate
          </button>
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] text-ink-2 transition"
            style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
          >
            <Download className="h-3.5 w-3.5" /> Export YAML
          </button>
          <button
            onClick={handleImport}
            className="flex items-center gap-1.5 rounded-[6px] px-3 py-2 text-[13px] text-ink-2 transition"
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
  // Per-agent YOLO — skips approval gates for this agent only. The global
  // AGENTOS_YOLO_MODE / persisted flag is an ops override: when it's on,
  // every agent bypasses approvals and this toggle is advisory.
  const [yoloMode, setYoloMode] = useState(agent?.yolo_mode ?? false);
  const [globalYolo, setGlobalYolo] = useState(false);

  useEffect(() => {
    setYoloMode(agent?.yolo_mode ?? false);
  }, [agent?.yolo_mode]);

  useEffect(() => {
    api.getYoloMode().then((r) => setGlobalYolo(r.yolo_mode)).catch(() => {});
  }, []);

  const toggleYolo = async () => {
    if (!agent) return;
    const next = !yoloMode;
    setYoloMode(next);
    try {
      await api.updateAgent(agent.id, { yolo_mode: next });
      showSaved(next ? "YOLO mode ON — approvals disabled" : "YOLO mode OFF");
      window.dispatchEvent(
        new CustomEvent("caberos:yolo-mode", {
          detail: { agentId: agent.id, enabled: next },
        }),
      );
    } catch {
      setYoloMode(!next); // revert on error
    }
  };

  const disableGlobalYolo = async () => {
    try {
      await api.setYoloMode(false);
      setGlobalYolo(false);
      showSaved("Global YOLO override off");
    } catch {
      showSaved("Global override is env-pinned — unset AGENTOS_YOLO_MODE");
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
      setSaveError(
        error instanceof ApiError && error.status === 503
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
      {/* YOLO mode banner — per-agent approval bypass */}
      <div
        className={`flex items-center justify-between rounded-lg border px-4 py-3 transition ${
          yoloMode || globalYolo ? "border-danger bg-danger-tint" : "border-line"
        }`}
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-ink">YOLO Mode</span>
            {(yoloMode || globalYolo) && (
              <span className="rounded-full bg-danger px-2 py-0.5 text-[9px] font-mono uppercase text-white">
                Active
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-ink-3">
            Skip approval gates for this agent only. Tools execute immediately without confirmation.
          </p>
          {globalYolo && (
            <p className="mt-0.5 text-[11px] font-medium text-danger">
              Forced on for all agents via the global YOLO setting.{" "}
              <button
                type="button"
                onClick={disableGlobalYolo}
                className="text-danger underline underline-offset-2"
              >
                turn off global override
              </button>
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={toggleYolo}
          disabled={globalYolo}
          className={`rounded-md border px-3 py-1.5 text-[12px] font-medium transition ${
            yoloMode
              ? "border-danger bg-danger text-white"
              : "border-line text-ink-2 hover:border-ink-3"
          } ${globalYolo ? "cursor-not-allowed opacity-50" : ""}`}
        >
          {yoloMode ? "Disable" : "Enable"}
        </button>
      </div>

      <p className="text-[12px] text-ink-3">
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
        <p role="alert" className="font-mono text-[11px] text-danger">
          {saveError}
        </p>
      )}
      {saving && (
        <p className="font-mono text-[11px] text-ink-3">Saving…</p>
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
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div
        className="flex cursor-pointer items-center gap-2 px-4 py-2.5 transition hover:bg-ground"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-ink-3" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-ink-3" />
        )}
        <span className="font-mono text-[11px] font-medium uppercase tracking-[0.05em] text-ink-2">
          {title}
        </span>
        <span className="font-mono text-[11px] text-ink-3">
          {grantedCount}/{caps.length}
        </span>
        {serverGrantActive ? (
          <Select
            value={serverMode}
            onClick={(event) => event.stopPropagation()}
            onChange={(v) => onServerModeChange?.(v as GrantMode)}
            options={[
              { value: "none", label: "Not permitted" },
              { value: "on_demand", label: "Permitted on demand" },
              { value: "always", label: "Always available" },
            ]}
            className="ml-auto h-7 rounded-md border border-line bg-ground px-2 text-[11px] text-ink-2 outline-none transition focus:border-accent"
          />
        ) : (
          <button
            onClick={(event) => { event.stopPropagation(); handleToggleAll(); }}
            className="ml-auto rounded-md border border-line px-2.5 py-1 font-mono text-[10px] text-ink-3 transition hover:border-ink-3 hover:text-ink-2"
          >
            {allGranted ? "Disable all" : "Enable all"}
          </button>
        )}
        {serverGrantActive && serverMode !== "none" && caps.some((cap) => cap.egress) && (
          <label
            className="flex items-center gap-1.5 text-[11px] text-ink-2"
            onClick={(event) => event.stopPropagation()}
          >
            <input
              type="checkbox"
              checked={serverRequiresApproval}
              onChange={(event) => onServerApprovalChange?.(event.target.checked)}
              className="cursor-pointer accent-[var(--accent)]"
            />
            approval
          </label>
        )}
      </div>
      {expanded && (
        <div className="space-y-1.5 border-t border-line px-4 pb-3 pt-3">
          {caps.map((cap) => {
            const mode = modeFor(cap);
            const viaServer = serverGrantActive && serverMode !== "none" && isInherited(cap);
            const needsApproval = approvals.has(cap.name);
            return (
              <div
                key={cap.name}
                className="flex items-center justify-between gap-3 rounded-md bg-ground px-3 py-2"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[12px] font-medium text-ink">{cap.name}</span>
                      {cap.egress && (
                        <span className="rounded-full bg-warning-tint px-1.5 py-0.5 font-mono text-[9px] text-warning">
                          egress
                        </span>
                      )}
                    </div>
                    <p
                      className={`text-[11px] text-ink-2 ${cap.description.length > 80 ? "cursor-pointer" : ""}`}
                      title={cap.description.length > 80 ? cap.description : undefined}
                      onClick={() => cap.description.length > 80 && setExpandedDesc(expandedDesc === cap.name ? null : cap.name)}
                    >
                      {cap.description.length > 80
                        ? (expandedDesc === cap.name ? cap.description : cap.description.slice(0, 80) + "…")
                        : cap.description}
                      {cap.description.length > 80 && (
                        <span className="ml-1 font-mono text-[10px] text-ink-3">
                          {expandedDesc === cap.name ? "[-]" : "[+]"}
                        </span>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {viaServer && (
                    <span className="font-mono text-[10px] text-ink-3">via server</span>
                  )}
                  <Select
                    value={mode}
                    onChange={(v) => onModeChange(cap.name, v as GrantMode)}
                    options={[
                      { value: "none", label: "Not permitted" },
                      { value: "on_demand", label: "On demand" },
                      { value: "always", label: "Always" },
                    ]}
                    className="h-7 rounded-md border border-line bg-surface px-2 text-[11px] text-ink-2 outline-none transition focus:border-accent"
                  />
                  {!viaServer && mode !== "none" && cap.egress && (
                    <label className="flex items-center gap-1.5 text-[11px] text-ink-2">
                      <input
                        type="checkbox"
                        checked={needsApproval}
                        onChange={() => toggleApproval(cap.name)}
                        className="cursor-pointer accent-[var(--accent)]"
                      />
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

function MemoryTab({ agentId }: { agentId: string; onClose: () => void; showSaved: (msg: string) => void }) {
  const [managed, setManaged] = useState("");
  const [content, setContent] = useState("");
  const [meta, setMeta] = useState<{ hash?: string | null; token_count?: number; max_tokens?: number | null; revision_id?: string | null }>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{
    message: string;
    currentCurated?: string;
    currentHash?: string;
  } | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [savedCurated, setSavedCurated] = useState("");

  const load = useCallback(async (forAgent: string) => {
    try {
      const result = await api.getMemory(forAgent);
      if (forAgent !== agentIdRef.current) return; // stale response for a prior agent
      setManaged(result.managed_content || "");
      const curated = result.curated_content ?? result.content ?? "";
      setContent(curated);
      setSavedCurated(curated);
      setMeta({
        hash: result.hash,
        token_count: result.token_count,
        max_tokens: result.max_tokens,
        revision_id: result.revision_id,
      });
      setConflict(null);
      setLoadFailed(false);
    } catch (e) {
      if (forAgent !== agentIdRef.current) return;
      // Keep the operator's draft — a failed load must not stomp it.
      setLoadFailed(true);
      setConflict({ message: e instanceof Error ? e.message : "Failed to load memory" });
    } finally {
      if (forAgent === agentIdRef.current) setLoading(false);
    }
  }, []);

  // Current agent id ref — guards a late response for the previous agent
  // from overwriting freshly loaded state.
  const agentIdRef = useRef(agentId);
  agentIdRef.current = agentId;

  useEffect(() => {
    if (!agentId) return;
    setLoading(true);
    setLoadFailed(false);
    load(agentId);
  }, [agentId, load]);

  const dirty = content !== savedCurated;

  const handleSave = async () => {
    setSaving(true);
    setNotice(null);
    setConflict(null);
    try {
      // Whole-file hash is the CAS base — the server rejects a stale base
      // rather than stomping a concurrent edit.
      await api.updateMemory(agentId, content, meta.hash ?? undefined);
      setNotice("Saved — a new core revision was published.");
      await load(agentId);
    } catch (e) {
      const detail = (e as ApiError)?.detail as
        | { conflict?: string; current_hash?: string; current_curated_content?: string }
        | string
        | undefined;
      if (detail && typeof detail === "object") {
        // Keep the server's CURRENT hash — "Replace my draft" must adopt
        // the authoritative base or the next save loops the same 409.
        setConflict({
          message: detail.conflict || "Save conflict",
          currentCurated: detail.current_curated_content ?? undefined,
          currentHash: detail.current_hash ?? undefined,
        });
      } else {
        setConflict({ message: e instanceof Error ? e.message : "Save failed" });
      }
    } finally {
      setSaving(false);
    }
  };

  const handleCleanup = async () => {
    setCleaning(true);
    setNotice(null);
    setConflict(null);
    try {
      await api.cleanupMemory(agentId);
      setNotice("Cleanup complete — a new revision was published.");
      await load(agentId);
    } catch (e) {
      setConflict({ message: e instanceof Error ? e.message : "Cleanup failed" });
    } finally {
      setCleaning(false);
    }
  };

  if (loading) return <p className="text-[13px] text-ink-2">Loading…</p>;

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-ink-3">
        Core memory is agent-wide and personal — running sessions keep their
        pinned snapshot; edits apply to future sessions.
      </p>
      {managed && (
        <div>
          <p className="text-[12px] font-medium text-ink-2 mb-1">Managed identity (read-only)</p>
          <pre
            className="w-full max-h-40 overflow-y-auto whitespace-pre-wrap break-all rounded-md border px-3 py-2 font-mono text-[11px] leading-[1.5] text-ink-3"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          >
            {managed}
          </pre>
        </div>
      )}
      <div>
        <p className="text-[12px] font-medium text-ink-2 mb-1">Curated memory</p>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="# Memory

Durable preferences and standing facts…"
          rows={14}
          className="w-full resize-y rounded-md border px-3 py-2 font-mono text-[12px] leading-[1.6] text-ink outline-none"
          style={{ borderColor: "var(--border)", background: "var(--ground)" }}
        />
      </div>
      <div className="flex items-center justify-between">
        <p className="text-[11px] text-ink-3">
          {meta.token_count != null && meta.max_tokens != null
            ? `${meta.token_count} / ${meta.max_tokens} tokens`
            : ""}
          {meta.hash ? ` · ${meta.hash.slice(0, 12)}` : ""}
          {meta.revision_id
            ? ` · rev ${meta.revision_id.slice(0, 12)} — revisions retained; restore via the memory API`
            : ""}
        </p>
        <div className="flex gap-2">
          <button
            onClick={handleCleanup}
            // Cleanup only makes sense against the saved bytes — a dirty
            // draft hasn't been persisted yet, so it's disabled until saved.
            disabled={cleaning || saving || dirty || loadFailed}
            className="rounded-md border px-3 py-1.5 text-[12px] text-ink-2 disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
          >
            {cleaning ? "Cleaning…" : "Clean Up"}
          </button>
          <SaveButton onClick={handleSave} disabled={saving || cleaning || loadFailed} label="Save" />
        </div>
      </div>
      {conflict && (
        <div className="text-[12px] text-[var(--danger,#b91c1c)]">
          <p>Conflict: {conflict.message}</p>
          {conflict.currentCurated !== undefined && (
            <button
              onClick={() => {
                // Adopt the server's curated bytes AND its current hash —
                // stale revision/token metadata is cleared until the next
                // successful save reloads it.
                setContent(conflict.currentCurated || "");
                setSavedCurated("");
                setMeta((m) => ({
                  ...m,
                  hash: conflict.currentHash ?? m.hash,
                  token_count: undefined,
                  revision_id: undefined,
                }));
                setConflict(null);
              }}
              className="mt-1 underline"
            >
              Replace my draft with the current version
            </button>
          )}
        </div>
      )}
      {notice && <p className="text-[12px] text-[var(--olive,#4d7c0f)]">{notice}</p>}
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
      setSystemSkills(globalData.skills.filter((s) => s.scope !== "agent-local"));
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

  const handlePromote = async (skill: Skill) => {
    const ok = await confirm({
      title: "Promote to global?",
      message: `Promote "${skill.name}" to a global skill? It becomes available to all agents and leaves this agent's workspace.`,
      confirmLabel: "Promote",
    });
    if (!ok) return;
    try {
      await api.promoteSkill(skill.id!, { change_summary: "promoted from agent settings" });
      load();
      showSaved(`Promoted "${skill.name}" to global`);
    } catch (e) {
      showSaved(`Promote failed: ${e instanceof Error ? e.message : "error"}`);
    }
  };

  if (loading) return <p className="text-[13px] text-ink-2">Loading…</p>;

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-[12px] font-medium text-ink-2">
            Global Skills ({systemSkills.length})
          </p>
          <a
            href="/skills"
            className="text-[12px] text-accent hover:underline"
          >
            Manage in Skills page →
          </a>
        </div>
        <p className="text-[11px] text-ink-3 mb-3">
          Available to all agents. Use /skillname in chat to activate.
        </p>
        {systemSkills.length === 0 ? (
          <p className="py-4 text-center text-[13px] text-ink-3">No global skills installed.</p>
        ) : (
          <div className="space-y-1.5">
            {systemSkills.map((skill) => (
              <div
                key={skill.name}
                className="flex items-center justify-between rounded-md border px-4 py-2.5"
                style={{ borderColor: "var(--border)", background: "var(--ground)" }}
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[13px] font-medium text-ink">{skill.name}</p>
                  {skill.description && (
                    <p className="text-[12px] text-ink-2 truncate">{skill.description}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: "16px" }}>
        <p className="text-[12px] font-medium text-ink-2 mb-2">
          Agent Skills ({agentSkills.length})
        </p>
        <p className="text-[11px] text-ink-3 mb-3">
          Created by this agent via skill-creator. Promote to global to share with other agents.
        </p>
        {agentSkills.length === 0 ? (
          <p className="py-4 text-center text-[13px] text-ink-3">
            No agent-specific skills. Use the skill-creator skill in chat to create one.
          </p>
        ) : (
          <div className="space-y-1.5">
            {agentSkills.map((skill) => (
              <div
                key={skill.name}
                className="flex items-center justify-between rounded-md border px-4 py-2.5"
                style={{ borderColor: "var(--border)", background: "var(--ground)" }}
              >
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[13px] font-medium text-ink">{skill.name}</p>
                  {skill.description && (
                    <p className="text-[12px] text-ink-2 truncate">{skill.description}</p>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-2">
                  {skill.id && (
                    <button
                      onClick={() => handlePromote(skill)}
                      className="text-[12px] text-accent transition hover:underline"
                      style={{ border: "none", background: "none", cursor: "pointer" }}
                      title="Promote to global"
                    >
                      Promote
                    </button>
                  )}
                  <button
                    onClick={() => handleDeleteAgentSkill(skill.name)}
                    className="text-ink-3 transition hover:text-danger"
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
        className="flex items-center justify-between rounded-md border px-4 py-3"
        style={{ borderColor: "var(--border)", background: "var(--ground)" }}
      >
        <div>
          <p className="text-[13px] font-medium text-ink">Dashboard</p>
          <p className="text-[12px] text-ink-2">Built-in web chat channel</p>
        </div>
        <span className="rounded-full px-2 py-0.5 text-[11px] font-mono" style={{ background: "rgba(22,163,74,0.1)", color: "var(--success)" }}>
          Active
        </span>
      </div>

      {/* External channels connected to this agent */}
      {loading ? (
        <p className="py-2 text-[12px] text-ink-3">Loading...</p>
      ) : channels.length === 0 ? (
        <div
          className="rounded-md border px-4 py-3"
          style={{ borderColor: "var(--border)", background: "var(--ground)" }}
        >
          <p className="text-[13px] text-ink-2">No external channels connected</p>
          <p className="mt-1 text-[12px] text-ink-3">
            Go to the Channels page to connect Telegram, Discord, and other messaging platforms to this agent.
          </p>
        </div>
      ) : (
        channels.map((ch) => (
          <div
            key={ch.id}
            className="flex items-center justify-between rounded-md border px-4 py-3"
            style={{ borderColor: "var(--border)", background: "var(--ground)" }}
          >
            <div className="flex items-center gap-2">
              <span className="text-lg">{platformIcons[ch.platform] || "📡"}</span>
              <div>
                <p className="text-[13px] font-medium text-ink">
                  {ch.platform.charAt(0).toUpperCase() + ch.platform.slice(1)}
                </p>
                <p className="text-[12px] text-ink-2">
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

      <p className="pt-2 text-[12px] text-ink-3">
        Manage channels in the <a href="/channels" className="underline">Channels page</a>.
      </p>
    </div>
  );
}

// --- Shared components ---

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h3 className="border-b border-line pb-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3">
        {title}
      </h3>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1.5 block text-[12px] font-medium text-ink-2">{label}</label>
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
      className="w-full rounded-md border border-line bg-ground px-3 py-2 text-[13px] text-ink outline-none transition focus:border-accent placeholder:text-ink-faint"
    />
  );
}

function SaveButton({ onClick, disabled, label }: { onClick: () => void; disabled: boolean; label: string }) {
  return (
    <Button size="sm" onClick={onClick} disabled={disabled}>
      <Save className="h-3.5 w-3.5" /> {label}
    </Button>
  );
}
