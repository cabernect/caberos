import type { ComponentType, CSSProperties, ReactNode } from "react";
import { ChevronRight } from "lucide-react";

interface Breadcrumb {
  label: string;
  onClick?: () => void;
}

interface PageHeaderProps {
  icon: ComponentType<{ className?: string; style?: CSSProperties }>;
  title: string;
  titleOnClick?: () => void;
  description?: string;
  breadcrumbs?: Breadcrumb[];
  children?: ReactNode;
}

export function PageHeader({ icon: Icon, title, titleOnClick, description, breadcrumbs, children }: PageHeaderProps) {
  return (
    <header
      className="px-8 py-5"
      style={{ background: "var(--sidebar)", borderBottom: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-5 w-5 shrink-0" style={{ color: "var(--accent)" }} />
        {titleOnClick ? (
          <button
            type="button"
            onClick={titleOnClick}
            className="cursor-pointer text-[18px] font-semibold text-[var(--ink)] hover:opacity-75"
          >
            {title}
          </button>
        ) : (
          <h1 className="text-[18px] font-semibold text-[var(--ink)]">{title}</h1>
        )}
        {breadcrumbs?.map((breadcrumb, index) => (
          <span key={`${breadcrumb.label}-${index}`} className="contents">
            <ChevronRight className="h-4 w-4 shrink-0 text-[var(--ink-3)]" />
            {breadcrumb.onClick ? (
              <button
                type="button"
                onClick={breadcrumb.onClick}
                className="cursor-pointer text-[15px] text-[var(--ink-2)] hover:text-[var(--ink)]"
              >
                {breadcrumb.label}
              </button>
            ) : (
              <span className="text-[15px] text-[var(--ink-2)]">{breadcrumb.label}</span>
            )}
          </span>
        ))}
        {children}
      </div>
      {description && <p className="mt-0.5 pl-7 text-[13px] text-[var(--ink-2)]">{description}</p>}
    </header>
  );
}
