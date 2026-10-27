import type { ReactNode } from "react";
import { AlertTriangle, Info, XCircle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const TONES: Record<string, { icon: LucideIcon; classes: string }> = {
  warning: { icon: AlertTriangle, classes: "border-warning/30 bg-warning-tint text-warning" },
  danger: { icon: XCircle, classes: "border-danger/30 bg-danger-tint text-danger" },
  info: { icon: Info, classes: "border-line bg-accent-tint text-accent" },
};

/** Inline banner for needs-attention states — warning-tint, icon + words. */
export function WarningBanner({
  tone = "warning",
  title,
  children,
  action,
  className,
}: {
  tone?: "warning" | "danger" | "info";
  title?: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const t = TONES[tone];
  const Icon = t.icon;
  return (
    <div className={cn("flex items-start gap-3 rounded-md border px-4 py-3", t.classes, className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        {title && <div className="text-[14px] font-semibold leading-5">{title}</div>}
        <div className="text-[13px] leading-[18px] text-ink-muted">{children}</div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
