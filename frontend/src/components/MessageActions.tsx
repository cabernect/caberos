import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

export function MessageActions({ content }: { content: string }) {
  const [status, setStatus] = useState<"idle" | "copying" | "copied" | "error">("idle");
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
  }, []);

  if (!content.trim()) return null;

  const copyMessage = async () => {
    if (resetTimer.current) clearTimeout(resetTimer.current);
    setStatus("copying");
    try {
      await navigator.clipboard.writeText(content);
      setStatus("copied");
      resetTimer.current = setTimeout(() => setStatus("idle"), 2000);
    } catch {
      setStatus("error");
    }
  };

  const label = status === "copied" ? "Copied" : "Copy message";
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={copyMessage}
        disabled={status === "copying"}
        aria-label={label}
        title={label}
        className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-md text-[var(--ink-3)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--ink)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-wait"
      >
        {status === "copied" ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      <span role="status" className={status === "error" ? "text-[12px] text-[var(--ink-2)]" : "sr-only"}>
        {status === "copied" ? "Message copied" : status === "error" ? "Couldn't copy. Try again or select the text manually." : ""}
      </span>
    </div>
  );
}
