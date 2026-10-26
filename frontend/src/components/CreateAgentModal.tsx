import { useState, useEffect, useRef } from "react";
import { X, Upload, FileText } from "lucide-react";
import { api } from "@/lib/api";
import type { ModelInfo, Provider } from "@/lib/types";
import { ModelSelect } from "@/components/ModelSelect";
import { Button } from "@/components/ui/button";
import { FilterPills } from "@/components/ui/filter-pills";
import { Select } from "@/components/ui/select";

interface CreateAgentModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
  providers: Provider[];
  /** Which tab the dialog opens on (default "form"). */
  initialMode?: "form" | "yaml";
}

export function CreateAgentModal({ open, onClose, onCreated, providers, initialMode = "form" }: CreateAgentModalProps) {
  const [mode, setMode] = useState<"form" | "yaml">(initialMode);
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

  // Opening via "Import" vs "New agent" selects the starting tab
  useEffect(() => {
    if (open) setMode(initialMode);
  }, [open, initialMode]);

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
  max_turns_per_run: 200
  max_cost_per_run: 1.0
`;

  const inputCls =
    "w-full rounded-md border border-line bg-ground px-3 py-2 text-[13px] text-ink outline-none transition focus:border-accent placeholder:text-ink-faint";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/25"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-line bg-surface shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[15px] font-semibold text-ink">
              {mode === "form" ? "New agent" : "Import agent"}
            </h2>
            <p className="mt-0.5 text-[12px] text-ink-3">
              {mode === "form"
                ? "Name it, pick a model, describe who it is."
                : "Bring in an agent defined as YAML."}
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Segmented tab switcher */}
        <div className="px-5 pt-4">
          <FilterPills
            pills={[
              { key: "form", label: "Form" },
              { key: "yaml", label: "Import YAML" },
            ]}
            active={mode}
            onChange={(k) => {
              setMode(k as "form" | "yaml");
              setError("");
            }}
            variant="segmented"
          />
        </div>

        <div className="max-h-[55vh] space-y-4 overflow-y-auto p-5">
          {error && (
            <div className="rounded-md bg-danger-tint px-3 py-2 text-[12px] text-danger">
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
                  className={inputCls}
                  autoFocus
                />
              </Field>

              <div className="grid grid-cols-2 gap-4">
                <Field label="Provider">
                  <Select
                    value={providerId}
                    onChange={setProviderId}
                    options={providers.map((p) => ({ value: p.id, label: p.name }))}
                    className={inputCls}
                    align="left" panelClassName="text-[13px]"
                  />
                  {providers.length === 0 && (
                    <p className="mt-1 text-[11px] text-accent">
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

              <Field label="Soul" hint="Identity, values, principles">
                <textarea
                  value={soul}
                  onChange={(e) => setSoul(e.target.value)}
                  placeholder="What this agent believes in, its core values..."
                  rows={3}
                  className={`${inputCls} resize-none`}
                />
              </Field>

              <Field label="Persona" hint="Tone, communication style">
                <textarea
                  value={persona}
                  onChange={(e) => setPersona(e.target.value)}
                  placeholder="How this agent talks, its personality..."
                  rows={3}
                  className={`${inputCls} resize-none`}
                />
              </Field>

              <Field label="Task" hint="Mission, instructions">
                <textarea
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  placeholder="What this agent should do, its mission..."
                  rows={3}
                  className={`${inputCls} resize-none`}
                />
              </Field>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Upload className="h-3.5 w-3.5" />
                  Upload .yaml file
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setYamlText(YAML_TEMPLATE)}
                >
                  <FileText className="h-3.5 w-3.5" />
                  Load template
                </Button>
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
                  className={`${inputCls} resize-none font-mono text-[12px]`}
                  autoFocus
                />
              </Field>

              <p className="text-[11px] leading-[16px] text-ink-3">
                The YAML must include <code className="font-mono">id</code> and <code className="font-mono">name</code>.
                Leave <code className="font-mono">capabilities</code> empty to enable all tools, or list specific ones to restrict.
                If an agent with the same <code className="font-mono">id</code> already exists, it will be updated.
              </p>
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-line px-5 py-3.5">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={mode === "form" ? handleCreate : handleImportYaml}
            disabled={saving || (mode === "form" ? !name.trim() : !yamlText.trim())}
          >
            {saving ? "Creating…" : mode === "form" ? "Create agent" : "Import agent"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 flex items-baseline justify-between text-[12px] font-medium text-ink-2">
        {label}
        {hint && <span className="text-[11px] font-normal text-ink-3">{hint}</span>}
      </label>
      {children}
    </div>
  );
}
