import { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

/**
 * Markdown renderer with copy-to-clipboard on code blocks.
 * Drop-in replacement for <ReactMarkdown remarkPlugins={[remarkGfm]}>...
 */
export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        pre: CodeBlock,
      }}
    >
      {children}
    </ReactMarkdown>
  );
}

function CodeBlock({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);

  // Extract raw text from the <code> child for clipboard
  const getText = useCallback(() => {
    if (typeof children === "string") return children;
    if (children && typeof children === "object" && "props" in children) {
      const props = (children as React.ReactElement).props as { children?: React.ReactNode };
      if (typeof props.children === "string") return props.children;
      if (Array.isArray(props.children)) {
        return props.children
          .map((c) => (typeof c === "string" ? c : ""))
          .join("");
      }
    }
    return "";
  }, [children]);

  const handleCopy = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      const text = getText();
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    },
    [getText],
  );

  return (
    <div className="group relative">
      <button
        onClick={handleCopy}
        className="absolute right-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded border border-[var(--border)] bg-[var(--white)] opacity-0 transition-opacity hover:bg-[var(--sidebar)] group-hover:opacity-100"
        title="Copy code"
        aria-label="Copy code"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-[var(--success)]" />
        ) : (
          <Copy className="h-3.5 w-3.5 text-[var(--ink-2)]" />
        )}
      </button>
      <pre>{children}</pre>
    </div>
  );
}
