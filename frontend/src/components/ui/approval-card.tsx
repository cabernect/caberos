import type { ReactNode } from "react";
import { ShieldAlert, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

/**
 * W13 approval card: warning-tone header, capability + detail in mono,
 * Approve/Deny split. `footer` carries extra controls (e.g. remember-scope).
 * Destructive detail (tone="danger") for risky calls.
 */
export function ApprovalCard({
  title,
  detail,
  tone = "warning",
  state = "pending",
  onApprove,
  onDeny,
  footer,
  className,
}: {
  /** e.g. "terminal wants to run a command" */
  title: ReactNode;
  /** the exact call — command, URL, or args. Rendered in mono. */
  detail?: ReactNode;
  tone?: "warning" | "danger";
  state?: "pending" | "approved" | "rejected";
  onApprove?: () => void;
  onDeny?: () => void;
  footer?: ReactNode;
  className?: string;
}) {
  const toneClasses =
    tone === "danger"
      ? "border-danger/40 bg-danger-tint text-danger"
      : "border-warning/40 bg-warning-tint text-warning";
  return (
    <div className={cn("overflow-hidden rounded-md border border-line bg-surface", className)}>
      <div className={cn("flex items-center gap-2 border-b px-4 py-2.5 text-[13px] font-medium leading-[18px]", toneClasses)}>
        <ShieldAlert className="h-4 w-4 shrink-0" />
        {title}
      </div>
      {detail && (
        <div className="max-h-40 overflow-y-auto px-4 py-3 font-mono text-[13px] leading-[18px] text-ink">
          {detail}
        </div>
      )}
      <div className="flex items-center gap-2 px-4 py-3">
        {state === "pending" && (
          <>
            <Button size="sm" onClick={onApprove}>
              <Check className="h-3.5 w-3.5" /> Approve
            </Button>
            <Button size="sm" variant="outline" onClick={onDeny}>
              <X className="h-3.5 w-3.5" /> Deny
            </Button>
          </>
        )}
        {state === "approved" && <span className="text-[13px] text-success">Approved</span>}
        {state === "rejected" && <span className="text-[13px] text-danger">Denied</span>}
        {footer && <div className="ml-auto">{footer}</div>}
      </div>
    </div>
  );
}
