import { useState, useEffect, useRef } from "react";
import { ChevronRight, ChevronDown, Brain } from "lucide-react";

interface ThinkingBlockProps {
  content: string;
  isStreaming: boolean;
  durationSec?: number;
}

export function ThinkingBlock({ content, isStreaming, durationSec }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(true);
  const contentRef = useRef<HTMLDivElement>(null);

  // Auto-expand during streaming, auto-collapse when done
  useEffect(() => {
    if (isStreaming) {
      setExpanded(true);
    } else {
      setExpanded(false);
    }
  }, [isStreaming]);

  // Auto-scroll to bottom while streaming
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
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <Brain className="h-3 w-3" />
        <span>
          {isStreaming ? "thinking..." : `thinking${durationSec ? ` · ${durationSec}s` : ""}`}
        </span>
      </button>

      {expanded && (
        <div
          ref={contentRef}
          className="mt-1 max-h-48 overflow-y-auto pl-6"
        >
          <p className="font-mono text-xs italic text-muted-foreground whitespace-pre-wrap">
            {content}
            {isStreaming && <span className="streaming-cursor" />}
          </p>
        </div>
      )}
    </div>
  );
}
