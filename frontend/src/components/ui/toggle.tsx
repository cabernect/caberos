import type { ButtonHTMLAttributes } from "react";

type ToggleProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onChange" | "value"> & {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  size?: "sm" | "md";
};

const SIZES = {
  sm: {
    track: "h-4 w-7",
    thumb: "h-3 w-3",
    on: "translate-x-[14px]",
    off: "translate-x-[2px]",
  },
  md: {
    track: "h-5 w-9",
    thumb: "h-4 w-4",
    on: "translate-x-[18px]",
    off: "translate-x-[2px]",
  },
} as const;

export function Toggle({ checked, onCheckedChange, size = "md", className = "", disabled, ...rest }: ToggleProps) {
  const s = SIZES[size];
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onCheckedChange(!checked);
      }}
      className={`relative inline-flex shrink-0 cursor-pointer items-center rounded-full transition disabled:cursor-wait disabled:opacity-60 ${s.track} ${checked ? "bg-accent" : "bg-track"} ${className}`}
      {...rest}
    >
      <span
        className={`inline-block rounded-full bg-white shadow transition-transform ${s.thumb} ${checked ? s.on : s.off}`}
      />
    </button>
  );
}
