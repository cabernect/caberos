import { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { Check, Copy } from "lucide-react";
import { normalizeMathDelims } from "@/lib/mathDelims";
import "katex/dist/katex.min.css";

/**
 * Markdown renderer with copy-to-clipboard on code blocks.
 * Drop-in replacement for <ReactMarkdown remarkPlugins={[remarkGfm]}>...
 *
 * onWorkspaceLink: models often write workspace-relative paths as markdown
 * links ([file](artifacts/x.png)) — those hrefs are dead in a browser. When
 * provided, such links render as in-app openers instead of navigating.
 */
export function Markdown({
  children,
  onWorkspaceLink,
}: {
  children: string;
  onWorkspaceLink?: (path: string) => void;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        pre: CodeBlock,
        a: (props) => <WorkspaceAwareLink {...props} onWorkspaceLink={onWorkspaceLink} />,
      }}
    >
      {normalizeMathDelims(children)}
    </ReactMarkdown>
  );
}

function WorkspaceAwareLink({
  href,
  children,
  onWorkspaceLink,
}: {
  href?: string;
  children?: React.ReactNode;
  onWorkspaceLink?: (path: string) => void;
}) {
  const isWorkspacePath =
    !!href && !/^[a-z][a-z0-9+.-]*:/i.test(href) && !href.startsWith("#") && !href.startsWith("/");
  if (isWorkspacePath && onWorkspaceLink) {
    return (
      <a
        href={href}
        title={`Open ${href} in workspace`}
        onClick={(e) => {
          e.preventDefault();
          onWorkspaceLink(href!);
        }}
      >
        {children}
      </a>
    );
  }
  return <a href={href}>{children}</a>;
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
      {/* sticky so the button tracks the scrollport top for tall blocks
          (an absolute top-2 button scrolls out of view inside overflow panes) */}
      <div className="pointer-events-none sticky top-0 z-10 -mb-8 flex h-8 justify-end pr-2 pt-2">
        <button
          onClick={handleCopy}
          className="pointer-events-auto flex h-6 w-6 items-center justify-center rounded border border-[var(--border)] bg-[var(--white)] opacity-0 transition-opacity hover:bg-[var(--sidebar)] group-hover:opacity-100"
          title="Copy code"
          aria-label="Copy code"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-[var(--success)]" />
          ) : (
            <Copy className="h-3.5 w-3.5 text-[var(--ink-2)]" />
          )}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}
