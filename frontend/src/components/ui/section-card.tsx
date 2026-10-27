import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Section container: 18/26 semibold title + optional trailing action,
 * then content. The content area takes ListRow children or a custom body.
 */
export function SectionCard({
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  title: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("rounded-md border border-line bg-surface", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <h2 className="text-[16px] font-semibold leading-6 text-ink">{title}</h2>
        {action}
      </div>
      <div className={cn("px-4 py-3", bodyClassName)}>{children}</div>
    </section>
  );
}
