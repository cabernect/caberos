import { useCallback, useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { Provider, ToolBindingInfo } from "@/lib/types";
import { Select } from "@/components/ui/select";
import { Field } from "./shared";

// --- Tools tab (W5) -------------------------------------------------------

function ToolStatusChip({ tool }: { tool: ToolBindingInfo }) {
  const label = !tool.implemented
    ? "Not yet available"
    : tool.state === "ready"
      ? tool.binding ? "Configured" : "Using defaults"
      : tool.state === "unconfigured"
        ? "Not configured"
        : "Needs attention";
  const tone = !tool.implemented
    ? "var(--ink-3)"
    : tool.state === "ready"
      ? "var(--accent)"
      : tool.state === "unconfigured"
        ? "var(--ink-3)"
        : "var(--danger)";
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ background: "var(--sunken)", color: tone }}
    >
      {label}
    </span>
  );
}

const ENGINE_LABELS: Record<string, string> = {
  duckduckgo: "DuckDuckGo",
  brave: "Brave",
  startpage: "Startpage",
  yahoo: "Yahoo",
  mojeek: "Mojeek",
  wikipedia: "Wikipedia",
};

const engineLabel = (key: string) => ENGINE_LABELS[key] ?? key;

/** Search backends that dispatch through a Provider-stored credential. */
const SPEECH_SERVICE_LABELS: Record<string, string> = {
  elevenlabs: "ElevenLabs",
};

const SEARCH_SERVICE_LABELS: Record<string, string> = {
  tavily: "Tavily",
  exa: "Exa",
  firecrawl: "Firecrawl Cloud",
  firecrawl_self_hosted: "Firecrawl self-hosted",
  brave_search: "Brave Search",
};
const SELF_HOSTED_BACKEND = "firecrawl_self_hosted";
const SEARCH_BACKEND_LABELS: Record<string, string> = {
  ddgs: "DDGS (free)",
  tavily: "Tavily API",
  exa: "Exa API",
  firecrawl: "Firecrawl Cloud",
  firecrawl_self_hosted: "Firecrawl self-hosted",
  brave_search: "Brave Search API",
};

const TERMINAL_BACKEND_LABELS: Record<string, string> = {
  auto: "Auto (OS-native)",
  seatbelt: "Seatbelt (macOS)",
  bwrap: "Bubblewrap (Linux)",
  mxc: "MXC (Windows, experimental)",
};

const backendOptionLabel = (toolKey: string, choice: string) =>
  toolKey === "exec.terminal"
    ? (TERMINAL_BACKEND_LABELS[choice] ?? choice)
    : (SEARCH_BACKEND_LABELS[choice] ?? choice);

function EngineOrderField({
  value,
  choices,
  onChange,
}: {
  value: string[];
  choices: string[];
  onChange: (v: string[]) => void;
}) {
  const remaining = choices.filter((c) => !value.includes(c));
  const move = (i: number, d: number) => {
    const next = [...value];
    const [item] = next.splice(i, 1);
    next.splice(i + d, 0, item);
    onChange(next);
  };
  return (
    <div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
        {value.map((engine, i) => (
          <div
            key={engine}
            className="group flex items-center gap-2 rounded-md border border-line bg-ground px-2 py-1"
          >
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--accent-bg)] text-[10px] font-semibold text-[var(--accent)]">
              {i + 1}
            </span>
            <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">
              {engineLabel(engine)}
            </span>
            <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
              <button
                type="button"
                disabled={i === 0}
                onClick={() => move(i, -1)}
                className="cursor-pointer text-ink-3 hover:text-ink disabled:opacity-30"
                title="Try earlier"
              >
                <ArrowUp className="h-3 w-3" />
              </button>
              <button
                type="button"
                disabled={i === value.length - 1}
                onClick={() => move(i, 1)}
                className="cursor-pointer text-ink-3 hover:text-ink disabled:opacity-30"
                title="Try later"
              >
                <ArrowDown className="h-3 w-3" />
              </button>
              <button
                type="button"
                onClick={() => onChange(value.filter((e) => e !== engine))}
                className="cursor-pointer text-ink-3 hover:text-[var(--danger)]"
                title="Disable engine"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        ))}
        {remaining.length > 0 && (
          <Select
            value=""
            onChange={(v) => {
              if (v) onChange([...value, v]);
            }}
            options={[
              { value: "", label: "+ engine" },
              ...remaining.map((e) => ({ value: e, label: engineLabel(e) })),
            ]}
            className="h-full w-full rounded-md border border-dashed border-line px-2 py-1 text-[12px] text-ink-3 outline-none"
          />
        )}
      </div>
    </div>
  );
}

export function ToolsTab({ providers }: { providers: Provider[] }) {
  const { confirm, toast } = useConfirm();
  const [tools, setTools] = useState<ToolBindingInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // per-key draft state: options for engine tools, provider/model for model tools
  const [drafts, setDrafts] = useState<
    Record<string, { options: Record<string, unknown>; providerId: string; model: string }>
  >({});
  const [saving, setSaving] = useState<string | null>(null);
  const [searchProviders, setSearchProviders] = useState<Provider[]>([]);
  const [speechProviders, setSpeechProviders] = useState<Provider[]>([]);
  // Per-tool draft for "+ New connection" — dedicated speech provider types.
  const [speechNew, setSpeechNew] = useState<
    Record<string, { name: string; apiKey: string }>
  >({});
  const [searchName, setSearchName] = useState("");
  const [searchApiKey, setSearchApiKey] = useState("");
  const [deletingSearchKey, setDeletingSearchKey] = useState(false);
  const [testingSearch, setTestingSearch] = useState(false);
  const [searchTestResult, setSearchTestResult] = useState("");
  const [searchUrl, setSearchUrl] = useState("");
  const [searchAllowPrivate, setSearchAllowPrivate] = useState(false);
  // providerId → modality-filtered catalog model ids (assistive suggestions
  // for the free-text model field; failures stay silent — not a hard gate)
  const [catalogModels, setCatalogModels] = useState<Record<string, string[]>>({});

  const loadModelSuggestions = useCallback(
    async (providerId: string, modalities: string[] | null) => {
      if (!providerId || !modalities?.length || catalogModels[providerId]) return;
      try {
        const [catalogResp, discoveredResp] = await Promise.all([
          api.listCatalogModels(providerId),
          // Provider-reported availability (D40) — live-discovered offerings
          // count even when the catalog snapshot doesn't know the model yet.
          api.listModels(providerId).catch(() => ({ models: [] })),
        ]);
        const catalogIds = catalogResp.models
          .filter((m) =>
            modalities.every((mod) => (m.output_modalities ?? []).includes(mod)),
          )
          .map((m) => m.id);
        const discoveredIds = discoveredResp.models
          .filter(
            (m) =>
              m.availability === "available" &&
              m.model_kind === "media" &&
              modalities.every((mod) =>
                m.output_modalities
                  ? (m.output_modalities ?? []).includes(mod)
                  : m.id.toLowerCase().includes(mod),
              ),
          )
          .map((m) => m.id);
        setCatalogModels((prev) => ({
          ...prev,
          [providerId]: [...new Set([...catalogIds, ...discoveredIds])].sort(),
        }));
      } catch {
        /* suggestions are assistive — catalog misses stay quiet */
      }
    },
    [catalogModels],
  );

  const load = useCallback(async () => {
    try {
      const [r, services, speechServices] = await Promise.all([
        api.listToolBindings(),
        api.listProviders("search"),
        api.listProviders("speech"),
      ]);
      setTools(r.tools);
      setSearchProviders(services);
      setSpeechProviders(speechServices);
      const boundSearch = r.tools.find((t) => t.key === "search.web");
      const boundSearchProvider = services.find(
        (p) => p.id === boundSearch?.binding?.provider_id,
      );
      setSearchName(boundSearchProvider?.name ?? "");
      setSearchUrl(boundSearchProvider?.base_url ?? "");
      setSearchAllowPrivate(boundSearchProvider?.extra_params?.allow_private_network === true);
      setDrafts((prev) => {
        const next = { ...prev };
        for (const t of r.tools) {
          if (!next[t.key]) {
            next[t.key] = {
              options: { ...t.options },
              providerId: t.binding?.provider_id ?? "",
              model: t.binding?.model ?? "",
            };
          } else {
            // Refresh options from server only when not mid-edit? Options are
            // cheap — prefer the server's truth so stale drafts can't write.
            next[t.key] = {
              options: { ...t.options },
              providerId: t.binding?.provider_id ?? "",
              model: t.binding?.model ?? "",
            };
          }
        }
        return next;
      });
      setError("");
      // Warm model suggestions for already-bound providers.
      for (const t of r.tools) {
        if (t.kind === "model" && t.binding?.provider_id) {
          void loadModelSuggestions(t.binding.provider_id, t.model_modalities);
        }
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [loadModelSuggestions]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (tool: ToolBindingInfo) => {
    const draft = drafts[tool.key];
    if (!draft) return;
    setSaving(tool.key);
    try {
      let providerId = draft.providerId;
      const backend = String(draft.options.backend ?? "");
      const serviceType = tool.key === "search.web" ? SEARCH_SERVICE_LABELS[backend] : undefined;
      const selfHosted = backend === SELF_HOSTED_BACKEND;
      if (serviceType) {
        if (!providerId && !searchApiKey.trim() && !selfHosted) {
          throw new Error(`Enter a ${serviceType} API key to create a search connection.`);
        }
        if (!providerId && selfHosted && !searchUrl.trim()) {
          throw new Error("Enter the self-hosted Firecrawl server URL.");
        }
        const serviceData = {
          name: searchName.trim() || `${serviceType} search`,
          ...(searchApiKey.trim() ? { api_key: searchApiKey.trim() } : {}),
          ...(selfHosted
            ? {
                base_url: searchUrl.trim(),
                extra_params: { allow_private_network: searchAllowPrivate },
              }
            : {}),
        };
        if (providerId) {
          await api.updateProvider(providerId, {
            ...serviceData,
          });
        } else {
          const created = await api.createProvider({ ...serviceData, type: backend });
          providerId = created.id;
          setSearchProviders((prev) => [...prev, created]);
          setDrafts((prev) => ({
            ...prev, [tool.key]: { ...prev[tool.key], providerId },
          }));
        }
        setSearchApiKey("");
        setSearchTestResult("");
      }
      // Speech card "+ New connection" — create the dedicated provider inline
      // (encrypted custody, same as search) before binding it.
      if (providerId.startsWith("new:")) {
        const type = providerId.slice(4);
        const newDraft = speechNew[tool.key] ?? { name: "", apiKey: "" };
        if (!newDraft.apiKey.trim()) {
          throw new Error(`Enter a ${SPEECH_SERVICE_LABELS[type] ?? type} API key.`);
        }
        const created = await api.createProvider({
          type,
          name: newDraft.name.trim() || `${SPEECH_SERVICE_LABELS[type] ?? type} speech`,
          api_key: newDraft.apiKey.trim(),
        });
        providerId = created.id;
        setSpeechProviders((prev) => [...prev, created]);
        setSpeechNew((prev) => ({ ...prev, [tool.key]: { name: "", apiKey: "" } }));
      }
      const body =
        tool.kind === "engine"
          ? {
              ...(serviceType ? { provider_id: providerId } : {}),
              options: draft.options,
              expected_revision: tool.binding?.revision ?? null,
            }
          : {
              provider_id: providerId || null,
              model: draft.model,
              options: draft.options,
              expected_revision: tool.binding?.revision ?? null,
            };
      await api.updateToolBinding(tool.key, body);
      await load();
      toast(`${tool.title} saved`);
    } catch (e: any) {
      if (e?.status === 409) {
        toast("Settings changed elsewhere — reloaded the latest values");
        await load();
      } else {
        toast(String(e?.message ?? e));
      }
    } finally {
      setSaving(null);
    }
  };

  const testSearch = async () => {
    const providerId = drafts["search.web"]?.providerId;
    if (!providerId || searchApiKey) return;
    const serviceType =
      SEARCH_SERVICE_LABELS[String(drafts["search.web"]?.options.backend ?? "")] ?? "search";
    const consent = await confirm({
      title: `Test ${serviceType} connection?`,
      message: `Sends one synthetic query to ${serviceType}. This may use paid credits; no conversation or workspace content is sent.`,
      confirmLabel: "Test connection",
    });
    if (!consent) return;
    setTestingSearch(true);
    setSearchTestResult("");
    try {
      const result = await api.testSearchProvider(providerId);
      setSearchTestResult(result.ok ? "Connection test passed." : result.error ?? "Connection test failed.");
    } catch {
      setSearchTestResult("Connection test failed. Check credentials and try again.");
    } finally {
      setTestingSearch(false);
    }
  };

  const deleteSearchKey = async () => {
    const providerId = drafts["search.web"]?.providerId;
    if (!providerId) return;
    setDeletingSearchKey(true);
    try {
      await api.updateProvider(providerId, { remove_api_key: true });
      setSearchProviders((prev) =>
        prev.map((p) => (p.id === providerId ? { ...p, has_key: false } : p)),
      );
      setSearchApiKey("");
      setSearchTestResult("");
    } catch (e) {
      toast(String(e));
    } finally {
      setDeletingSearchKey(false);
    }
  };

  const reset = async (tool: ToolBindingInfo) => {
    const ok = await confirm({
      title: `Reset ${tool.title}?`,
      message: "This returns the tool to its built-in defaults.",
      confirmLabel: "Reset",
    });
    if (!ok) return;
    try {
      await api.resetToolBinding(tool.key);
      await load();
      toast(`${tool.title} reset to defaults`);
    } catch (e) {
      toast(String(e));
    }
  };

  if (loading) {
    return <p className="text-sm text-[var(--ink-3)]">Loading tools…</p>;
  }

  return (
    <div className="max-w-4xl space-y-4">
      {error && (
        <p className="rounded-md border border-[var(--danger)]/30 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
          {error}
        </p>
      )}
      <p className="text-[13px] text-[var(--ink-2)]">
        Tool bindings choose how a supported tool executes — engine options or
        a provider/model. They don't grant capabilities; each agent's
        permissions still decide who may use them.
      </p>
      {tools
        .filter((t) => t.implemented)
        .map((tool) => {
        const draft = drafts[tool.key] ?? {
          options: {},
          providerId: "",
          model: "",
        };
        const isSearch = tool.key === "search.web";
        const isTerminal = tool.key === "exec.terminal";
        // Match the Select's display fallback — an unset backend is its default.
        const backend = String(
          draft.options.backend ??
            tool.options_schema.find((f) => f.name === "backend")?.default ??
            "",
        );
        const serviceType = isSearch ? SEARCH_SERVICE_LABELS[backend] : undefined;
        const serviceSearch = Boolean(serviceType);
        const selfHosted = backend === SELF_HOSTED_BACKEND;
        const selectedSearch = searchProviders.find((p) => p.id === draft.providerId);
        const setOption = (name: string, v: unknown) =>
          setDrafts((d) => ({
            ...d,
            [tool.key]: {
              ...d[tool.key],
              options: { ...d[tool.key].options, [name]: v },
            },
          }));
        return (
          <section
            key={tool.key}
            className="rounded-xl p-5"
            style={{
              border: "1px solid var(--border-soft)",
              background: "var(--surface)",
            }}
          >
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-[var(--ink)]">
                {tool.title}
              </h2>
              <ToolStatusChip tool={tool} />
            </div>
            <p className="mt-1 text-[12px] text-[var(--ink-3)]">
              {tool.description}
            </p>
            <div className="mt-4 space-y-3">
                {tool.reason && tool.state !== "ready" && (
                  <p
                    className="text-[12px]"
                    style={{
                      color:
                        tool.state === "invalid"
                          ? "var(--danger)"
                          : "var(--ink-3)",
                    }}
                  >
                    {tool.reason}
                  </p>
                )}
                {tool.kind === "model" && (
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Provider">
                      <Select
                        value={draft.providerId}
                        onChange={(v) => {
                          setDrafts((d) => ({
                            ...d,
                            [tool.key]: {
                              ...d[tool.key],
                              providerId: v,
                              // Model ids are provider-namespaced — the old
                              // provider's id is wrong under a new provider.
                              model: "",
                            },
                          }));
                          void loadModelSuggestions(v, tool.model_modalities);
                        }}
                        options={[
                          { value: "", label: "Choose provider…" },
                          ...[...providers, ...speechProviders]
                            .filter(
                              (p) =>
                                !tool.service_types?.length ||
                                tool.service_types.includes(p.type),
                            )
                            .map((p) => ({
                              value: p.id,
                              label: `${p.name} (${p.type})`,
                            })),
                          ...(tool.service_types ?? [])
                            .filter((t) => SPEECH_SERVICE_LABELS[t])
                            .map((t) => ({
                              value: `new:${t}`,
                              label: `＋ New ${SPEECH_SERVICE_LABELS[t]} connection`,
                            })),
                        ]}
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink outline-none"
                      />
                    </Field>
                    <Field label="Model">
                      <input
                        list={`catalog-models-${tool.key}`}
                        value={draft.model}
                        onChange={(e) =>
                          setDrafts((d) => ({
                            ...d,
                            [tool.key]: {
                              ...d[tool.key],
                              model: e.target.value,
                            },
                          }))
                        }
                        placeholder="e.g. gpt-image-1"
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 font-mono text-[12px] text-ink outline-none"
                      />
                      <datalist id={`catalog-models-${tool.key}`}>
                        {(catalogModels[draft.providerId] ?? []).map((id) => (
                          <option key={id} value={id} />
                        ))}
                      </datalist>
                    </Field>
                  </div>
                )}
                {tool.kind === "model" && draft.providerId.startsWith("new:") && (
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Connection name">
                      <input
                        value={speechNew[tool.key]?.name ?? ""}
                        onChange={(e) =>
                          setSpeechNew((prev) => ({
                            ...prev,
                            [tool.key]: { name: e.target.value, apiKey: prev[tool.key]?.apiKey ?? "" },
                          }))
                        }
                        placeholder={`${SPEECH_SERVICE_LABELS[draft.providerId.slice(4)] ?? "Speech"} speech`}
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink outline-none"
                      />
                    </Field>
                    <Field label="API key">
                      <input
                        type="password"
                        autoComplete="new-password"
                        value={speechNew[tool.key]?.apiKey ?? ""}
                        onChange={(e) =>
                          setSpeechNew((prev) => ({
                            ...prev,
                            [tool.key]: { name: prev[tool.key]?.name ?? "", apiKey: e.target.value },
                          }))
                        }
                        placeholder="Stored encrypted — write-only"
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink outline-none"
                      />
                    </Field>
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {tool.options_schema.filter((field) => !isSearch || (
                    field.name === "backend" ||
                    !field.backends?.length ||
                    field.backends.includes(backend)
                  )).map((field) => (
                    <div
                      key={field.name}
                      className={field.kind === "engine_order" ? "sm:col-span-2" : ""}
                    >
                      <Field label={field.label}>
                        {field.kind === "engine_order" ? (
                      <EngineOrderField
                        value={
                          (draft.options[field.name] as string[] | undefined) ??
                          []
                        }
                        choices={field.choices}
                        onChange={(v) => setOption(field.name, v)}
                      />
                    ) : field.kind === "select" ? (
                      <Select
                        ariaLabel={field.label}
                        disabled={testingSearch || saving !== null}
                        value={String(draft.options[field.name] ?? field.default ?? "")}
                        onChange={(v) => {
                          setOption(field.name, v);
                          // A backend switch invalidates the selected connection —
                          // providers are typed per service, and a stale id would
                          // either fail validation or bind the wrong service.
                          if (isSearch && field.name === "backend" && v !== backend) {
                            setDrafts((d) => ({
                              ...d,
                              [tool.key]: { ...d[tool.key], providerId: "" },
                            }));
                            setSearchName("");
                            setSearchUrl("");
                            setSearchAllowPrivate(false);
                            setSearchApiKey("");
                            setSearchTestResult("");
                          }
                        }}
                        options={field.choices.map((c) => ({
                          value: c,
                          label: field.name === "backend"
                            ? backendOptionLabel(tool.key, c)
                            : c,
                        }))}
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink outline-none"
                      />
                    ) : field.kind === "boolean" ? (
                      <input
                        type="checkbox"
                        checked={Boolean(draft.options[field.name] ?? field.default)}
                        onChange={(e) => setOption(field.name, e.target.checked)}
                      />
                    ) : field.kind === "number" ? (
                      <input
                        type="number"
                        value={String(draft.options[field.name] ?? field.default ?? "")}
                        onChange={(e) => setOption(field.name, Number(e.target.value))}
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink outline-none"
                      />
                    ) : (
                      <input
                        value={String(draft.options[field.name] ?? field.default ?? "")}
                        onChange={(e) => setOption(field.name, e.target.value)}
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 font-mono text-[12px] text-ink outline-none"
                      />
                    )}
                      </Field>
                    </div>
                  ))}
                </div>
                {isTerminal && tool.backends && (
                  <div className="space-y-1">
                    {tool.backends.map((b) => (
                      <p key={b.name} className="text-[12px] text-[var(--ink-3)]">
                        <span className="font-medium text-[var(--ink-2)]">
                          {TERMINAL_BACKEND_LABELS[b.name] ?? b.name}
                        </span>
                        {" — "}
                        {!b.supported_here
                          ? (b.reason ?? "not supported on this OS")
                          : b.available
                            ? `${b.os_requirement} · installed${b.experimental ? " · experimental (not a vendor-attested security boundary)" : ""}${b.auto ? " · Auto resolves here" : ""}`
                            : `${b.os_requirement} · ${b.reason ?? "not installed"}`}
                      </p>
                    ))}
                    <p className="text-[12px] text-[var(--ink-3)]">
                      Applies to new terminal sessions; open mode always runs
                      unsandboxed on the host.
                    </p>
                  </div>
                )}
                {serviceSearch && (
                  <div className="space-y-3">
                    <Field label="Search connection">
                      <Select
                        ariaLabel="Search connection"
                        disabled={testingSearch || saving !== null}
                        value={draft.providerId}
                        options={[
                          { value: "", label: `New ${serviceType} connection` },
                          ...searchProviders.filter((p) => p.type === backend).map((p) => ({
                            value: p.id, label: p.name,
                          })),
                        ]}
                        onChange={(id) => {
                          setDrafts((prev) => ({
                            ...prev, [tool.key]: { ...prev[tool.key], providerId: id },
                          }));
                          const provider = searchProviders.find((p) => p.id === id);
                          setSearchName(provider?.name ?? "");
                          setSearchUrl(provider?.base_url ?? "");
                          setSearchAllowPrivate(provider?.extra_params?.allow_private_network === true);
                          setSearchApiKey("");
                          setSearchTestResult("");
                        }}
                        className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink"
                      />
                    </Field>
                    {selfHosted && (
                      <label className="space-y-1 text-[12px] text-ink-2">
                        <span>Firecrawl server URL</span>
                        <input
                          value={searchUrl}
                          disabled={testingSearch || saving !== null}
                          onChange={(e) => {
                            setSearchUrl(e.target.value);
                            setSearchTestResult("");
                          }}
                          placeholder="https://firecrawl.example.internal"
                          className="w-full rounded-md border border-line bg-ground px-3 py-1.5 font-mono text-[12px] text-ink"
                        />
                      </label>
                    )}
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <label className="space-y-1 text-[12px] text-ink-2">
                        <span>Connection name</span>
                        <input
                          value={searchName}
                          disabled={testingSearch || saving !== null}
                          onChange={(e) => setSearchName(e.target.value)}
                          placeholder={`${serviceType} search`}
                          className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink"
                        />
                      </label>
                      <label className="space-y-1 text-[12px] text-ink-2">
                        <span>{selfHosted ? `${serviceType} API key (optional)` : `${serviceType} API key`}</span>
                        <div className="flex gap-2">
                          <input
                            type="password"
                            autoComplete="new-password"
                            value={searchApiKey}
                            disabled={Boolean(selectedSearch?.has_key) || testingSearch || saving !== null}
                            onChange={(e) => {
                              setSearchApiKey(e.target.value);
                              setSearchTestResult("");
                            }}
                            placeholder={selectedSearch?.has_key ? "Stored securely" : "Enter API key"}
                            className="w-full rounded-md border border-line bg-ground px-3 py-1.5 text-[13px] text-ink disabled:opacity-60"
                          />
                          {selectedSearch?.has_key && (
                            <button
                              type="button"
                              disabled={deletingSearchKey || testingSearch || saving !== null}
                              onClick={() => void deleteSearchKey()}
                              className="shrink-0 cursor-pointer rounded-md border border-line px-2.5 text-[12px] text-ink-2 transition hover:bg-sunken disabled:opacity-50"
                            >
                              {deletingSearchKey ? "Deleting…" : "Delete key"}
                            </button>
                          )}
                        </div>
                      </label>
                    </div>
                    {selfHosted && (
                      <label className="flex items-center gap-2 text-[12px] text-ink-2">
                        <input
                          type="checkbox"
                          checked={searchAllowPrivate}
                          disabled={testingSearch || saving !== null}
                          onChange={(e) => setSearchAllowPrivate(e.target.checked)}
                        />
                        Allow private-network addresses (LAN). Leave off for public servers only.
                      </label>
                    )}
                    <p className="text-[12px] text-ink-3">
                      Saved keys are encrypted in Providers storage. Saving sends no search request.
                    </p>
                    <button
                      type="button"
                      disabled={!selectedSearch || (!selfHosted && !selectedSearch.has_key) || !!searchApiKey || testingSearch || saving !== null}
                      onClick={() => void testSearch()}
                      className="cursor-pointer rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {testingSearch ? "Testing..." : "Test connection (may use credits)"}
                    </button>
                    <p role="status" className="text-[12px] text-ink-2">{searchTestResult}</p>
                  </div>
                )}
                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => void save(tool)}
                    disabled={saving !== null || testingSearch}
                    className="cursor-pointer rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition hover:opacity-90 disabled:opacity-50"
                  >
                    {saving === tool.key ? "Saving…" : tool.binding ? "Save" : "Save configuration"}
                  </button>
                  {tool.binding && (
                    <button
                      type="button"
                      onClick={() => void reset(tool)}
                      className="cursor-pointer rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 transition hover:bg-sunken"
                    >
                      Reset to defaults
                    </button>
                  )}
                  {tool.state === "ready" && !tool.binding && (
                    <span className="text-[11px] text-[var(--ink-3)]">
                      Running on built-in defaults — saving creates a binding.
                    </span>
                  )}
                </div>
              </div>
          </section>
        );
      })}
      {tools.some((t) => !t.implemented) && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {tools
            .filter((t) => !t.implemented)
            .map((tool) => (
              <section
                key={tool.key}
                className="rounded-xl border border-dashed border-line p-4"
                style={{ background: "var(--surface)" }}
              >
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-semibold text-[var(--ink-2)]">
                    {tool.title}
                  </h2>
                  <ToolStatusChip tool={tool} />
                </div>
                <p className="mt-1 text-[12px] text-[var(--ink-3)]">
                  {tool.description}
                </p>
                <p className="mt-2 text-[12px] text-[var(--ink-3)]">
                  {tool.planned_note ?? "Planned for a future release."}
                </p>
              </section>
            ))}
        </div>
      )}
    </div>
  );
}
