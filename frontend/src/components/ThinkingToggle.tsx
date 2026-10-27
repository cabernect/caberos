import { Brain } from "lucide-react";
import { Select } from "@/components/ui/select";

/** Thinking toggle + effort selector — shown when the selected model supports reasoning.
 *
 *  "Think" pill (accent-tint when on) + a compact effort dropdown —
 *  models can expose 6+ efforts, so a segmented control wraps the row.
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
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => onToggle(!isOn)}
        className={`flex cursor-pointer items-center gap-1.5 rounded-[8px] border px-2.5 py-1.5 text-[12px] font-medium transition-colors ${
          isOn
            ? "border-accent/40 bg-accent-tint text-accent"
            : "border-line bg-surface text-ink-muted hover:text-ink"
        }`}
        title={isOn ? "Thinking enabled — click to disable" : "Enable thinking/reasoning"}
      >
        <Brain className="h-3.5 w-3.5" />
        <span>Think</span>
      </button>
      {isOn && efforts.length > 0 && (
        <Select
          value={effort}
          onChange={onEffortChange}
          options={efforts.map((e) => ({ value: e, label: e }))}
          className="cursor-pointer rounded-[8px] border border-line bg-surface py-1.5 pl-2 pr-1.5 text-[12px] font-medium text-ink-muted outline-none transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
          title="Thinking effort"
          ariaLabel="Thinking effort"
        />
      )}
    </div>
  );
}
