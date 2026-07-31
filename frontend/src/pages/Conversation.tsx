import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowDown, PanelLeft } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import type { Agent, Message, SessionInfo } from "@/lib/types";
import { ToolCallBlock, type ToolCallData } from "@/components/ToolCallBlock";
import { ThinkingBlock } from "@/components/ThinkingBlock";
import { ChatSidebar } from "@/components/ChatSidebar";
import { ChatInputBar, type ContextItem } from "@/components/ChatInputBar";
import { SettingsOverlay } from "@/components/SettingsOverlay";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

interface TurnCost {
  turnNumber: number;
  tokensIn: number;
  tokensOut: number;
  cost: number;
}

interface StreamingResponse {
  thinking: string;
  text: string;
  toolCalls: Map<string, ToolCallData>;
  toolCallOrder: string[];
  thinkingStartTime: number | null;
  turnCosts: TurnCost[];
  guardrailWarnings: string[];
  completed: boolean;  // true when run is done — hides cursor, keeps content visible
}

interface ElicitationOption {
  label: string;
  description: string;
}

interface ActiveElicitation {
  id: string;
  question: string;
  options: ElicitationOption[] | null;
  multiSelect: boolean;
}

export function Conversation() {
  const { id: agentId } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [agent, setAgent] = useState<Agent | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streaming, setStreaming] = useState<StreamingResponse | null>(null);
  const [inputWarnings, setInputWarnings] = useState<string[]>([]);
  const [activeElicitation, setActiveElicitation] = useState<ActiveElicitation | null>(null);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const activeSessionRef = useRef<string | null>(null);
  const streamingRef = useRef<StreamingResponse | null>(null);

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  useEffect(() => {
    if (!agentId) return;
    api.getAgent(agentId).then(setAgent).catch(() => {});
  }, [agentId]);

  const loadSessions = useCallback(() => {
    if (!agentId) return;
    api.listSessions(agentId).then(setSessions).catch(() => {});
  }, [agentId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (!agentId || !activeSessionId) {
      setMessages([]);
      return;
    }
    api
      .getSessionMessages(agentId, activeSessionId)
      .then((msgs) => {
        setMessages(
          msgs.map((m: Message) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            created_at: m.created_at,
          })),
        );
      })
      .catch(() => {});
  }, [agentId, activeSessionId]);

  // SSE event handling is done inside handleSend via the run manager.
  // POST /message starts a run → GET /runs/{id}/events streams events.
  // The run survives disconnects — reconnect with Last-Event-ID to resume.

  // Track the active run so we can reconnect or stop it
  const activeRunRef = useRef<{ runId: string; lastEventId: number } | null>(null);

  // Handle a single SSE event — shared between initial stream and reconnects
  const handleEvent = (event: string, data: any) => {
    switch (event) {
      case "typing":
        break;

      case "thinking":
        setStreaming((prev) =>
          prev ? { ...prev, thinking: prev.thinking + data.content } : prev,
        );
        break;

      case "token":
        setStreaming((prev) =>
          prev ? { ...prev, text: prev.text + data.content } : prev,
        );
        break;

      case "guardrail_correction":
        setStreaming((prev) =>
          prev ? { ...prev, text: data.content } : prev,
        );
        break;

      case "guardrail_warning":
        if (data.direction === "input") {
          setInputWarnings(data.warnings);
        } else {
          setStreaming((prev) =>
            prev ? { ...prev, guardrailWarnings: data.warnings } : prev,
          );
        }
        break;

      case "clarifying_question":
        // Set active elicitation — the chat bar transforms into the elicitation input
        setActiveElicitation({
          id: data.id,
          question: data.question,
          options: data.options,
          multiSelect: data.multi_select || false,
        });
        // Mark the tool call as pending_input so the ToolCallBlock shows "waiting"
        setStreaming((prev) => {
          if (!prev) return prev;
          const newToolCalls = new Map(prev.toolCalls);
          const existing = newToolCalls.get(data.tool_call_id);
          if (existing) {
            newToolCalls.set(data.tool_call_id, {
              ...existing,
              status: "pending_input",
              elicitation_id: data.id,
            });
          }
          return { ...prev, toolCalls: newToolCalls };
        });
        break;

      case "tool_call":
        setStreaming((prev) => {
          if (!prev) return prev;
          const newToolCalls = new Map(prev.toolCalls);
          const existing = newToolCalls.get(data.id);
          newToolCalls.set(data.id, {
            id: data.id,
            capability: data.capability,
            args: data.args,
            status: data.status,
            result: data.result,
            approval_id: data.approval_id,
            elicitation_id: existing?.elicitation_id,
          });
          const newOrder = prev.toolCallOrder.includes(data.id)
            ? prev.toolCallOrder
            : [...prev.toolCallOrder, data.id];
          return { ...prev, toolCalls: newToolCalls, toolCallOrder: newOrder };
        });
        break;

      case "turn_complete":
        setStreaming((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            turnCosts: [
              ...prev.turnCosts,
              {
                turnNumber: data.turn_number,
                tokensIn: data.tokens_in,
                tokensOut: data.tokens_out,
                cost: data.cost,
              },
            ],
          };
        });
        break;

      case "message_complete":
        if (data.session_id && !activeSessionRef.current) {
          setActiveSessionId(data.session_id);
        }
        // Mark streaming as completed — keep all thinking/tool calls/costs visible
        // The streaming block stays rendered with completed=true (no cursor)
        setStreaming((prev) => prev ? { ...prev, completed: true } : prev);
        setIsStreaming(false);
        activeRunRef.current = null;
        loadSessions();
        break;
    }
  };

  // Stream events from a run, with reconnect support
  const streamRun = async (agentId: string, runId: string, fromSeq = 0) => {
    let lastEventId = fromSeq;
    try {
      for await (const { event, data, id } of api.streamRunEvents(agentId, runId, lastEventId)) {
        if (id > lastEventId) lastEventId = id;
        handleEvent(event, data);
      }
    } catch {
      // Stream disconnected — try to reconnect if the run is still active
      if (activeRunRef.current?.runId === runId) {
        activeRunRef.current.lastEventId = lastEventId;
        // Reconnect after a short delay
        await new Promise((r) => setTimeout(r, 1000));
        if (activeRunRef.current?.runId === runId) {
          // Check if run is still active before reconnecting
          try {
            const status = await api.getRunStatus(agentId, runId);
            if (status.status === "running" || status.status === "awaiting_approval") {
              await streamRun(agentId, runId, lastEventId);
            }
          } catch {
            // Run gone — stop streaming
            setStreaming(null);
            setIsStreaming(false);
            activeRunRef.current = null;
          }
        }
      }
    }
  };

  const handleScroll = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const nearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight <
      100;
    autoScrollRef.current = nearBottom;
    setShowJumpToLatest(!nearBottom);
  };

  useEffect(() => {
    if (autoScrollRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streaming, isStreaming]);

  const handleJumpToLatest = () => {
    autoScrollRef.current = true;
    setShowJumpToLatest(false);
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const handleNewChat = () => {
    // Just deselect — the empty state IS the new chat view.
    // A session is created automatically when the first message is sent.
    setActiveSessionId(null);
    setMessages([]);
    setStreaming(null);
    setIsStreaming(false);
  };

  const handleSelectSession = (id: string) => {
    // Save completed streaming text before switching
    if (streamingRef.current?.completed && streamingRef.current.text) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: streamingRef.current!.text,
          created_at: new Date().toISOString(),
        },
      ]);
    }
    setStreaming(null);
    setIsStreaming(false);
    setActiveSessionId(id);
  };

  const handleDeleteSession = async (id: string) => {
    if (!agentId) return;
    try {
      await api.deleteSession(agentId, id);
      if (activeSessionId === id) {
        setActiveSessionId(null);
        setMessages([]);
      }
      loadSessions();
    } catch {}
  };

  const handleElicitationRespond = async (response: string) => {
    if (!activeElicitation) return;
    const el = activeElicitation;
    setActiveElicitation(null);

    // Build the question message (includes options if any)
    let questionContent = el.question;
    if (el.options && el.options.length > 0) {
      questionContent += "\n";
      el.options.forEach((opt, i) => {
        questionContent += `\n${i + 1}. ${opt.label}`;
        if (opt.description) questionContent += ` — ${opt.description}`;
      });
    }

    // Add Q&A pair to chat history
    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        content: questionContent,
        created_at: new Date().toISOString(),
      },
      {
        id: crypto.randomUUID(),
        role: "user",
        content: response,
        created_at: new Date().toISOString(),
      },
    ]);

    try {
      await api.respondToElicitation(el.id, response);
    } catch {
      // If failed, re-open the elicitation so user can retry
      setActiveElicitation(el);
      // Remove the Q&A we just added
      setMessages((prev) => prev.slice(0, -2));
    }
  };

  const handleSend = async (
    text: string,
    modelOverride: { provider_id: string; name: string } | null,
    _context: ContextItem[],
    attachments?: { type: string; mimeType: string; data: string; filename: string }[],
  ) => {
    if (!agentId) return;

    // If no active session, create one first
    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const session = await api.createSession(agentId);
        sessionId = session.id;
        setActiveSessionId(sessionId);
        loadSessions();
      } catch {
        return;
      }
    }

    // If there's a completed streaming block, save its final text to messages
    // before starting a new run (so the history persists)
    if (streamingRef.current?.completed && streamingRef.current.text) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: streamingRef.current!.text,
          created_at: new Date().toISOString(),
        },
      ]);
    }

    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      },
    ]);

    setInputWarnings([]);
    setStreaming({
      thinking: "",
      text: "",
      toolCalls: new Map(),
      toolCallOrder: [],
      thinkingStartTime: Date.now(),
      turnCosts: [],
      guardrailWarnings: [],
      completed: false,
    });
    setIsStreaming(true);
    autoScrollRef.current = true;

    // Step 1: POST /message to start the run
    try {
      const result = await api.sendMessage(
        agentId,
        text,
        true, // demo mode — uses ScriptedModel
        modelOverride || undefined,
        sessionId || undefined,
        attachments?.map((a) => ({
          type: a.type,
          mime_type: a.mimeType,
          data: a.data,
          filename: a.filename,
        })),
      );

      // Track the active run for reconnect/stop
      activeRunRef.current = { runId: result.run_id, lastEventId: 0 };

      // Step 2: Stream events from GET /runs/{id}/events
      await streamRun(agentId, result.run_id, 0);
    } catch {
      setStreaming(null);
      setIsStreaming(false);
    }
  };

  const headerTitle =
    sessions.find((s) => s.id === activeSessionId)?.title ||
    agent?.name ||
    agentId ||
    "";

  // Session timer — shows elapsed time since session started
  const activeSession = sessions.find((s) => s.id === activeSessionId);
  const [sessionElapsed, setSessionElapsed] = useState("");
  useEffect(() => {
    if (!activeSession?.started_at) {
      setSessionElapsed("");
      return;
    }
    const update = () => {
      const start = new Date(activeSession.started_at).getTime();
      const elapsed = Math.floor((Date.now() - start) / 1000);
      if (elapsed < 60) setSessionElapsed(`${elapsed}s`);
      else if (elapsed < 3600) setSessionElapsed(`${Math.floor(elapsed / 60)}m ${elapsed % 60}s`);
      else setSessionElapsed(`${Math.floor(elapsed / 3600)}h ${Math.floor((elapsed % 3600) / 60)}m`);
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [activeSession?.started_at]);

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--surface)" }}>
      {/* Sidebar */}
      <ChatSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        collapsed={sidebarCollapsed}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onOpenSettings={() => setSettingsOpen(true)}
        onBackToAgents={() => navigate("/")}
      />

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Header */}
        <div
          className="flex items-center gap-2 px-4 py-2"
          style={{
            background: "var(--sidebar)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <span
            className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[13px] font-medium text-[var(--ink-2)]"
          >
            {headerTitle}
          </span>
          {sessionElapsed && (
            <span
              className="text-[11px] tabular-nums text-[var(--ink-3)]"
              title="Session elapsed time"
            >
              {sessionElapsed}
            </span>
          )}
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            className="flex h-7 w-7 items-center justify-center rounded text-[var(--ink-2)] transition"
            style={{ border: "none", background: "none", cursor: "pointer" }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--border)";
              e.currentTarget.style.color = "var(--ink)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "none";
              e.currentTarget.style.color = "var(--ink-2)";
            }}
            title={sidebarCollapsed ? "Show sidebar" : "Hide sidebar"}
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        </div>

        {/* Messages */}
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="relative flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-[672px] px-6 py-6">
            {messages.length === 0 && !isStreaming && (
              <div className="flex h-full flex-col items-center justify-center pt-32 text-center">
                <h2 className="text-[18px] font-semibold text-[var(--ink)]">
                  {agent?.name || agentId}
                </h2>
                <p className="mt-2 text-[14px] text-[var(--ink-2)]">
                  {agent?.soul || "Start a conversation to begin."}
                </p>
              </div>
            )}

            {messages.map((msg) => (
              <MessageRow key={msg.id} message={msg} />
            ))}

            {inputWarnings.length > 0 && (
              <div
                className="mb-3 rounded-[5px] border px-3 py-2 font-mono text-[11px]"
                style={{ borderColor: "var(--warning)", background: "var(--surface)", color: "var(--ink-2)" }}
              >
                {inputWarnings.map((w, i) => (
                  <div key={i}>⚠ {w}</div>
                ))}
              </div>
            )}

            {isStreaming && streaming && (
              <StreamingMessage streaming={streaming} />
            )}
            {isStreaming && !streaming && <TypingIndicator />}
            {/* Completed streaming block — keeps thinking/tool calls/costs visible after run ends */}
            {!isStreaming && streaming && streaming.completed && (
              <StreamingMessage streaming={streaming} />
            )}

            <div ref={messagesEndRef} />
          </div>

          {showJumpToLatest && (
            <button
              onClick={handleJumpToLatest}
              className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full px-3 py-1.5 text-[12px] shadow-lg"
              style={{
                background: "var(--white)",
                border: "1px solid var(--border)",
                color: "var(--ink-2)",
                cursor: "pointer",
              }}
            >
              <ArrowDown className="mr-1 inline h-3 w-3" />
              Jump to latest
            </button>
          )}
        </div>

        {/* Input bar */}
        <ChatInputBar
          defaultProviderId={agent?.provider_id || null}
          defaultModelName={agent?.model || null}
          disabled={isStreaming && !activeElicitation}
          onSend={handleSend}
          activeElicitation={activeElicitation}
          onElicitationRespond={handleElicitationRespond}
        />
      </div>

      {/* Settings overlay */}
      <SettingsOverlay
        agent={agent}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}

function StreamingMessage({ streaming }: { streaming: StreamingResponse }) {
  const hasContent = streaming.text || streaming.toolCallOrder.length > 0;
  const thinkingDuration = streaming.thinkingStartTime
    ? Math.round((Date.now() - streaming.thinkingStartTime) / 1000)
    : undefined;

  return (
    <div className="mb-6">
      {(streaming.thinking || streaming.thinkingStartTime) && (
        <ThinkingBlock
          content={streaming.thinking}
          isStreaming={!!streaming.thinking && !streaming.text && !streaming.completed}
          durationSec={(streaming.text || streaming.completed) ? thinkingDuration : undefined}
        />
      )}

      {streaming.toolCallOrder.map((id) => {
        const tc = streaming.toolCalls.get(id);
        if (!tc) return null;
        return <ToolCallBlock key={id} call={tc} />;
      })}

      {streaming.text && (
        <div className="markdown-body text-[14px] leading-[1.65] text-[var(--ink)]">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{streaming.text}</ReactMarkdown>
          {!streaming.completed && <span className="streaming-cursor" />}
        </div>
      )}

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

      {!hasContent && !streaming.thinking && <TypingIndicator />}

      {streaming.turnCosts.length > 0 && (
        <div className="mt-2 flex items-center gap-2 font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
          {(() => {
            const totalIn = streaming.turnCosts.reduce((s, t) => s + t.tokensIn, 0);
            const totalOut = streaming.turnCosts.reduce((s, t) => s + t.tokensOut, 0);
            const totalCost = streaming.turnCosts.reduce((s, t) => s + t.cost, 0);
            const turns = streaming.turnCosts.length;
            return (
              <span>
                {turns} turn{turns !== 1 ? "s" : ""} · {totalIn + totalOut} tokens · ${totalCost.toFixed(3)}
              </span>
            );
          })()}
        </div>
      )}
    </div>
  );
}

function MessageRow({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="mb-6 flex justify-end">
        <div
          className="max-w-[75%] rounded-lg px-3.5 py-2.5 text-[14px] leading-[1.65]"
          style={{
            background: "var(--accent)",
            color: "var(--white)",
          }}
        >
          {message.content}
        </div>
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
      return (
        <div className="mb-4">
          <ToolCallBlock call={data} />
        </div>
      );
    } catch {
      return null;
    }
  }

  if (message.role === "heartbeat") {
    return (
      <div
        className="mb-6 border-l-2 pl-4 text-[13px] text-[var(--ink-2)]"
        style={{ borderColor: "var(--warning)" }}
      >
        {message.content}
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
  return (
    <div className="markdown-body mb-6 text-[14px] leading-[1.65] text-[var(--ink)]">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
    </div>
  );
}

function TypingIndicator() {
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
