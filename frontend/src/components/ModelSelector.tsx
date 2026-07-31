import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Provider, ModelInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ModelSelectorProps {
  defaultProviderId: string | null;
  defaultModelName: string | null;
  onChange: (model: { provider_id: string; name: string } | null) => void;
}

interface ProviderModels {
  provider: Provider;
  models: ModelInfo[];
}

export function ModelSelector({
  defaultProviderId,
  defaultModelName,
  onChange,
}: ModelSelectorProps) {
  const [providers, setProviders] = useState<ProviderModels[]>([]);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string>(
    defaultProviderId && defaultModelName
      ? `${defaultProviderId}/${defaultModelName}`
      : "",
  );

  useEffect(() => {
    api.listProviders().then(async (provs) => {
      const loaded: ProviderModels[] = [];
      for (const p of provs) {
        try {
          const resp = await api.listModels(p.id);
          loaded.push({ provider: p, models: resp.models });
        } catch {
          loaded.push({ provider: p, models: [] });
        }
      }
      setProviders(loaded);
    });
  }, []);

  const handleSelect = (providerId: string, modelName: string) => {
    setSelected(`${providerId}/${modelName}`);
    setOpen(false);
    onChange({ provider_id: providerId, name: modelName });
  };

  const handleUseDefault = () => {
    setSelected(
      defaultProviderId && defaultModelName
        ? `${defaultProviderId}/${defaultModelName}`
        : "",
    );
    setOpen(false);
    onChange(null);
  };

  const selectedLabel = selected
    ? formatModelLabel(selected, providers)
    : "Default model";

  return (
    <div className="relative shrink-0">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 rounded-[5px] border px-2 py-1.5 font-mono text-[12px] whitespace-nowrap transition"
        style={{
          borderColor: "var(--border)",
          background: "none",
          color: "var(--ink-2)",
        }}
        onMouseEnter={(e) =>
          (e.currentTarget.style.borderColor = "var(--ink-3)")
        }
        onMouseLeave={(e) =>
          (e.currentTarget.style.borderColor = "var(--border)")
        }
      >
        <span className="max-w-[200px] truncate">{selectedLabel}</span>
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
            className="absolute bottom-full left-0 z-50 mb-1 max-h-80 min-w-[200px] overflow-y-auto rounded-md border p-1 shadow-lg"
            style={{
              borderColor: "var(--border)",
              background: "var(--white)",
              boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
            }}
          >
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
                <span style={{ color: "var(--ink-3)" }}>{defaultModelName}</span>
              )}
            </button>

            <div style={{ borderTop: "1px solid var(--border)" }} />

            {providers.length === 0 && (
              <div className="px-3 py-3 text-center font-mono text-[11px] text-[var(--ink-3)]">
                No providers configured.
                <br />
                Add one in Settings.
              </div>
            )}

            {providers.map(({ provider, models }) => (
              <div key={provider.id}>
                <div
                  className="px-3 py-1.5 font-mono text-[11px] text-[var(--ink-3)]"
                  style={{ background: "var(--surface)" }}
                >
                  {provider.name} ({provider.type})
                </div>
                {models.length === 0 ? (
                  <div className="px-3 py-1.5 font-mono text-[11px] italic text-[var(--ink-3)]">
                    No models discovered — type model name manually
                  </div>
                ) : (
                  models.map((model) => {
                    const key = `${provider.id}/${model.id}`;
                    return (
                      <button
                        key={key}
                        onClick={() => handleSelect(provider.id, model.id)}
                        className="flex w-full items-center px-3 py-1.5 text-left font-mono text-[12px] transition"
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
                        {model.name}
                      </button>
                    );
                  })
                )}
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
  const [providerId, modelName] = selected.split("/");
  const pm = providers.find((p) => p.provider.id === providerId);
  const providerName = pm?.provider.name || providerId.slice(0, 8);
  return `${modelName} · ${providerName}`;
}
