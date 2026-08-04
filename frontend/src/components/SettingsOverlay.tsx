import { useEffect, useState, useCallback } from "react";
import {
  X, Save, Copy, Download, Upload, Power, Plus, Trash2,
  FileText, Folder, ChevronRight, FolderOpen,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Agent, ModelInfo, Provider, Skill, WorkspaceEntry } from "@/lib/types";
import { ModelSelect } from "@/components/ModelSelect";

interface CapabilityInfo {
  name: string;
  desc: string;
  egress: boolean;
  approval: boolean;
}

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
            {agent?.name || "Agent"} Settings
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
            <GeneralTab agent={agent} providers={providers} onSaved={onSaved} onClose={onClose} showSaved={showSaved} />
          )}
          {tab === "Capabilities" && (
            <CapabilitiesTab agent={agent} onSaved={onSaved} onClose={onClose} showSaved={showSaved} />
          )}
          {tab === "Memory" && <MemoryTab agentId={agent?.id || ""} onClose={onClose} showSaved={showSaved} />}
          {tab === "Skills" && <SkillsTab agentId={agent?.id || ""} showSaved={showSaved} />}
          {tab === "Workspace" && <WorkspaceTab agentId={agent?.id || ""} />}
          {tab === "Channels" && <ChannelsTab />}
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
  const [maxContext, setMaxContext] = useState(24000);
  const [sandboxMode, setSandboxMode] = useState<"strict" | "open">("strict");
  const [hbEnabled, setHbEnabled] = useState(false);
  const [hbInterval, setHbInterval] = useState(60);
  const [hbPrompt, setHbPrompt] = useState("");
  const [hbMaxCost, setHbMaxCost] = useState(0.5);
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
      if (agent.heartbeat) {
        setHbEnabled(agent.heartbeat.enabled);
        setHbInterval(agent.heartbeat.interval_minutes);
        setHbPrompt(agent.heartbeat.task_prompt);
        setHbMaxCost(agent.heartbeat.max_cost_per_heartbeat);
      }
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
        soul, persona, task,
        sandbox_mode: sandboxMode,
        limits: {
          max_turns_per_run: maxTurns,
          max_cost_per_run: maxCost,
          session_idle_timeout_min: idleTimeout,
          max_context_tokens: maxContext,
        },
        heartbeat: {
          enabled: hbEnabled,
          interval_minutes: hbInterval,
          task_prompt: hbPrompt,
          max_cost_per_heartbeat: hbMaxCost,
          consecutive_failure_threshold: 3,
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
            <NumberInput value={maxTurns} onChange={setMaxTurns} />
          </Field>
          <Field label="Max cost per run ($)">
            <NumberInput value={maxCost} onChange={setMaxCost} step={0.01} />
          </Field>
          <Field label="Session idle timeout (min)">
            <NumberInput value={idleTimeout} onChange={setIdleTimeout} />
          </Field>
          <Field label="Max context tokens">
            <NumberInput value={maxContext} onChange={setMaxContext} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-[13px] text-[var(--ink-2)]">
          <input type="checkbox" checked={hbEnabled} onChange={(e) => setHbEnabled(e.target.checked)} />
          Enable periodic heartbeat
        </label>
        {hbEnabled && (
          <div className="grid grid-cols-2 gap-4">
            <Field label="Interval (minutes)">
              <NumberInput value={hbInterval} onChange={setHbInterval} />
            </Field>
            <Field label="Max cost per heartbeat ($)">
              <NumberInput value={hbMaxCost} onChange={setHbMaxCost} step={0.01} />
            </Field>
            <div className="col-span-2">
              <Field label="Heartbeat task prompt">
                <textarea
                  value={hbPrompt}
                  onChange={(e) => setHbPrompt(e.target.value)}
                  placeholder="What should the agent do on each heartbeat?"
                  rows={2}
                  className="w-full resize-none rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                />
              </Field>
            </div>
          </div>
        )}
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

function CapabilitiesTab({
  agent,
  onSaved,
  onClose,
  showSaved,
}: {
  agent: Agent | null;
  onSaved: () => void;
  onClose: () => void;
  showSaved: (msg: string) => void;
}) {
  const [granted, setGranted] = useState<Set<string>>(new Set());
  const [approvals, setApprovals] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [allCaps, setAllCaps] = useState<CapabilityInfo[]>(FALLBACK_CAPABILITIES);

  // Fetch capability list from backend (single source of truth)
  useEffect(() => {
    api.listCapabilities().then((caps) => {
      setAllCaps(caps.map((c) => ({
        name: c.name,
        desc: c.description,
        egress: c.egress,
        approval: c.require_approval,
      })));
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (agent?.capabilities) {
      // Explicit list (including empty = no tools)
      setGranted(new Set(agent.capabilities.map((c) => c.name)));
      setApprovals(new Set(agent.capabilities.filter((c) => c.require_approval).map((c) => c.name)));
    } else {
      // capabilities is null/missing = all tools enabled (default)
      setGranted(new Set(allCaps.map((c) => c.name)));
      setApprovals(new Set(allCaps.filter((c) => c.approval).map((c) => c.name)));
    }
  }, [agent, allCaps]);

  const toggle = (name: string) => {
    const next = new Set(granted);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setGranted(next);
  };

  const toggleApproval = (name: string) => {
    const next = new Set(approvals);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setApprovals(next);
  };

  const handleSave = async () => {
    if (!agent) return;
    setSaving(true);
    try {
      // If all tools are granted, save null (= all tools, default)
      // Otherwise save the explicit list
      const allGranted = allCaps.length > 0 && allCaps.every((c) => granted.has(c.name));
      const caps = allGranted
        ? null
        : Array.from(granted).map((name) => ({
            name,
            subject: "none" as const,
            require_approval: approvals.has(name),
          }));
      await api.updateAgent(agent.id, { capabilities: caps });
      onSaved();
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-[var(--ink-3)]">
        Select which tools this agent can use. Egress tools (network access) can require approval.
      </p>
      {allCaps.map((cap) => {
        const isGranted = granted.has(cap.name);
        const needsApproval = approvals.has(cap.name);
        return (
          <div
            key={cap.name}
            className="flex items-center justify-between rounded-[5px] border px-4 py-3"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          >
            <div className="flex items-center gap-3">
              <input type="checkbox" checked={isGranted} onChange={() => toggle(cap.name)} style={{ cursor: "pointer" }} />
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[13px] font-medium text-[var(--ink)]">{cap.name}</span>
                  {cap.egress && (
                    <span className="rounded-full px-1.5 py-0.5 text-[10px] font-mono" style={{ background: "rgba(245,158,11,0.1)", color: "var(--warning)" }}>
                      egress
                    </span>
                  )}
                </div>
                <p className="text-[12px] text-[var(--ink-2)]">{cap.desc}</p>
              </div>
            </div>
            {isGranted && cap.egress && (
              <label className="flex items-center gap-1.5 text-[12px] text-[var(--ink-2)]">
                <input type="checkbox" checked={needsApproval} onChange={() => toggleApproval(cap.name)} style={{ cursor: "pointer" }} />
                require approval
              </label>
            )}
          </div>
        );
      })}
      <SaveButton onClick={handleSave} disabled={saving} label="Save" />
    </div>
  );
}

// --- Memory Tab ---

function MemoryTab({ agentId, onClose, showSaved }: { agentId: string; onClose: () => void; showSaved: (msg: string) => void }) {
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
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    if (!agentId) return;
    try {
      setSkills(await api.listSkills(agentId));
    } catch {} finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    await api.createSkill(agentId, newName.trim());
    setNewName("");
    setShowCreate(false);
    load();
    showSaved("Skill created");
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete skill "${name}"?`)) return;
    await api.deleteSkill(agentId, name);
    load();
    showSaved("Skill deleted");
  };

  if (loading) return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-[var(--ink-3)]">
          Skills are reusable prompt fragments in the agent's home directory.
        </p>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="flex items-center gap-1 rounded-[5px] px-2.5 py-1.5 text-[12px] transition"
          style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer", color: "var(--ink-2)" }}
        >
          <Plus className="h-3.5 w-3.5" /> New Skill
        </button>
      </div>

      {showCreate && (
        <div className="flex gap-2 rounded-[5px] border p-3" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="skill-name"
            className="flex-1 rounded-[5px] border px-3 py-1.5 text-[13px] text-[var(--ink)] outline-none"
            style={{ borderColor: "var(--border)", background: "var(--white)" }}
            autoFocus
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <button
            onClick={handleCreate}
            className="rounded-[5px] px-3 py-1.5 text-[13px] font-medium"
            style={{ background: "var(--ink)", color: "var(--white)", border: "none", cursor: "pointer" }}
          >
            Create
          </button>
        </div>
      )}

      {skills.length === 0 ? (
        <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">No skills configured.</p>
      ) : (
        skills.map((skill) => (
          <div
            key={skill.name}
            className="flex items-center justify-between rounded-[5px] border px-4 py-3"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          >
            <div>
              <p className="font-mono text-[13px] font-medium text-[var(--ink)]">{skill.name}</p>
              {skill.description && <p className="text-[12px] text-[var(--ink-2)]">{skill.description}</p>}
            </div>
            <button
              onClick={() => handleDelete(skill.name)}
              className="text-[var(--ink-3)] transition hover:text-[var(--danger)]"
              style={{ border: "none", background: "none", cursor: "pointer" }}
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))
      )}
    </div>
  );
}

// --- Workspace Tab ---

function WorkspaceTab({ agentId }: { agentId: string }) {
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState<WorkspaceEntry[]>([]);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (p: string) => {
    if (!agentId) return;
    setLoading(true);
    setFileContent(null);
    try {
      const result = await api.listWorkspace(agentId, p);
      if (result.type === "dir") {
        setEntries(result.entries || []);
      } else {
        setFileContent(result.content || "");
        setEntries([]);
      }
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => { load(""); }, [load]);

  const navigate = (name: string) => {
    const newPath = path ? `${path}/${name}` : name;
    setPath(newPath);
    load(newPath);
  };

  const goUp = () => {
    const parts = path.split("/").filter(Boolean);
    parts.pop();
    const up = parts.join("/");
    setPath(up);
    load(up);
  };

  const breadcrumbs = path ? path.split("/").filter(Boolean) : [];

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
      ) : fileContent !== null ? (
        <div>
          <button onClick={goUp} className="mb-2 flex items-center gap-1 text-[12px] text-[var(--accent)]" style={{ border: "none", background: "none", cursor: "pointer" }}>
            <FolderOpen className="h-3.5 w-3.5" /> Back
          </button>
          <pre
            className="max-h-[60vh] overflow-auto rounded-[5px] border p-3 font-mono text-[12px] leading-[1.5] text-[var(--ink)]"
            style={{ borderColor: "var(--border)", background: "var(--surface)" }}
          >
            {fileContent}
          </pre>
        </div>
      ) : entries.length === 0 ? (
        <p className="py-8 text-center text-[13px] text-[var(--ink-3)]">Empty directory.</p>
      ) : (
        <div className="space-y-1">
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
            <button
              key={entry.name}
              onClick={() => navigate(entry.name)}
              className="flex w-full items-center gap-2 rounded-[5px] px-3 py-2 text-[13px] text-[var(--ink)] transition hover:bg-[var(--surface)]"
              style={{ border: "none", background: "none", cursor: "pointer" }}
            >
              {entry.type === "dir" ? (
                <Folder className="h-4 w-4" style={{ color: "var(--accent)" }} />
              ) : (
                <FileText className="h-4 w-4" style={{ color: "var(--ink-3)" }} />
              )}
              <span>{entry.name}</span>
              {entry.type === "file" && (
                <span className="ml-auto font-mono text-[11px] text-[var(--ink-3)]">
                  {entry.size > 1024 ? `${(entry.size / 1024).toFixed(1)}KB` : `${entry.size}B`}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Channels Tab ---

function ChannelsTab() {
  return (
    <div className="space-y-2">
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
      <p className="pt-2 text-[12px] text-[var(--ink-3)]">
        More channels (Telegram, Slack, etc.) coming in a later release.
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

function NumberInput({ value, onChange, step }: { value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <input
      type="number"
      value={value}
      step={step || 1}
      onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
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
