import { useEffect, useState, useRef } from "react";
import { Search, Eye, Brain } from "lucide-react";
import { api } from "@/lib/api";
import type { Provider, ModelInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

interface SelectedModel {
  provider_id: string;
  name: string;
  supports_vision?: boolean;
  supports_thinking?: boolean;
  thinking_efforts?: string[];
}

interface ModelSelectorProps {
  defaultProviderId: string | null;
  defaultModelName: string | null;
  onChange: (model: SelectedModel | null) => void;
}

interface ProviderModels {
  provider: Provider;
  models: ModelInfo[];
  listRevision?: string;
}

interface LoadState {
  generation: number;
  mounted: boolean;
}

export function ModelSelector({
  defaultProviderId,
  defaultModelName,
  onChange,
}: ModelSelectorProps) {
  const [providers, setProviders] = useState<ProviderModels[]>([]);
  const [loadErrors, setLoadErrors] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<string>(
    defaultProviderId && defaultModelName
      ? `${defaultProviderId}/${defaultModelName}`
      : "",
  );

  // Per-instance request generation — two mounted selectors never
  // invalidate each other, and an out-of-order provider list or model
  // response can never reset newer state.
  const loadState = useRef<LoadState>({ generation: 0, mounted: true });

  const refreshProviders = () => {
    const gen = ++loadState.current.generation;
    api
      .listProviders()
      .then((provs) => {
        if (!loadState.current.mounted || gen !== loadState.current.generation)
          return;
        setProviders((current) =>
          provs.map((provider) => {
            const existing = current.find(
              (e) => e.provider.id === provider.id,
            );
            // Keep last-known models during the fresh GET — a slow or
            // failed refresh shows the stale list, not an empty one.
            return { provider, models: existing?.models ?? [], listRevision: existing?.listRevision };
          }),
        );
        for (const provider of provs) {
          api
            .listModels(provider.id)
            .then((resp) => {
              if (
                !loadState.current.mounted ||
                gen !== loadState.current.generation
              )
                return;
              setLoadErrors((prev) => {
                const next = new Set(prev);
                next.delete(provider.id);
                return next;
              });
              setProviders((current) =>
                current.map((entry) =>
                  entry.provider.id === provider.id
                    ? {
                        ...entry,
                        models: resp.models,
                        listRevision: resp.revision,
                      }
                    : entry,
                ),
              );
            })
            .catch(() => {
              if (
                !loadState.current.mounted ||
                gen !== loadState.current.generation
              )
                return;
              // Retain last-known metadata; flag the provider as stale
              // rather than dropping its entries.
              setLoadErrors((prev) => new Set(prev).add(provider.id));
            });
        }
      })
      .catch(() => {
        if (loadState.current.mounted && gen === loadState.current.generation) {
          setProviders([]);
          setLoadErrors(new Set());
        }
      });
  };

  // Local GET on mount — the backend never probes upstream here.
  useEffect(() => {
    loadState.current.mounted = true;
    refreshProviders();
    return () => {
      loadState.current.mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSelect = (
    providerId: string,
    modelName: string,
    supportsVision: boolean,
    supportsThinking: boolean,
    thinkingEfforts: string[],
  ) => {
    setSelected(`${providerId}/${modelName}`);
    setOpen(false);
    setSearch("");
    onChange({
      provider_id: providerId,
      name: modelName,
      supports_vision: supportsVision,
      supports_thinking: supportsThinking,
      thinking_efforts: thinkingEfforts,
    });
  };

  const handleUseDefault = () => {
    setSelected(
      defaultProviderId && defaultModelName
        ? `${defaultProviderId}/${defaultModelName}`
        : "",
    );
    setOpen(false);
    setSearch("");
    const defaultModel = lookupDefaultModel();
    onChange(defaultModel);
  };

  const lookupDefaultModel = (): SelectedModel | null => {
    if (!defaultProviderId || !defaultModelName) return null;
    const pm = providers.find((p) => p.provider.id === defaultProviderId);
    if (!pm) return null;
    const model = pm.models.find((m) => m.id === defaultModelName);
    if (!model) return null;
    return {
      provider_id: defaultProviderId,
      name: model.id,
      supports_vision: model.supports_vision,
      supports_thinking: model.supports_thinking,
      thinking_efforts: model.thinking_efforts,
    };
  };

  // Emit the default model's capabilities so thinking/vision toggles
  // work. The emitted key includes the metadata revision so a catalog
  // refresh emits exactly once for the *changed* capability set — not a
  // re-render loop on every list refresh.
  const emittedDefaultKey = useRef<string | null>(null);
  useEffect(() => {
    if (providers.length === 0) return;
    if (!defaultProviderId || !defaultModelName) return;

    const defaultKey = `${defaultProviderId}/${defaultModelName}`;
    const isCurrentlyDefault = !selected || selected === defaultKey;
    if (!isCurrentlyDefault) return;

    const pm = providers.find((p) => p.provider.id === defaultProviderId);
    const model = pm?.models.find((m) => m.id === defaultModelName);
    if (!model) return;
    // Emit once per actual capability change: same row revision but a
    // flipped flag (or a legacy backend without revisions) still re-emits.
    const signature = JSON.stringify([
      model.supports_vision ?? null,
      model.supports_thinking ?? null,
      model.thinking_efforts ?? [],
    ]);
    const key = `${defaultKey}/${pm?.listRevision ?? ""}:${model.revision ?? ""}:${model.snapshot_revision ?? ""}:${signature}`;
    if (emittedDefaultKey.current === key) return;
    emittedDefaultKey.current = key;
    setSelected(defaultKey);
    onChange(lookupDefaultModel());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers, defaultProviderId, defaultModelName, selected]);

  // Refetch on every open — the listing is local so this stays cheap.
  const toggleOpen = () => {
    const next = !open;
    setOpen(next);
    if (next) refreshProviders();
  };

  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 0);
    } else {
      setSearch("");
    }
  }, [open]);

  const searchLower = search.toLowerCase();
  const filteredProviders = search
    ? providers
        .map(({ provider, models }) => ({
          provider,
          models: models.filter(
            (m) =>
              m.id.toLowerCase().includes(searchLower) ||
              (m.display_name ?? "").toLowerCase().includes(searchLower) ||
              provider.name.toLowerCase().includes(searchLower),
          ),
        }))
        .filter(({ models }) => models.length > 0)
    : providers;

  const isDefault =
    !selected ||
    (defaultProviderId &&
      defaultModelName &&
      selected === `${defaultProviderId}/${defaultModelName}`);
  const defaultProviderName = providers.find(
    (p) => p.provider.id === defaultProviderId,
  )?.provider.name;
  const selectedLabel = isDefault
    ? defaultModelName
      ? `${defaultModelName} · ${defaultProviderName || defaultProviderId?.slice(0, 8)} (default)`
      : "Select a model…"
    : formatModelLabel(selected, providers);

  const availabilityNote = (model: ModelInfo): string | null => {
    const parts: string[] = [];
    if (model.availability === "unavailable") parts.push("unavailable");
    else if (model.availability === "unknown") parts.push("unknown");
    if (model.stale) parts.push("stale");
    return parts.length ? ` · ${parts.join(" · ")}` : null;
  };

  // Per-field source + confidence labels — distinct for each limit, no
  // "unsupported" claim on unknown.
  const fmt = (v: number) =>
    v >= 1000 ? `${Math.round(v / 1000)}K` : String(v);
  const fieldTip = (
    label: string,
    value: number | null | undefined,
    source?: string,
    confidence?: string,
  ): string => {
    const shown =
      value != null ? `${value.toLocaleString()} tokens` : "Unknown";
    const src = source ?? "unknown";
    const conf = confidence ?? "unknown";
    return `${label}: ${shown} — ${src} (${conf})`;
  };
  const limitsTitle = (model: ModelInfo): string => {
    const prov = model.provenance ?? {};
    return [
      fieldTip(
        "Input limit",
        model.max_context_tokens,
        prov["max_context_tokens"]?.source,
        prov["max_context_tokens"]?.confidence,
      ),
      fieldTip(
        "Total context",
        model.context_window_tokens,
        prov["context_window_tokens"]?.source,
        prov["context_window_tokens"]?.confidence,
      ),
      fieldTip(
        "Output limit",
        model.max_output_tokens,
        prov["max_output_tokens"]?.source,
        prov["max_output_tokens"]?.confidence,
      ),
    ].join("\n");
  };

  return (
    <div className="relative shrink-0">
      <button
        onClick={toggleOpen}
        className="flex items-center gap-1 rounded-[5px] border px-2 py-1.5 font-mono text-[12px] whitespace-nowrap transition"
        style={{
          borderColor: "var(--border)",
          background: "none",
          color: "var(--ink-2)",
          cursor: "pointer",
        }}
        onMouseEnter={(e) =>
          (e.currentTarget.style.borderColor = "var(--ink-3)")
        }
        onMouseLeave={(e) =>
          (e.currentTarget.style.borderColor = "var(--border)")
        }
      >
        <span className="max-w-[200px] truncate" title={selectedLabel}>
          {selectedLabel}
        </span>
        <span
          className="text-[10px] opacity-60"
          style={{ transform: open ? "rotate(180deg)" : "none" }}
        >
          ▾
        </span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="absolute bottom-full left-0 z-50 mb-1 max-h-80 min-w-[240px] overflow-y-auto rounded-md border p-1 shadow-lg"
            style={{
              borderColor: "var(--border)",
              background: "var(--white)",
              boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
            }}
          >
            <div className="relative mb-1">
              <Search
                className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2"
                style={{ color: "var(--ink-3)" }}
              />
              <input
                ref={searchRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search models…"
                className="w-full rounded-[4px] border py-1.5 pl-7 pr-2 font-mono text-[12px] outline-none"
                style={{
                  borderColor: "var(--border)",
                  background: "var(--surface)",
                  color: "var(--ink)",
                }}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setOpen(false);
                  e.stopPropagation();
                }}
              />
            </div>

            {!search && selected && !isDefault && (
              <div
                className="mb-1 flex items-center gap-2 rounded-[4px] px-3 py-1.5 font-mono text-[12px]"
                style={{ background: "var(--surface)", color: "var(--accent)" }}
              >
                <span
                  className="text-[10px] font-bold uppercase"
                  style={{ color: "var(--accent)" }}
                >
                  Current
                </span>
                <span className="truncate" title={selectedLabel}>
                  {selectedLabel}
                </span>
              </div>
            )}

            <button
              onClick={handleUseDefault}
              className={cn(
                "flex w-full items-center justify-between px-3 py-1.5 text-left font-mono text-[12px] transition",
              )}
              style={{
                color:
                  !selected ||
                  selected === `${defaultProviderId}/${defaultModelName}`
                    ? "var(--accent)"
                    : "var(--ink)",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "var(--surface)")
              }
              onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
            >
              <span style={{ color: "var(--ink-2)" }}>Agent default</span>
              {defaultModelName && (
                <span style={{ color: "var(--ink-3)" }}>
                  {defaultModelName} ·{" "}
                  {defaultProviderName || defaultProviderId?.slice(0, 8)}
                </span>
              )}
            </button>

            <div style={{ borderTop: "1px solid var(--border)" }} />

            {filteredProviders.length === 0 && (
              <div className="px-3 py-3 text-center font-mono text-[11px] text-[var(--ink-3)]">
                {search
                  ? `No models matching "${search}".`
                  : providers.length === 0
                    ? "No providers configured. Add one in Settings."
                    : "No models available."}
              </div>
            )}

            {filteredProviders.map(({ provider, models }) => (
              <div key={provider.id}>
                <div
                  className="px-3 py-1.5 font-mono text-[11px] text-[var(--ink-3)]"
                  style={{ background: "var(--surface)" }}
                >
                  {provider.name}
                  {loadErrors.has(provider.id) && (
                    <span className="ml-1" title="Model list failed to load; showing last-known data">
                      · refresh failed
                    </span>
                  )}
                </div>
                {models.map((model) => {
                  const key = `${provider.id}/${model.id}`;
                  const note = availabilityNote(model);
                  const label = model.display_name || model.id;
                  return (
                    <button
                      key={key}
                      onClick={() =>
                        handleSelect(
                          provider.id,
                          model.id,
                          !!model.supports_vision,
                          !!model.supports_thinking,
                          model.thinking_efforts || [],
                        )
                      }
                      className="flex w-full items-center gap-1 px-3 py-1.5 text-left font-mono text-[12px] transition"
                      style={{
                        color: selected === key ? "var(--accent)" : "var(--ink)",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background = "var(--surface)")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = "none")
                      }
                    >
                      <span className="flex-1 truncate">
                        {label}
                        {label !== model.id && (
                          <span style={{ color: "var(--ink-3)" }}>
                            {" "}
                            · {model.id}
                          </span>
                        )}
                        {note && (
                          <span style={{ color: "var(--ink-3)" }}>{note}</span>
                        )}
                      </span>
                      {model.supports_thinking === true && (
                        <Brain
                          className="ml-1 h-3.5 w-3.5 shrink-0"
                          style={{ color: "var(--ink-3)" }}
                          aria-label="Supports thinking/reasoning"
                        />
                      )}
                      {model.supports_vision === true && (
                        <Eye
                          className="ml-1 h-3.5 w-3.5 shrink-0"
                          style={{ color: "var(--ink-3)" }}
                          aria-label="Supports vision/image input"
                        />
                      )}
                      <span
                        className="ml-1 shrink-0 font-mono text-[10px]"
                        style={{ color: "var(--ink-4)" }}
                        title={limitsTitle(model)}
                      >
                        {model.context_window_tokens != null
                          ? fmt(model.context_window_tokens)
                          : model.max_context_tokens != null
                            ? `in ${fmt(model.max_context_tokens)}`
                            : "?"}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function formatModelLabel(
  selected: string,
  providers: ProviderModels[],
): string {
  const slashIdx = selected.indexOf("/");
  const providerId = slashIdx >= 0 ? selected.slice(0, slashIdx) : selected;
  const modelName = slashIdx >= 0 ? selected.slice(slashIdx + 1) : "";
  const pm = providers.find((p) => p.provider.id === providerId);
  const providerName = pm?.provider.name || providerId.slice(0, 8);
  return `${modelName} · ${providerName}`;
}
