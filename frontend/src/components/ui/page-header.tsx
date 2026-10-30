import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Breadcrumb {
  label: string;
  onClick?: () => void;
}

/**
 * W13 page anatomy: breadcrumb trail → page title (30/36 semibold) →
 * right-aligned actions. Every page starts with this, then a filter row,
 * then content.
 */
export function PageHeader({
  breadcrumbs,
  title,
  subtitle,
  actions,
  trailing,
  className,
}: {
  breadcrumbs?: Breadcrumb[];
  title: ReactNode;
  /** Secondary line under the title — what this page is for. */
  subtitle?: ReactNode;
  actions?: ReactNode;
  /** Right-aligned element on the breadcrumb line (e.g. command bar). */
  trailing?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("sticky top-0 z-10 bg-ground px-8 pb-5 pt-7", className)}>
      {((breadcrumbs && breadcrumbs.length > 0) || trailing) && (
        <div className="mb-2 flex items-center justify-between gap-4">
          {breadcrumbs && breadcrumbs.length > 0 ? (
        <nav className="flex items-center gap-1.5 text-[13px] leading-[18px] text-ink-muted">
          {breadcrumbs.map((crumb, i) => (
            <span key={`${crumb.label}-${i}`} className="flex items-center gap-1.5">
              {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-ink-faint" />}
              {crumb.onClick ? (
                <button
                  type="button"
                  onClick={crumb.onClick}
                  className="cursor-pointer transition-colors hover:text-ink"
                >
                  {crumb.label}
                </button>
              ) : (
                <span>{crumb.label}</span>
              )}
            </span>
          ))}
        </nav>
          ) : (
            <span />
          )}
          {trailing && (
            <div className="flex h-[18px] w-[300px] shrink-0 items-center">
              {trailing}
            </div>
          )}
        </div>
      )}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[30px] font-semibold leading-9 text-ink">{title}</h1>
          {subtitle && (
            <p className="mt-1 text-[14px] leading-[20px] text-ink-muted">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2 pt-1">{actions}</div>}
      </div>
    </header>
  );
}
