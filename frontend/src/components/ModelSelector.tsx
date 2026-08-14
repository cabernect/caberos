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
}

const modelCache = new Map<string, ModelInfo[]>();

export function ModelSelector({
  defaultProviderId,
  defaultModelName,
  onChange,
}: ModelSelectorProps) {
  const [providers, setProviders] = useState<ProviderModels[]>([]);
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<string>(
    defaultProviderId && defaultModelName
      ? `${defaultProviderId}/${defaultModelName}`
      : "",
  );

  useEffect(() => {
    let cancelled = false;

    api.listProviders().then((provs) => {
      if (cancelled) return;

      // Render providers immediately. Each model list arrives independently so
      // one slow or unavailable provider cannot block the whole selector.
      setProviders(
        provs.map((provider) => ({
          provider,
          models: modelCache.get(provider.id) || [],
        })),
      );

      for (const provider of provs) {
        if (modelCache.has(provider.id)) continue;

        api.listModels(provider.id).then((resp) => {
          if (cancelled) return;
          modelCache.set(provider.id, resp.models);
          setProviders((current) =>
            current.map((entry) =>
              entry.provider.id === provider.id
                ? { ...entry, models: resp.models }
                : entry,
            ),
          );
        }).catch(() => {
          // Keep the provider visible even when its discovery endpoint fails.
        });
      }
    }).catch(() => {
      if (!cancelled) setProviders([]);
    });

    return () => { cancelled = true; };
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
    // Look up the default model's capabilities from the providers list
    // so thinking/vision toggles work with the default model too
    const defaultModel = lookupDefaultModel();
    onChange(defaultModel);
  };

  // Find the default model's metadata (capabilities) from loaded providers
  const lookupDefaultModel = (): SelectedModel | null => {
    if (!defaultProviderId || !defaultModelName) return null;
    const pm = providers.find((p) => p.provider.id === defaultProviderId);
    if (!pm) return null;
    const model = pm.models.find((m) => m.name === defaultModelName);
    if (!model) return null;
    return {
      provider_id: defaultProviderId,
      name: defaultModelName,
      supports_vision: model.supports_vision,
      supports_thinking: model.supports_thinking,
      thinking_efforts: model.thinking_efforts,
    };
  };

  // When providers load and no model is explicitly selected (using default),
  // emit the default model's capabilities so thinking/vision toggles work
  useEffect(() => {
    if (providers.length === 0) return;
    if (!selected && defaultProviderId && defaultModelName) {
      const defaultModel = lookupDefaultModel();
      if (defaultModel) onChange(defaultModel);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers, defaultProviderId, defaultModelName]);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 0);
    } else {
      setSearch("");
    }
  }, [open]);

  // Filter models by search query (case-insensitive, matches model name or provider name)
  const searchLower = search.toLowerCase();
  const filteredProviders = search
    ? providers
        .map(({ provider, models }) => ({
          provider,
          models: models.filter(
            (m) =>
              m.name.toLowerCase().includes(searchLower) ||
              provider.name.toLowerCase().includes(searchLower),
          ),
        }))
        .filter(({ models }) => models.length > 0)
    : providers;

  const isDefault =
    !selected || (defaultProviderId && defaultModelName && selected === `${defaultProviderId}/${defaultModelName}`);
  const defaultProviderName = providers.find((p) => p.provider.id === defaultProviderId)?.provider.name;
  const selectedLabel = isDefault
    ? defaultModelName
      ? `${defaultModelName} · ${defaultProviderName || defaultProviderId?.slice(0, 8)} (default)`
      : "Select a model…"
    : formatModelLabel(selected, providers);

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setOpen(!open)}
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
        <span className="max-w-[200px] truncate" title={selectedLabel}>{selectedLabel}</span>
        <span
          className="text-[10px] opacity-60"
          style={{ transform: open ? "rotate(180deg)" : "none" }}
        >
          ▾
        </span>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          <div
            className="absolute bottom-full left-0 z-50 mb-1 max-h-80 min-w-[240px] overflow-y-auto rounded-md border p-1 shadow-lg"
            style={{
              borderColor: "var(--border)",
              background: "var(--white)",
              boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
            }}
          >
            {/* Search input */}
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

            {/* Current model — highlighted at top so user always sees what's active */}
            {!search && selected && !isDefault && (
              <div
                className="mb-1 flex items-center gap-2 rounded-[4px] px-3 py-1.5 font-mono text-[12px]"
                style={{ background: "var(--surface)", color: "var(--accent)" }}
              >
                <span className="text-[10px] font-bold uppercase" style={{ color: "var(--accent)" }}>
                  Current
                </span>
                <span className="truncate" title={selectedLabel}>{selectedLabel}</span>
              </div>
            )}

            {/* Default option */}
            <button
              onClick={handleUseDefault}
              className={cn(
                "flex w-full items-center justify-between px-3 py-1.5 text-left font-mono text-[12px] transition",
              )}
              style={{
                color:
                  !selected || selected === `${defaultProviderId}/${defaultModelName}`
                    ? "var(--accent)"
                    : "var(--ink)",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "var(--surface)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "none")
              }
            >
              <span style={{ color: "var(--ink-2)" }}>Agent default</span>
              {defaultModelName && (
                <span style={{ color: "var(--ink-3)" }}>
                  {defaultModelName} · {defaultProviderName || defaultProviderId?.slice(0, 8)}
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
                </div>
                {models.map((model) => {
                  const key = `${provider.id}/${model.id}`;
                  return (
                    <button
                      key={key}
                      onClick={() => handleSelect(
                        provider.id, model.id,
                        !!model.supports_vision,
                        !!model.supports_thinking,
                        model.thinking_efforts || [],
                      )}
                      className="flex w-full items-center gap-1 px-3 py-1.5 text-left font-mono text-[12px] transition"
                      style={{
                        color:
                          selected === key ? "var(--accent)" : "var(--ink)",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background = "var(--surface)")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = "none")
                      }
                    >
                      <span className="flex-1 truncate">{model.name}</span>
                      {model.supports_thinking && (
                        <Brain
                          className="ml-1 h-3.5 w-3.5 shrink-0"
                          style={{ color: "var(--ink-3)" }}
                          title="Supports thinking/reasoning"
                        />
                      )}
                      {model.supports_vision && (
                        <Eye
                          className="ml-1 h-3.5 w-3.5 shrink-0"
                          style={{ color: "var(--ink-3)" }}
                          title="Supports vision/image input"
                        />
                      )}
                      {model.max_context_tokens && (
                        <span
                          className="ml-1 shrink-0 font-mono text-[10px]"
                          style={{ color: "var(--ink-4)" }}
                          title={`Context: ${(model.max_context_tokens / 1024).toFixed(0)}K tokens${model.max_output_tokens ? ` · Output: ${(model.max_output_tokens / 1024).toFixed(0)}K` : ""}`}
                        >
                          {(model.max_context_tokens / 1024).toFixed(0)}K
                        </span>
                      )}
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
