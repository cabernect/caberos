import type { LucideIcon } from "lucide-react";
import { ArrowLeft, Check } from "lucide-react";

/** Shared pieces for the onboarding flow — left-stepper wizard panes and
 * centered stages. Visual language per docs/plans/v0.2/fe_example:
 * warm ground, white cards, olive icon tiles, ink-black primary buttons. */

export function IconTile({
  icon: Icon,
  size = 44,
}: {
  icon: LucideIcon;
  size?: number;
}) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-[12px]"
      style={{
        width: size,
        height: size,
        background: "var(--accent-bg)",
        color: "var(--accent)",
      }}
    >
      <Icon style={{ width: size * 0.42, height: size * 0.42 }} />
    </div>
  );
}

export function StepTitle({ children }: { children: React.ReactNode }) {
  return (
    <h1 className="mt-2 text-[28px] font-semibold leading-tight tracking-tight text-[var(--ink)]">
      {children}
    </h1>
  );
}

export function StepSub({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-2 max-w-[560px] text-[13px] leading-6 text-[var(--ink-2)]">
      {children}
    </p>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="flex items-center gap-2 rounded-lg px-5 py-2.5 text-[13px] font-medium text-white transition"
      style={{
        background: "var(--ink)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <Check className="h-4 w-4" />
      {children}
    </button>
  );
}

export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 rounded-lg border bg-white px-4 py-2.5 text-[13px] font-medium text-[var(--ink)] transition hover:bg-[var(--hover)]"
      style={{ borderColor: "var(--border)", cursor: "pointer" }}
    >
      <ArrowLeft className="h-4 w-4" /> Back
    </button>
  );
}

/** Tinted info callout — olive chip + message text. */
export function CalloutBox({
  icon: Icon,
  children,
  tone = "ok",
}: {
  icon: LucideIcon;
  children: React.ReactNode;
  tone?: "ok" | "warn";
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-xl p-4 text-[12.5px] leading-5"
      style={{
        background:
          tone === "warn" ? "var(--warning-bg, #F6EEDA)" : "var(--accent-bg)",
        color: "var(--ink)",
      }}
    >
      <Icon
        className="mt-0.5 h-4 w-4 shrink-0"
        style={{
          color: tone === "warn" ? "var(--warning)" : "var(--accent)",
        }}
      />
      <div>{children}</div>
    </div>
  );
}

/** Labeled text input row matching the design's form style. */
export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-[var(--ink-2)]">
        {label}
      </span>
      {children}
    </label>
  );
}

export const inputStyle: React.CSSProperties = {
  width: "100%",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--white)",
  padding: "10px 12px",
  fontSize: 13,
  color: "var(--ink)",
};

/** Segmented strength meter — 4 bars, filled in accent by score 0-4. */
export function StrengthMeter({ score, hint }: { score: number; hint: string }) {
  return (
    <div className="mt-2">
      <div className="flex gap-1.5">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-1.5 flex-1 rounded-full"
            style={{
              background:
                i < score ? "var(--accent)" : "var(--border)",
            }}
          />
        ))}
      </div>
      <p className="mt-1.5 text-[12px] text-[var(--ink-3)]">{hint}</p>
    </div>
  );
}
