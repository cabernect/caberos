import type { ComponentType } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const tileVariants = cva("flex shrink-0 items-center justify-center rounded-md", {
  variants: {
    size: {
      sm: "h-7 w-7 [&_svg]:h-3.5 [&_svg]:w-3.5",
      md: "h-9 w-9 [&_svg]:h-4.5 [&_svg]:w-4.5",
      lg: "h-11 w-11 [&_svg]:h-5.5 [&_svg]:w-5.5",
    },
    tone: {
      sunken: "bg-sunken text-ink-muted",
      accent: "bg-accent-tint text-accent",
      warning: "bg-warning-tint text-warning",
      danger: "bg-danger-tint text-danger",
      surface: "border border-line bg-surface text-ink-muted",
    },
  },
  defaultVariants: { size: "md", tone: "sunken" },
});

/** Rounded square holding a lucide icon — entity avatar / integration icon. */
export function IconTile({
  icon: Icon,
  size,
  tone,
  className,
}: {
  icon: ComponentType<{ className?: string }>;
  className?: string;
} & VariantProps<typeof tileVariants>) {
  return (
    <div className={cn(tileVariants({ size, tone }), className)}>
      <Icon />
    </div>
  );
}
