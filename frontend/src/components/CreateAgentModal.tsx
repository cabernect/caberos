import { useState, useEffect, useRef } from "react";
import { X, Upload, FileText } from "lucide-react";
import { api } from "@/lib/api";
import type { ModelInfo, Provider } from "@/lib/types";
import { ModelSelect } from "@/components/ModelSelect";

interface CreateAgentModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
  providers: Provider[];
}

export function CreateAgentModal({ open, onClose, onCreated, providers }: CreateAgentModalProps) {
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [name, setName] = useState("");
  const [providerId, setProviderId] = useState("");
  const [modelName, setModelName] = useState("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [soul, setSoul] = useState("");
  const [persona, setPersona] = useState("");
  const [task, setTask] = useState("");
  const [yamlText, setYamlText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  if (!open) return null;

  const resetForm = () => {
    setName("");
    setProviderId("");
    setModelName("");
    setModels([]);
    setSoul("");
    setPersona("");
    setTask("");
    setYamlText("");
    setError("");
  };

  const handleCreate = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const result = await api.createAgent({
        name: name.trim(),
        provider_id: providerId || undefined,
        model_name: modelName || undefined,
        soul: soul || undefined,
        persona: persona || undefined,
        task: task || undefined,
      });
      onCreated(result.id);
      resetForm();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleImportYaml = async () => {
    if (!yamlText.trim()) {
      setError("Paste YAML content or upload a .yaml file");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const result = await api.importAgent(yamlText);
      onCreated(result.id);
      resetForm();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setYamlText(String(reader.result));
    };
    reader.readAsText(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const YAML_TEMPLATE = `id: my-agent
name: My Agent
soul: |
  What this agent believes in, its core values...
persona: |
  How this agent talks, its personality...
task: |
  What this agent should do, its mission...
model:
  provider_id: ""
  name: ""
# capabilities: [read_file, write_file, web_search]  # omit = all tools; [] = none
limits:
  max_turns_per_run: 15
  max_context_tokens: 32000
  max_cost_per_run: 1.0
`;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.25)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-lg border shadow-xl"
        style={{ background: "var(--white)", borderColor: "var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <h2 className="text-[16px] font-semibold text-[var(--ink)]">Create New Agent</h2>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition hover:bg-[var(--border)] hover:text-[var(--ink)]"
            style={{ border: "none", background: "none", cursor: "pointer" }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 px-6 pt-4">
          <button
            onClick={() => { setMode("form"); setError(""); }}
            className="rounded-[5px] px-3 py-1.5 text-[12px] font-medium transition"
            style={{
              background: mode === "form" ? "var(--ink)" : "none",
              color: mode === "form" ? "var(--white)" : "var(--ink-2)",
              border: "1px solid var(--border)",
              cursor: "pointer",
            }}
          >
            Form
          </button>
          <button
            onClick={() => { setMode("yaml"); setError(""); }}
            className="rounded-[5px] px-3 py-1.5 text-[12px] font-medium transition"
            style={{
              background: mode === "yaml" ? "var(--ink)" : "none",
              color: mode === "yaml" ? "var(--white)" : "var(--ink-2)",
              border: "1px solid var(--border)",
              cursor: "pointer",
            }}
          >
            Import YAML
          </button>
        </div>

        <div className="max-h-[55vh] space-y-4 overflow-y-auto p-6">
          {error && (
            <div
              className="rounded-[5px] px-3 py-2 text-[12px]"
              style={{ background: "rgba(239,68,68,0.1)", color: "var(--danger)" }}
            >
              {error}
            </div>
          )}

          {mode === "form" ? (
            <>
              <Field label="Name">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Research Assistant"
                  className="w-full rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                  autoFocus
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
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  {providers.length === 0 && (
                    <p className="mt-1 text-[11px] text-[var(--accent)]">
                      No providers configured. Add one in Settings → Providers first.
                    </p>
                  )}
                </Field>
                <Field label="Model name">
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

              <Field label="Soul (identity, values, principles)">
                <textarea
                  value={soul}
                  onChange={(e) => setSoul(e.target.value)}
                  placeholder="What this agent believes in, its core values..."
                  rows={3}
                  className="w-full resize-none rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                />
              </Field>

              <Field label="Persona (tone, communication style)">
                <textarea
                  value={persona}
                  onChange={(e) => setPersona(e.target.value)}
                  placeholder="How this agent talks, its personality..."
                  rows={3}
                  className="w-full resize-none rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                />
              </Field>

              <Field label="Task (mission, instructions)">
                <textarea
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  placeholder="What this agent should do, its mission..."
                  rows={3}
                  className="w-full resize-none rounded-[5px] border px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                />
              </Field>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-[5px] border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--border)]"
                  style={{ borderColor: "var(--border)", background: "none", cursor: "pointer" }}
                >
                  <Upload className="h-3.5 w-3.5" />
                  Upload .yaml file
                </button>
                <button
                  onClick={() => setYamlText(YAML_TEMPLATE)}
                  className="flex items-center gap-1.5 rounded-[5px] border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--border)]"
                  style={{ borderColor: "var(--border)", background: "none", cursor: "pointer" }}
                >
                  <FileText className="h-3.5 w-3.5" />
                  Load template
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".yaml,.yml"
                  onChange={handleFileUpload}
                  className="hidden"
                />
              </div>

              <Field label="Agent YAML">
                <textarea
                  value={yamlText}
                  onChange={(e) => setYamlText(e.target.value)}
                  placeholder="Paste agent YAML here, or upload a file / load a template..."
                  rows={16}
                  className="w-full resize-none rounded-[5px] border px-3 py-2 font-mono text-[12px] text-[var(--ink)] outline-none"
                  style={{ borderColor: "var(--border)", background: "var(--surface)" }}
                  autoFocus
                />
              </Field>

              <p className="text-[11px] text-[var(--ink-3)]">
                The YAML must include <code className="font-mono">id</code> and <code className="font-mono">name</code>.
                Leave <code className="font-mono">capabilities</code> empty to enable all tools, or list specific ones to restrict.
                If an agent with the same <code className="font-mono">id</code> already exists, it will be updated.
              </p>
            </>
          )}
        </div>

        <div
          className="flex justify-end gap-2 px-6 py-4"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <button
            onClick={onClose}
            className="rounded-[6px] px-4 py-2 text-[13px] font-medium text-[var(--ink-2)] transition"
            style={{ border: "1px solid var(--border)", background: "none", cursor: "pointer" }}
          >
            Cancel
          </button>
          <button
            onClick={mode === "form" ? handleCreate : handleImportYaml}
            disabled={saving || (mode === "form" ? !name.trim() : !yamlText.trim())}
            className="rounded-[6px] px-4 py-2 text-[13px] font-medium transition"
            style={{
              background: "var(--ink)",
              color: "var(--white)",
              border: "1px solid var(--ink)",
              cursor: saving ? "not-allowed" : "pointer",
              opacity: saving || (mode === "form" ? !name.trim() : !yamlText.trim()) ? 0.5 : 1,
            }}
          >
            {saving ? "Creating…" : mode === "form" ? "Create Agent" : "Import Agent"}
          </button>
        </div>
      </div>
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
