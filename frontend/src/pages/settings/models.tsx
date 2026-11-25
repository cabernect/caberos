import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Cpu,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirmHook";
import type { Agent, ModelInfo, Provider } from "@/lib/types";
import { Select } from "@/components/ui/select";
import { ProviderTile } from "./shared";

/** Compact capability hint — " · 128K · thinking · vision" — used on both
 * catalog picker options and mapped rows. Only documented flags surface. */
function capabilitySuffix(m: {
  context_window_tokens?: number | null;
  supports_thinking?: boolean | null;
  supports_vision?: boolean | null;
}): string {
  const bits = [
    m.context_window_tokens
      ? `${Math.round(m.context_window_tokens / 1000)}K`
      : null,
    m.supports_thinking ? "thinking" : null,
    m.supports_vision ? "vision" : null,
  ].filter(Boolean);
  return bits.length ? ` · ${bits.join(" · ")}` : "";
}

/** Declared catalog-identity editor for alias providers. Local snapshot
 * read only — the operator picks the exact catalog model their deployment
 * name actually serves. */
function CatalogMappingEditor({
  provider,
  model,
  onDone,
}: {
  provider: Provider;
  model: ModelInfo;
  onDone: () => void;
}) {
  const [catalogProviders, setCatalogProviders] = useState<
    { id: string; name: string; models: number }[]
  >([]);
  const [catalogProviderId, setCatalogProviderId] = useState(
    model.catalog_provider_id || "",
  );
  const [catalogModels, setCatalogModels] = useState<
    {
      id: string;
      name: string;
      context_window_tokens: number | null;
      supports_thinking?: boolean | null;
      supports_vision?: boolean | null;
    }[]
  >([]);
  const [catalogModelId, setCatalogModelId] = useState(
    model.catalog_model_id || "",
  );
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const { toast } = useConfirm();

  useEffect(() => {
    let cancelled = false;
    setLoadingCatalog(true);
    api
      .listCatalogModels(provider.id, catalogProviderId || undefined)
      .then((r) => {
        if (cancelled) return;
        setCatalogProviders(r.providers);
        setCatalogModels(r.models);
        if (!catalogProviderId && r.catalog_provider_id)
          setCatalogProviderId(r.catalog_provider_id);
      })
      .catch((e) => {
        if (!cancelled) toast(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoadingCatalog(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id, catalogProviderId]);

  const filteredModels = catalogModels.filter((m) => {
    if (!filter.trim()) return true;
    const q = filter.trim().toLowerCase();
    return m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q);
  });

  const save = async () => {
    if (!catalogProviderId || !catalogModelId) return;
    setSaving(true);
    try {
      await api.setModelMetadata(provider.id, model.name, {
        catalog_provider_id: catalogProviderId,
        catalog_model_id: catalogModelId,
      });
      onDone();
    } catch (e) {
      toast(String(e));
      setSaving(false);
    }
  };

  const clear = async () => {
    setSaving(true);
    try {
      await api.setModelMetadata(provider.id, model.name, {
        clear_catalog_mapping: true,
      });
      onDone();
    } catch (e) {
      toast(String(e));
      setSaving(false);
    }
  };

  return (
    <div
      className="mt-1.5 rounded-lg border px-3 py-2.5"
      style={{ borderColor: "var(--border-soft)", background: "var(--ground)" }}
    >
      <p className="mb-2 text-[11px] text-[var(--ink-3)]">
        Which catalog model does <span className="font-mono">{model.name}</span>{" "}
        actually serve?
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={catalogProviderId}
          onChange={(v) => {
            setCatalogProviderId(v);
            setCatalogModelId("");
          }}
          options={catalogProviders.map((p) => ({
            value: p.id,
            label: `${p.name} (${p.models})`,
          }))}
          ariaLabel="Catalog provider"
          placeholder="Catalog provider"
          className="w-56 rounded-lg border border-[var(--border)] bg-surface px-2.5 py-1.5 text-[12px] text-[var(--ink)] outline-none"
          align="left"
          panelClassName="text-[12px]"
        />
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--ink-3)]" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter catalog models…"
            className="w-full rounded-lg border px-2.5 py-1.5 pl-7 text-[12px] text-[var(--ink)] outline-none"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface)",
            }}
          />
        </div>
        <Select
          value={catalogModelId}
          onChange={setCatalogModelId}
          options={filteredModels.map((m) => ({
            value: m.id,
            label: `${m.name}${capabilitySuffix(m)}`,
          }))}
          ariaLabel="Catalog model"
          placeholder={
            loadingCatalog
              ? "Loading…"
              : catalogModels.length === 0
                ? "No models in catalog"
                : filteredModels.length === 0
                  ? "No matches"
                  : "Choose catalog model"
          }
          className="w-72 rounded-lg border border-[var(--border)] bg-surface px-2.5 py-1.5 text-[12px] text-[var(--ink)] outline-none"
          align="left"
          panelClassName="text-[12px]"
        />
        <button
          onClick={save}
          disabled={!catalogProviderId || !catalogModelId || saving}
          className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-[12px] font-medium"
          style={{
            background: "var(--ink)",
            color: "var(--white)",
            opacity: catalogProviderId && catalogModelId && !saving ? 1 : 0.5,
          }}
        >
          <Check className="h-3 w-3" />
          {saving ? "Saving…" : "Save"}
        </button>
        {model.catalog_mapping_explicit && (
          <button
            onClick={clear}
            disabled={saving}
            className="rounded-lg border px-2.5 py-1.5 text-[11px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-50"
            style={{ borderColor: "var(--border)" }}
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

export function ModelsTab({
  providers,
  loading,
  onChanged,
}: {
  providers: Provider[];
  loading: boolean;
  onChanged: () => void;
}) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [discovered, setDiscovered] = useState<Record<string, ModelInfo[]>>({});
  const [discovering, setDiscovering] = useState<Record<string, boolean>>({});
  const [customProviderId, setCustomProviderId] = useState("");
  const [customName, setCustomName] = useState("");
  const [savingCustom, setSavingCustom] = useState(false);
  const [chipPage, setChipPage] = useState<Record<string, number>>({});
  const [mappingKey, setMappingKey] = useState<string | null>(null);
  const [mappingOpen, setMappingOpen] = useState<Set<string>>(new Set());
  const { toast } = useConfirm();
  const navigate = useNavigate();
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    api
      .listAgents()
      .then((a) => {
        if (mounted.current) setAgents(a);
      })
      .catch(() => {});
  }, []);

  const loadModels = useCallback((providerId: string) => {
    api
      .listModels(providerId)
      .then((r) => {
        if (mounted.current)
          setDiscovered((prev) => ({ ...prev, [providerId]: r.models }));
      })
      .catch(() => {});
  }, []);

  // Cached offerings are a local read — this never hits the provider.
  useEffect(() => {
    setCustomProviderId((prev) =>
      providers.some((p) => p.id === prev) ? prev : providers[0]?.id || "",
    );
    for (const p of providers) loadModels(p.id);
  }, [providers, loadModels]);

  const handleDiscover = async (provider: Provider) => {
    setDiscovering((prev) => ({ ...prev, [provider.id]: true }));
    const done = () =>
      setDiscovering((prev) => ({ ...prev, [provider.id]: false }));
    try {
      // Explicit refresh — schedules backend discovery; the GET itself is
      // local so the first read returns current offerings immediately.
      await api.refreshProviderModels(provider.id).catch(() => null);
      let waited = 0;
      for (;;) {
        if (!mounted.current) return;
        const resp = await api.listModels(provider.id);
        if (!mounted.current) return;
        setDiscovered((prev) => ({ ...prev, [provider.id]: resp.models }));
        if (resp.refresh_in_progress !== true) break;
        waited += 1;
        if (waited >= 60) {
          toast("Refresh is still running; re-check later");
          break;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (e) {
      if (mounted.current) toast(String(e));
    } finally {
      if (mounted.current) done();
    }
  };

  const discoverAll = () => {
    for (const p of providers) void handleDiscover(p);
  };

  const customProvider = providers.find((p) => p.id === customProviderId);

  const handleAddCustom = async () => {
    const name = customName.trim();
    if (!name || !customProvider) return;
    setSavingCustom(true);
    try {
      await api.addCustomModel(customProvider.id, name);
      setCustomName("");
      onChanged();
    } catch (e) {
      toast(String(e));
    } finally {
      if (mounted.current) setSavingCustom(false);
    }
  };

  const handleRemoveCustom = async (provider: Provider, modelName: string) => {
    try {
      await api.removeCustomModel(provider.id, modelName);
      onChanged();
    } catch (e) {
      toast(String(e));
    }
  };

  if (loading)
    return <p className="text-[13px] text-[var(--ink-2)]">Loading…</p>;
  if (providers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Cpu className="h-8 w-8 text-[var(--ink-3)]" />
        <p className="mt-3 text-[14px] text-[var(--ink-2)]">
          No providers configured
        </p>
        <p className="mt-1 text-[12px] text-[var(--ink-3)]">
          Add a provider first to manage models.
        </p>
      </div>
    );
  }

  // Group agents by (provider, model) for the In use table; agents with no
  // model get their own actionable rows.
  const providerName = (id: string | null) =>
    providers.find((p) => p.id === id)?.name ?? "—";
  const inUse = new Map<
    string,
    { model: string; provider: string; usedBy: string[] }
  >();
  const unsetAgents: Agent[] = [];
  for (const a of agents) {
    if (!a.model || !a.provider_id) {
      unsetAgents.push(a);
      continue;
    }
    const key = `${a.provider_id}::${a.model}`;
    const row = inUse.get(key) ?? {
      model: a.model,
      provider: providerName(a.provider_id),
      usedBy: [],
    };
    row.usedBy.push(a.name);
    inUse.set(key, row);
  }
  const inUseRows = [...inUse.values()].sort((a, b) =>
    a.model.localeCompare(b.model),
  );

  return (
    <div className="max-w-4xl space-y-8">
      {/* In use */}
      <section id="in-use">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">In use</h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          Models your agents are set to.
        </p>
        <div
          className="overflow-hidden rounded-xl border"
          style={{
            borderColor: "var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <table className="w-full text-left">
            <thead>
              <tr
                className="border-b text-[12px] font-medium text-[var(--ink-3)]"
                style={{ borderColor: "var(--border-soft)" }}
              >
                <th className="w-[30%] px-5 py-2.5 font-medium">Model</th>
                <th className="w-[20%] px-5 py-2.5 font-medium">Provider</th>
                <th className="px-5 py-2.5 font-medium">Used by</th>
              </tr>
            </thead>
            <tbody>
              {inUseRows.map((row) => (
                <tr
                  key={`${row.provider}:${row.model}`}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--border-soft)" }}
                >
                  <td className="whitespace-nowrap px-5 py-3 font-mono text-[13px] font-medium text-[var(--ink)]">
                    {row.model}
                  </td>
                  <td className="px-5 py-3 text-[13px] text-[var(--ink)]">
                    {row.provider}
                  </td>
                  <td className="px-5 py-3 text-[12px] text-[var(--ink-2)]">
                    {row.usedBy.join(", ")}
                  </td>
                </tr>
              ))}
              {unsetAgents.map((a) => (
                <tr
                  key={a.id}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--border-soft)" }}
                >
                  <td
                    className="whitespace-nowrap px-5 py-3 font-mono text-[13px] font-medium"
                    style={{ color: "var(--warning, #b45309)" }}
                  >
                    No model set
                  </td>
                  <td className="px-5 py-3" />
                  <td className="px-5 py-3 text-[12px] text-[var(--ink-2)]">
                    {a.name} ·{" "}
                    <button
                      onClick={() => navigate("/agents")}
                      className="font-medium underline-offset-2 hover:underline"
                      style={{ color: "var(--accent)" }}
                    >
                      Choose a model
                    </button>
                  </td>
                </tr>
              ))}
              {inUseRows.length === 0 && unsetAgents.length === 0 && (
                <tr>
                  <td
                    colSpan={3}
                    className="px-5 py-6 text-center text-[12px] text-[var(--ink-3)]"
                  >
                    No agents yet — create one to see its model here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Discover models */}
      <section id="discover">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-[14px] font-semibold text-[var(--ink)]">
              Discover models
            </h2>
            <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
              Fetch what each provider offers, then pick from the list when you
              set up an agent.
            </p>
          </div>
          <button
            onClick={discoverAll}
            disabled={providers.every((p) => discovering[p.id])}
            className="flex shrink-0 items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
            style={{ borderColor: "var(--border)" }}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Discover all
          </button>
        </div>
        <div className="space-y-2.5">
          {providers.map((provider) => {
            const all = discovered[provider.id] || [];
            const models = all.filter((m) => m.availability === "available");
            const chatModels = models.filter((m) => m.model_kind !== "media");
            const mediaModels = models.filter((m) => m.model_kind === "media");
            const errCount = all.filter((m) => m.discovery_error).length;
            const error =
              models.length === 0 && errCount > 0
                ? all.find((m) => m.discovery_error)?.discovery_error
                : null;
            const isDiscovering = discovering[provider.id];
            return (
              <div
                key={provider.id}
                className="rounded-xl border px-4 py-3.5"
                style={{
                  borderColor: "var(--border-soft)",
                  background: "var(--surface)",
                }}
              >
                <div className="flex items-center gap-3.5">
                  <ProviderTile name={provider.name} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-semibold text-[var(--ink)]">
                      {provider.name}
                    </p>
                    <p className="mt-0.5 text-[11px] text-[var(--ink-3)]">
                      {isDiscovering ? (
                        "Fetching models…"
                      ) : error ? (
                        <span style={{ color: "var(--danger)" }}>
                          Discovery failed: {error}
                        </span>
                      ) : models.length > 0 ? (
                        <>
                          {models.length} models fetched · prefix{" "}
                          <span className="font-mono">{provider.type}/</span>
                          {errCount > 0 && ` · ${errCount} unconfirmed`}
                        </>
                      ) : (
                        <>
                          No models fetched yet · prefix{" "}
                          <span className="font-mono">{provider.type}/</span>
                        </>
                      )}
                    </p>
                  </div>
                  <button
                    onClick={() => handleDiscover(provider)}
                    disabled={isDiscovering}
                    className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <RefreshCw
                      className={`h-3.5 w-3.5 ${isDiscovering ? "animate-spin" : ""}`}
                    />
                    Discover
                  </button>
                </div>
                {chatModels.length > 0 && (
                  <div
                    className="mt-3 border-t pt-3"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    <div className="flex flex-wrap gap-1.5">
                      {chatModels
                        .slice(
                          (chipPage[provider.id] || 0) * 24,
                          ((chipPage[provider.id] || 0) + 1) * 24,
                        )
                        .map((m) => (
                          <span
                            key={m.id}
                            className="rounded-full px-2.5 py-1 font-mono text-[11px]"
                            style={{
                              background: "var(--border)",
                              color: "var(--ink-2)",
                            }}
                            title={m.display_name || m.name}
                          >
                            {m.name}
                          </span>
                        ))}
                    </div>
                    {chatModels.length > 24 && (
                      <div className="mt-2 flex items-center justify-end gap-2">
                        <button
                          onClick={() =>
                            setChipPage((prev) => ({
                              ...prev,
                              [provider.id]: Math.max(
                                0,
                                (prev[provider.id] || 0) - 1,
                              ),
                            }))
                          }
                          disabled={(chipPage[provider.id] || 0) === 0}
                          aria-label="Previous page"
                          className="flex h-6 w-6 items-center justify-center rounded border text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-40"
                          style={{ borderColor: "var(--border)" }}
                        >
                          ‹
                        </button>
                        <span className="text-[11px] text-[var(--ink-3)]">
                          {(chipPage[provider.id] || 0) + 1}/
                          {Math.ceil(chatModels.length / 24)}
                        </span>
                        <button
                          onClick={() =>
                            setChipPage((prev) => ({
                              ...prev,
                              [provider.id]: Math.min(
                                Math.ceil(chatModels.length / 24) - 1,
                                (prev[provider.id] || 0) + 1,
                              ),
                            }))
                          }
                          disabled={
                            (chipPage[provider.id] || 0) >=
                            Math.ceil(chatModels.length / 24) - 1
                          }
                          aria-label="Next page"
                          className="flex h-6 w-6 items-center justify-center rounded border text-[var(--ink-2)] transition hover:bg-[var(--hover)] disabled:opacity-40"
                          style={{ borderColor: "var(--border)" }}
                        >
                          ›
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {mediaModels.length > 0 && (
                  <div
                    className="mt-2.5 border-t pt-2.5"
                    style={{ borderColor: "var(--border-soft)" }}
                  >
                    <p className="mb-1.5 text-[11px] font-medium text-[var(--ink-3)]">
                      Media models — not pickable for chat
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {mediaModels.map((m) => (
                        <span
                          key={m.id}
                          className="rounded-full border border-dashed px-2.5 py-1 font-mono text-[11px]"
                          style={{
                            borderColor: "var(--accent)",
                            color: "var(--ink-3)",
                          }}
                          title={m.display_name || m.name}
                        >
                          {m.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {(() => {
                  // Alias providers (azure deployments, bedrock profiles) carry
                  // operator-chosen names — catalog facts need a declared
                  // mapping. Also keep explicitly-mapped rows editable.
                  const unmapped = all.filter(
                    (m) =>
                      m.context_window_tokens == null ||
                      m.catalog_mapping_explicit,
                  );
                  if (unmapped.length === 0) return null;
                  const expanded = mappingOpen.has(provider.id);
                  return (
                    <div
                      className="mt-3 border-t pt-2.5"
                      style={{ borderColor: "var(--border-soft)" }}
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setMappingOpen((prev) => {
                            const next = new Set(prev);
                            if (next.has(provider.id)) next.delete(provider.id);
                            else next.add(provider.id);
                            return next;
                          })
                        }
                        className="flex w-full items-center gap-2 text-left"
                      >
                        {expanded ? (
                          <ChevronDown className="h-3 w-3 shrink-0 text-[var(--ink-3)]" />
                        ) : (
                          <ChevronRight className="h-3 w-3 shrink-0 text-[var(--ink-3)]" />
                        )}
                        <span className="text-[11px] font-medium text-[var(--ink-2)]">
                          Catalog mappings
                        </span>
                        <span className="rounded-full bg-sunken px-1.5 py-px text-[9px] font-medium text-ink-muted">
                          ×{unmapped.length}
                        </span>
                        <span className="truncate text-[10px] text-[var(--ink-3)]">
                          map a name to resolve context and pricing
                        </span>
                      </button>
                      {expanded && (
                        <>
                          <p className="mb-2 mt-2 text-[11px] text-[var(--ink-3)]">
                            Models without catalog metadata — map a name to its
                            catalog entry to resolve context limits and
                            pricing.
                          </p>
                          <div className="space-y-1">
                        {unmapped.map((m) => {
                          const key = `${provider.id}::${m.id}`;
                          const open = mappingKey === key;
                          return (
                            <div key={key}>
                              <div className="flex items-center gap-2.5">
                                <span className="font-mono text-[12px] text-[var(--ink)]">
                                  {m.name}
                                </span>
                                <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--ink-3)]">
                                  {m.catalog_mapping_explicit
                                    ? `declared → ${m.catalog_provider_id}/${m.catalog_model_id}${capabilitySuffix(m)}`
                                    : "unknown metadata"}
                                </span>
                                <button
                                  onClick={() =>
                                    setMappingKey(open ? null : key)
                                  }
                                  className="flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium text-[var(--ink-2)] transition hover:bg-[var(--hover)]"
                                  style={{ borderColor: "var(--border)" }}
                                >
                                  {open ? (
                                    <X className="h-3 w-3" />
                                  ) : (
                                    <Pencil className="h-3 w-3" />
                                  )}
                                  {open
                                    ? "Close"
                                    : m.catalog_mapping_explicit
                                      ? "Edit mapping"
                                      : "Map"}
                                </button>
                              </div>
                              {open && (
                                <CatalogMappingEditor
                                  provider={provider}
                                  model={m}
                                  onDone={() => {
                                    setMappingKey(null);
                                    loadModels(provider.id);
                                  }}
                                />
                              )}
                            </div>
                          );
                        })}
                          </div>
                        </>
                      )}
                    </div>
                  );
                })()}
              </div>
            );
          })}
        </div>
      </section>

      {/* Add a custom model */}
      <section id="custom">
        <h2 className="text-[14px] font-semibold text-[var(--ink)]">
          Add a custom model
        </h2>
        <p className="mb-3 mt-0.5 text-[12px] text-[var(--ink-3)]">
          For a model that doesn't show up in the list.
        </p>
        <div
          className="rounded-xl border p-5"
          style={{
            borderColor: "var(--border-soft)",
            background: "var(--surface)",
          }}
        >
          <div className="flex items-end gap-3">
            <div className="w-52">
              <label
                htmlFor="custom-model-provider"
                className="mb-1 block text-[12px] font-medium text-[var(--ink-3)]"
              >
                Provider
              </label>
              <Select
                value={customProviderId}
                onChange={setCustomProviderId}
                options={providers.map((p) => ({ value: p.id, label: p.name }))}
                ariaLabel="Provider"
                className="w-full rounded-lg border border-[var(--border)] bg-surface px-3 py-2 text-[13px] text-[var(--ink)] outline-none"
                align="left" panelClassName="text-[13px]"
              />
            </div>
            <div className="min-w-0 w-56">
              <label
                htmlFor="custom-model-name"
                className="mb-1 block text-[12px] font-medium text-[var(--ink-3)]"
              >
                Model name
              </label>
              <input
                id="custom-model-name"
                value={customName}
                onChange={(e) => setCustomName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAddCustom()}
                placeholder="model-name"
                className="w-full rounded-lg border px-3 py-2 font-mono text-[12px] text-[var(--ink)] outline-none"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--surface)",
                }}
              />
            </div>
            <button
              onClick={handleAddCustom}
              disabled={!customName.trim() || !customProvider || savingCustom}
              className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-[12px] font-medium"
              style={{
                background: "var(--ink)",
                color: "var(--white)",
                border: "1px solid var(--ink)",
                opacity:
                  customName.trim() && customProvider && !savingCustom
                    ? 1
                    : 0.5,
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Add model
            </button>
          </div>
          <p className="mt-3 text-[11px] text-[var(--ink-3)]">
            The provider prefix is added for you, so{" "}
            <span className="font-mono">model-name</span> is saved as{" "}
            <span className="font-mono">
              {customProvider?.type ?? "provider"}/model-name
            </span>
            .
          </p>
          {customProvider &&
            (customProvider.custom_models || []).length > 0 && (
              <div
                className="mt-4 flex flex-wrap gap-1.5 border-t pt-4"
                style={{ borderColor: "var(--border-soft)" }}
              >
                {(customProvider.custom_models || []).map((m) => (
                  <span
                    key={m}
                    className="flex items-center gap-1 rounded-full px-2.5 py-1 font-mono text-[11px]"
                    style={{
                      background: "var(--accent-bg)",
                      color: "var(--accent)",
                    }}
                    title={`${customProvider.type}/${m}`}
                  >
                    {m}
                    <button
                      onClick={() => handleRemoveCustom(customProvider, m)}
                      aria-label={`Remove ${m}`}
                      className="flex items-center"
                      style={{ border: "none", background: "none", padding: 0 }}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
        </div>
      </section>
    </div>
  );
}
