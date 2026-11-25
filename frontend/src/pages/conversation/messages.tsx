import { workspaceBackend, type PreviewSource } from "@/lib/api";
import type { Message } from "@/lib/types";
import { useObjectUrl } from "@/components/previews/useObjectUrl";
import { AttachmentCard } from "@/components/AttachmentCard";
import {
  ToolCallBlock,
  FileChips,
  collectFileRefs,
  type ToolCallData,
  type SubAgentStreamData,
  type FileRef,
} from "@/components/ToolCallBlock";
import { Markdown } from "@/components/Markdown";
import { MessageActions } from "@/components/MessageActions";
import { ThinkingBlock } from "@/components/ThinkingBlock";
import { BookOpen, ChevronDown } from "lucide-react";
import type {
  ChatMessage,
  StreamingResponse,
  ThinkingBlockData,
} from "./types";

export function StreamingMessage({
  streaming,
  onPreview,
  agentId,
  sessionId,
}: {
  streaming: StreamingResponse;
  onPreview?: (source: PreviewSource) => void;
  agentId?: string;
  sessionId?: string | null;
}) {
  const hasContent = streaming.text || streaming.items.length > 0;
  const endTime = streaming.thinkingEndTime ?? Date.now();
  const currentThinkingDuration = streaming.thinkingStartTime
    ? Math.round((endTime - streaming.thinkingStartTime) / 1000)
    : undefined;
  const isThinkingStreaming = !!streaming.thinking && !streaming.text && !streaming.completed;
  const fileRefs = collectFileRefs(
    streaming.items
      .filter((i) => i.type === "tool")
      .map((i) => i.data as ToolCallData)
  );

  return (
    <div className="mb-6">
      {/* Render items in order: thinking blocks and tool calls interleaved */}
      {streaming.items.map((item) => {
        if (item.type === "thinking") {
          return (
            <ThinkingBlock
              key={item.id}
              content={item.data.content}
              isStreaming={false}
              durationSec={item.data.durationSec ?? undefined}
            />
          );
        }
        if (item.type === "text") {
          return (
            <div key={item.id} className="markdown-body text-[14px] leading-[1.65] text-[var(--ink)]">
              <Markdown onWorkspaceLink={(p) => onPreview?.({ path: p })}>{item.data.content}</Markdown>
            </div>
          );
        }
        return <ToolCallBlock
          key={item.id}
          call={item.data}
          onPreview={onPreview}
          subagentStream={
            item.data.capability === "run_subagent" && streaming.subagents.size > 0
              ? Array.from(streaming.subagents.entries()).map(([, s]) => ({
                  thinking: s.thinking,
                  items: s.items,
                  text: s.text,
                  completed: s.completed,
                }))[0]
              : undefined
          }
        />;
      })}

      {/* Current turn's thinking (live — not yet in items) */}
      {(streaming.thinking || (isThinkingStreaming && streaming.thinkingStartTime)) && (
        <ThinkingBlock
          content={streaming.thinking}
          isStreaming={isThinkingStreaming}
          durationSec={(streaming.text || streaming.completed) ? currentThinkingDuration : undefined}
        />
      )}

      {streaming.text && (
        <div className="markdown-body text-[14px] leading-[1.65] text-[var(--ink)]">
          <Markdown onWorkspaceLink={(p) => onPreview?.({ path: p })}>{streaming.text}</Markdown>
          {!streaming.completed && <span className="streaming-cursor" />}
        </div>
      )}

      {/* Model is streaming a tool call's arguments (large file bodies
          take minutes) — show live progress instead of dead air. */}
      {streaming.toolProgress && !streaming.completed && (
        <div
          role="status"
          aria-label="Preparing tool call"
          className="mb-4 flex min-w-0 items-center gap-1.5 text-xs text-ink-muted"
        >
          <span
            aria-hidden="true"
            className="pulse inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-warning"
          />
          <span className="min-w-0 break-words font-mono">
            Preparing {streaming.toolProgress.name ?? "tool call"}…
          </span>
          {streaming.toolProgress.argsChars > 0 && (
            <span className="shrink-0 font-mono text-ink-faint">
              {(streaming.toolProgress.argsChars / 1000).toFixed(1)}k chars
            </span>
          )}
        </div>
      )}

      {/* Between-turns affordance: a model call is in flight, nothing
          streamed back yet — otherwise the gap after a completed tool
          call reads as dead air. */}
      {streaming.awaitingModel && !streaming.completed && <TypingIndicator />}
      {streaming.awaitingModel && streaming.retryNotice && !streaming.completed && (
        <div
          className="mt-1 font-mono text-[11px]"
          style={{ color: "var(--ink-3)" }}
        >
          {streaming.retryNotice}
        </div>
      )}

      {/* Output files the run produced — only once the run completes:
          mid-run the agent may still rename/move/edit them, so early
          chips would point at paths that are about to go stale. */}
      {streaming.completed && fileRefs.length > 0 && <FileChips refs={fileRefs} onPreview={onPreview} agentId={agentId} sessionId={sessionId} />}

      {streaming.guardrailWarnings.length > 0 && (
        <div
          className="mt-2 rounded-[5px] border px-2.5 py-1.5 font-mono text-[11px]"
          style={{ borderColor: "var(--warning)", background: "var(--surface)", color: "var(--ink-2)" }}
        >
          {streaming.guardrailWarnings.map((w, i) => (
            <div key={i}>⚠ {w}</div>
          ))}
        </div>
      )}

      {!hasContent && !streaming.thinking && !streaming.awaitingModel && <TypingIndicator />}

      {streaming.turnCosts.length > 0 && (
        <div className="mt-2 flex items-center gap-2 font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
          {(() => {
            const totalOut = streaming.turnCosts.reduce((s, t) => s + t.tokensOut, 0);
            const totalCost = streaming.turnCosts.reduce((s, t) => s + t.cost, 0);
            const turns = streaming.turnCosts.length;
            return (
              <span>
                {turns} turn{turns !== 1 ? "s" : ""} · {totalOut} tokens · ${totalCost.toFixed(3)}
              </span>
            );
          })()}
        </div>
      )}
    </div>
  );
}

export function MessageRow({
  message,
  isLastInRun,
  subagentMessages,
  onPreview,
  agentId,
  sessionId,
  runFileRefs,
}: {
  message: ChatMessage;
  isLastInRun?: boolean;
  subagentMessages?: ChatMessage[];
  onPreview?: (source: PreviewSource) => void;
  agentId?: string;
  sessionId?: string | null;
  /** Output files this run produced — rendered at the end of the run. */
  runFileRefs?: FileRef[];
}) {
  if (message.role === "user") {
    // Parse attachment metadata (JSON string from the API)
    let attachmentFiles: { type: string; mime_type: string; filename: string; url?: string; path?: string; size?: number }[] = [];
    if (message.attachments) {
      try {
        const parsed = JSON.parse(message.attachments);
        if (Array.isArray(parsed)) {
          attachmentFiles = parsed.filter(
            (a: any) => a.filename || a.type === "url" || a.type === "image_url"
          );
        }
      } catch { /* ignore */ }
    }

    return (
      <div className="mb-6 flex flex-col items-end gap-1.5">
        {attachmentFiles.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {attachmentFiles.map((f, i) => (
              <MessageAttachmentCard key={i} file={f} agentId={agentId} sessionId={sessionId} onPreview={onPreview} />
            ))}
          </div>
        )}
        <div
          className="max-w-[75%] rounded-lg px-3.5 py-2.5 text-[14px] leading-[1.65] bg-ink text-surface dark:bg-[var(--accent-tint)] dark:text-ink"
        >
          {message.content}
        </div>
        <MessageActions content={message.content} />
      </div>
    );
  }

  if (message.role === "thinking") {
    return (
      <div className="mb-4">
        <ThinkingBlock content={message.content} isStreaming={false} />
      </div>
    );
  }

  if (message.role === "tool_call") {
    try {
      const data = JSON.parse(message.content) as ToolCallData;
      // Build subagent stream from persisted sub-agent messages
      let subagentStream: SubAgentStreamData | undefined;
      if (data.capability === "run_subagent" && subagentMessages && subagentMessages.length > 0) {
        const items: { type: "thinking" | "tool"; id: string; data: ThinkingBlockData | ToolCallData }[] = [];
        let text = "";
        for (const sm of subagentMessages) {
          if (sm.role === "thinking") {
            items.push({ type: "thinking", id: sm.id, data: { content: sm.content, durationSec: null } });
          } else if (sm.role === "tool_call") {
            try {
              const tcData = JSON.parse(sm.content) as ToolCallData;
              items.push({ type: "tool", id: sm.id, data: tcData });
            } catch { /* skip */ }
          } else if (sm.role === "assistant") {
            text += sm.content;
          }
        }
        subagentStream = { thinking: "", items, text, completed: true };
      }
      return (
        <div className="mb-4">
          <ToolCallBlock call={data} subagentStream={subagentStream} onPreview={onPreview} />
        </div>
      );
    } catch {
      return null;
    }
  }

  // Origin badge for non-chat runs — driven by run.trigger (schedule, heartbeat,
  // channel…); legacy rows predate trigger and carry role="heartbeat" instead.
  const origin =
    message.role === "heartbeat"
      ? "heartbeat"
      : message.role === "assistant" && message.trigger && message.trigger !== "user_message"
        ? message.is_test === true
          ? "test"
          : message.trigger
        : null;
  if (origin) {
    const ts = message.created_at ? new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
    return (
      <div className="mb-6">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="font-mono text-[11px] font-medium" style={{ color: "#7C3AED" }}>♢ {origin}</span>
          {ts && (
            <span className="font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>· {ts}</span>
          )}
        </div>
        <div
          className="markdown-body border-l-[3px] pl-4 text-[14px] leading-[1.65]"
          style={{ borderColor: "#7C3AED" }}
        >
          <Markdown onWorkspaceLink={(p) => onPreview?.({ path: p })}>{message.content}</Markdown>
        </div>
        <div className="mt-1.5 flex items-center gap-3">
          <MessageActions content={message.content} messageId={message.id} />
        </div>
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="mb-6 text-center text-[12px] text-[var(--ink-3)]">
        {message.content}
      </div>
    );
  }

  // assistant — left-aligned, no bubble, markdown rendered
  // Cost badge only on the last message of the run (tokens_out/cost are run-level)
  const hasCost = isLastInRun && (message.tokens_out || message.cost);
  return (
    <div className="mb-6">
      <div className="markdown-body text-[14px] leading-[1.65] text-[var(--ink)]">
        <Markdown onWorkspaceLink={(p) => onPreview?.({ path: p })}>{message.content}</Markdown>
      </div>
      {/* Output files the run produced — end of the run, above sources. */}
      {runFileRefs && runFileRefs.length > 0 && (
        <FileChips refs={runFileRefs} onPreview={onPreview} agentId={agentId} sessionId={sessionId} />
      )}
      {message.citations && message.citations.length > 0 && <CitationList citations={message.citations} />}
      <div className="mt-1.5 flex items-center gap-1.5">
        <MessageActions content={message.content} messageId={message.id} />
        {hasCost && (
          <div className="shrink-0 font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
            {message.tokens_out || 0} tokens · ${(message.cost || 0).toFixed(3)}
          </div>
        )}
      </div>
    </div>
  );
}

function CitationList({ citations }: { citations: NonNullable<Message["citations"]> }) {
  return (
    <details className="group mt-3 rounded-[10px] border border-line bg-surface px-3.5 py-2.5">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2">
          <BookOpen className="h-3.5 w-3.5 text-ink-faint" />
          <span className="text-[13px] font-medium text-ink">
            Sources · {citations.length}
          </span>
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-ink-faint transition-transform duration-200 group-open:rotate-180" />
      </summary>
      <div className="mt-2 space-y-1.5 border-t border-line pt-2.5">
        {citations.map((citation, index) => {
          const location = citation.page_number
            ? `page ${citation.page_number}`
            : citation.sheet_name || citation.heading_path.at(-1) || citation.source_location;
          let domain = citation.source_path;
          try {
            domain = new URL(citation.source_path).hostname.replace(/^www\./, "");
          } catch {
            /* not a URL — keep the raw path */
          }
          const label = citation.title || domain;
          return (
            <details
              key={citation.id}
              className="group/item rounded-md border border-line bg-surface px-2.5 py-2"
            >
              <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded bg-accent-tint font-mono text-[10px] font-semibold text-accent">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-ink">
                    {label}
                    {location ? <span className="text-ink-faint"> · {location}</span> : null}
                  </span>
                  <a
                    href={citation.source_type === "web" ? citation.source_path : undefined}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className={`block truncate font-mono text-[10px] text-ink-faint ${
                      citation.source_type === "web"
                        ? "underline-offset-2 hover:text-accent hover:underline"
                        : ""
                    }`}
                  >
                    {domain !== label ? `${domain} — ` : ""}{citation.source_path}
                  </a>
                </span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-faint transition-transform duration-200 group-open/item:rotate-180" />
              </summary>
              {citation.excerpt && (
                <p className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap break-all border-t border-line pt-2 text-xs leading-5 text-ink-muted">
                  {citation.excerpt}
                </p>
              )}
            </details>
          );
        })}
      </div>
    </details>
  );
}

export function TypingIndicator() {
  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center gap-1.5">
        <span
          className="pulse inline-block h-1.5 w-1.5 rounded-full"
          style={{ background: "#FBBF24" }}
        />
        <span className="font-mono text-[11px] text-[var(--ink-2)]">
          thinking…
        </span>
      </div>
      <div className="flex gap-1">
        <span className="bounce-dot" />
        <span className="bounce-dot" />
        <span className="bounce-dot" />
      </div>
    </div>
  );
}

/** Message-level attachment card — the shared AttachmentCard in open mode.
 *  Images fetch a real thumbnail through the preview backend's blob read;
 *  files with a stored path open the preview panel; URLs open a new tab. */
function MessageAttachmentCard({
  file,
  agentId,
  sessionId,
  onPreview,
}: {
  file: { type: string; mime_type: string; filename: string; url?: string; path?: string; size?: number; preview_url?: string };
  agentId?: string;
  sessionId?: string | null;
  onPreview?: (source: PreviewSource) => void;
}) {
  const isUrl = file.type === "url" || file.type === "image_url";
  const isImage = !isUrl && (file.type === "image" || file.mime_type?.startsWith("image/"));
  // Persisted blob wins once path exists; `preview_url` is the draft's
  // ephemeral data URL covering the window before persistence lands.
  const { url: blobUrl } = useObjectUrl(
    isImage && file.path && agentId
      ? () => workspaceBackend(agentId, sessionId ?? undefined).blob({ path: file.path! })
      : null,
    [file.path, agentId, sessionId]
  );

  // Images render inline at view size — bare <img>, click opens preview.
  // preview_url covers the pre-persist window.
  const imageSrc = blobUrl ?? file.preview_url;
  if (isImage && imageSrc) {
    return (
      <img
        src={imageSrc}
        alt={file.filename}
        title={`Preview ${file.filename}`}
        onClick={file.path && onPreview ? () => onPreview({ path: file.path! }) : undefined}
        className={`max-h-72 w-auto max-w-full rounded-[10px] object-contain transition-opacity ${
          file.path && onPreview ? "cursor-pointer hover:opacity-90" : ""
        }`}
      />
    );
  }

  return (
    <AttachmentCard
      type={file.type}
      filename={file.filename}
      mimeType={file.mime_type}
      size={file.size}
      url={isUrl ? file.url : undefined}
      thumbUrl={blobUrl ?? file.preview_url}
      onOpen={!isUrl && file.path && onPreview ? () => onPreview({ path: file.path! }) : undefined}
    />
  );
}
