import type { ReactNode } from "react";
import { LogoMark } from "./LogoMark";

export function VersionFooter() {
  return (
    <p className="pointer-events-none absolute inset-x-0 bottom-8 text-center text-[12px] text-[var(--ink-3)]">
      v{__APP_VERSION__} · Everything runs on this machine
    </p>
  );
}

/** Bare spiral mark — the logo itself spins as the loading indicator while
 * the engine starts. `failed` freezes it and shifts to warning; `spinning={false}`
 * plays a short wind-down so it reads as landing, not snapping. */
export function OrbitMark({ failed, spinning = true }: { failed?: boolean; spinning?: boolean }) {
  return (
    <LogoMark
      className={`h-14 w-14 ${spinning ? "animate-spin" : "logo-land"}`}
      color={failed ? "var(--warning)" : "var(--brand)"}
      style={
        spinning
          ? {
              animationDuration: "2.5s",
              animationPlayState: failed ? "paused" : "running",
            }
          : undefined
      }
    />
  );
}

/** Shared boot/login frame: centered logo + content. Children should use
 * `.rise-in` for the float-up entrance. */
export function BootShell({
  failed,
  spinning = true,
  children,
}: {
  failed?: boolean;
  spinning?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-ground px-6">
      <OrbitMark failed={failed} spinning={spinning} />
      {children}
      <VersionFooter />
    </div>
  );
}
