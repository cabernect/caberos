import { useState, useEffect, useRef } from "react";
import { Markdown } from "./Markdown";

interface ThinkingBlockProps {
  content: string;
  isStreaming: boolean;
  durationSec?: number;
}

export function ThinkingBlock({
  content,
  isStreaming,
  durationSec,
}: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isStreaming) {
      setExpanded(true);
    } else {
      setExpanded(false);
    }
  }, [isStreaming]);

  useEffect(() => {
    if (expanded && isStreaming && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [content, expanded, isStreaming]);

  if (!content && !isStreaming) return null;

  return (
    <div className="mb-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 bg-none p-0"
        style={{ border: "none", cursor: "pointer" }}
      >
        <span
          className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${isStreaming ? "pulse" : ""}`}
          style={{ background: "#FBBF24" }}
        />
        <span className="font-mono text-[11px] text-[var(--ink-2)] transition group-hover:text-[var(--ink)]">
          {isStreaming
            ? "thinking…"
            : `thinking${durationSec ? ` · ${durationSec}s` : ""}`}
        </span>
        <span className="font-mono text-[11px] text-[var(--ink-3)]">
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {expanded && (
        <div
          ref={contentRef}
          className="mb-3 mt-2 max-h-48 overflow-y-auto rounded-[5px] border p-2 px-3 py-2 text-[13px] italic leading-[1.6]"
          style={{
            borderColor: "#FDE68A",
            background: "var(--thinking-bg)",
            color: "var(--ink-2)",
          }}
        >
          <div className="markdown-body">
            <Markdown>{content}</Markdown>
          </div>
          {isStreaming && <span className="streaming-cursor" />}
        </div>
      )}
    </div>
  );
}
