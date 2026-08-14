import { Brain } from "lucide-react";

/** Thinking toggle + effort selector — shown when the selected model supports reasoning.
 *
 *  Used in two places:
 *  - ChatInputBar: per-message override (null = use agent default)
 *  - SettingsOverlay General tab: agent default thinking config
 */
export function ThinkingToggle({
  enabled,
  effort,
  efforts,
  onToggle,
  onEffortChange,
}: {
  enabled: boolean | null;
  effort: string;
  efforts: string[];
  onToggle: (enabled: boolean) => void;
  onEffortChange: (effort: string) => void;
}) {
  const isOn = enabled === true;

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => onToggle(!isOn)}
        className="flex items-center gap-1 rounded-[4px] border px-2 py-1 font-mono text-[11px] transition"
        style={{
          borderColor: isOn ? "var(--accent)" : "var(--border)",
          background: isOn ? "var(--surface)" : "transparent",
          color: isOn ? "var(--accent)" : "var(--ink-3)",
          cursor: "pointer",
        }}
        onMouseEnter={(e) => {
          if (!isOn) {
            e.currentTarget.style.borderColor = "var(--ink-3)";
            e.currentTarget.style.color = "var(--ink-2)";
          }
        }}
        onMouseLeave={(e) => {
          if (!isOn) {
            e.currentTarget.style.borderColor = "var(--border)";
            e.currentTarget.style.color = "var(--ink-3)";
          }
        }}
        title={isOn ? "Thinking enabled — click to disable" : "Enable thinking/reasoning"}
      >
        <Brain className="h-3 w-3" />
        <span>Think</span>
      </button>
      {isOn && efforts.length > 0 && (
        <select
          value={effort}
          onChange={(e) => onEffortChange(e.target.value)}
          className="rounded-[4px] border px-1.5 py-1 font-mono text-[11px] outline-none transition"
          style={{
            borderColor: "var(--border)",
            background: "var(--surface)",
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
          {efforts.map((e) => (
            <option key={e} value={e}>{e}</option>
          ))}
        </select>
      )}
    </div>
  );
}
