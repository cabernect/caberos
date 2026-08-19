import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowDown, PanelLeft, AlertCircle, FileIcon, Paperclip, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Agent, Message, Provider, SessionInfo } from "@/lib/types";
import { ToolCallBlock, type ToolCallData, type SubAgentStreamData } from "@/components/ToolCallBlock";
import { Markdown } from "@/components/Markdown";
import { ThinkingBlock } from "@/components/ThinkingBlock";
import { ProcessSteps } from "@/components/ProcessSteps";
import { ChatSidebar } from "@/components/ChatSidebar";
import { ChatInputBar, type ChatInputBarHandle, type ContextItem } from "@/components/ChatInputBar";
import { SettingsOverlay } from "@/components/SettingsOverlay";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  run_id?: string;
  run_status?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost?: number;
  subagent_id?: string | null;
  attachments?: string | null;
}

interface TurnCost {
  turnNumber: number;
  tokensIn: number;
  tokensOut: number;
  cost: number;
}

interface ThinkingBlockData {
  content: string;
  durationSec: number | null;
}

type StreamItem =
  | { type: "thinking"; id: string; data: ThinkingBlockData }
  | { type: "text"; id: string; data: { content: string } }
  | { type: "tool"; id: string; data: ToolCallData };

interface SubAgentStream {
  thinking: string;
  items: StreamItem[];
  text: string;
  toolCalls: Map<string, ToolCallData>;
  thinkingStartTime: number | null;
  completed: boolean;
}

interface StreamingResponse {
  thinking: string;          // current turn's thinking (accumulating)
  items: StreamItem[];       // ordered list of completed thinking blocks + tool calls
  text: string;
  toolCalls: Map<string, ToolCallData>;
  thinkingStartTime: number | null;
  thinkingEndTime: number | null;
  turnCosts: TurnCost[];
  guardrailWarnings: string[];
  completed: boolean;  // true when run is done — hides cursor, keeps content visible
  subagents: Map<string, SubAgentStream>;  // subagent_id -> nested stream
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
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [contextTokens, setContextTokens] = useState<number | undefined>(undefined);
  const [cachedTokens, setCachedTokens] = useState<number | undefined>(undefined);
  const [maxContextTokens, setMaxContextTokens] = useState<number | undefined>(undefined);
  const [compacted, setCompacted] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [contextBreakdown, setContextBreakdown] = useState<{ system_prompt: number; conversation: number; tools: number } | undefined>(undefined);
  const [hasModelSelected, setHasModelSelected] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const activeSessionRef = useRef<string | null>(null);
  const streamingRef = useRef<StreamingResponse | null>(null);
  const inputBarRef = useRef<ChatInputBarHandle>(null);
  const dragCounterRef = useRef(0);

  // Support multiple concurrent runs — one per session.
  // Each entry tracks the run's streaming state, runId, and lastEventId.
  // The "active" run is the one the user is currently viewing.
  interface RunEntry {
    runId: string;
    sessionId: string;
    lastEventId: number;
    streaming: StreamingResponse | null;
    elicitation: ActiveElicitation | null;
    abortController: AbortController | null;  // active SSE connection (null = not streaming)
  }
  const runEntriesRef = useRef<Map<string, RunEntry>>(new Map()); // keyed by sessionId

  // Set of sessions with active (non-completed) runs — for sidebar spinners
  const [runningSessionIds, setRunningSessionIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);

  useEffect(() => {
    streamingRef.current = streaming;
  }, [streaming]);

  const [providers, setProviders] = useState<Provider[]>([]);

  const reloadAgent = useCallback(() => {
    if (!agentId) return;
    api.getAgent(agentId).then(setAgent).catch(() => {});
  }, [agentId]);

  useEffect(() => {
    reloadAgent();
  }, [reloadAgent]);

  useEffect(() => {
    api.listProviders().then(setProviders).catch(() => {});
  }, []);

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
        let mapped = msgs.map((m: Message) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          created_at: m.created_at,
          run_id: m.run_id,
          run_status: m.run_status,
          tokens_in: m.tokens_in,
          tokens_out: m.tokens_out,
          cost: m.cost,
          subagent_id: m.subagent_id,
          attachments: m.attachments,
        }));
        // If this session has an active run that we're streaming, drop the
        // run's non-user messages (thinking, tool_call, assistant) — they're
        // shown by the streaming block. Keep the user message.
        const runEntry = runEntriesRef.current.get(activeSessionId);
        if (runEntry) {
          const runId = runEntry.runId;
          mapped = mapped.filter(
            (m) => m.role === "user" || m.run_id !== runId,
          );
        }
        // Deduplicate by content+role to avoid showing the same user message
        // twice (optimistic message has a different ID than the persisted one).
        // Only preserve optimistic messages that don't have a matching
        // content+role in the API response.
        setMessages((prev) => {
          const apiUserContents = new Set(
            mapped.filter((m) => m.role === "user").map((m) => m.content),
          );
          // Only keep optimistic messages from prev if they belong to THIS
          // session (not from another session the user switched from).
          // We can't track session per message, so we only preserve messages
          // whose content isn't already in the API response.
          const optimistic = prev.filter(
            (m) =>
              m.role === "user" &&
              !apiUserContents.has(m.content) &&
              !mapped.some((mm) => mm.id === m.id),
          );
          return [...mapped, ...optimistic];
        });
      })
      .catch(() => {});
  }, [agentId, activeSessionId]);

  // SSE event handling is done inside handleSend via the run manager.
  // POST /message starts a run → GET /runs/{id}/events streams events.
  // The run survives disconnects — reconnect with Last-Event-ID to resume.

  // Helper: update the streaming state for a specific session's run.
  // Updates the ref (source of truth) and syncs to React state only if
  // the user is currently viewing that session.
  const updateStreamingForSession = (
    sessionId: string,
    updater: (prev: StreamingResponse | null) => StreamingResponse | null,
  ) => {
    const entry = runEntriesRef.current.get(sessionId);
    if (!entry) return;
    const next = updater(entry.streaming);
    entry.streaming = next;
    // Only update the UI state if the user is viewing this session
    if (activeSessionRef.current === sessionId) {
      setStreaming(next);
      streamingRef.current = next;
    }
  };

  // Handle a single SSE event — shared between initial stream and reconnects.
  // `sessionId` identifies which run this event belongs to.
  const handleEvent = (event: string, data: any, sessionId: string) => {
    // Route sub-agent events to nested subagent streams
    if (data.subagent_id) {
      updateStreamingForSession(sessionId, (prev) => {
        if (!prev) return prev;
        const subagents = new Map(prev.subagents);
        let sub = subagents.get(data.subagent_id);
        if (!sub) {
          sub = {
            thinking: "",
            items: [],
            text: "",
            toolCalls: new Map(),
            thinkingStartTime: Date.now(),
            completed: false,
          };
        }

        switch (event) {
          case "thinking":
            sub = { ...sub, thinking: sub.thinking + data.content };
            break;
          case "token": {
            let items = sub.items;
            let thinking = sub.thinking;
            if (thinking) {
              const durationSec = sub.thinkingStartTime
                ? Math.round((Date.now() - sub.thinkingStartTime) / 1000)
                : null;
              items = [...items, { type: "thinking" as const, id: `sub-thinking-${items.length}`, data: { content: thinking, durationSec } }];
              thinking = "";
            }
            sub = { ...sub, items, thinking, text: sub.text + data.content };
            break;
          }
          case "tool_call": {
            let items = sub.items;
            let thinking = sub.thinking;
            if (thinking) {
              const durationSec = sub.thinkingStartTime
                ? Math.round((Date.now() - sub.thinkingStartTime) / 1000)
                : null;
              items = [...items, { type: "thinking" as const, id: `sub-thinking-${items.length}`, data: { content: thinking, durationSec } }];
              thinking = "";
            }
            const newToolCalls = new Map(sub.toolCalls);
            const toolData: ToolCallData = {
              id: data.id,
              capability: data.capability,
              args: data.args,
              status: data.status,
              result: data.result,
            };
            newToolCalls.set(data.id, toolData);
            const exists = items.some(i => i.type === "tool" && i.id === data.id);
            const newItems = exists
              ? items.map(i => i.type === "tool" && i.id === data.id ? { ...i, data: toolData } : i)
              : [...items, { type: "tool" as const, id: data.id, data: toolData }];
            sub = { ...sub, toolCalls: newToolCalls, items: newItems, thinking };
            break;
          }
          case "turn_complete": {
            const durationSec = sub.thinkingStartTime
              ? Math.round((Date.now() - sub.thinkingStartTime) / 1000)
              : null;
            const newItems = sub.thinking
              ? [...sub.items, { type: "thinking" as const, id: `sub-thinking-${sub.items.length}`, data: { content: sub.thinking, durationSec } }]
              : sub.items;
            sub = { ...sub, items: newItems, thinking: "", thinkingStartTime: Date.now() };
            break;
          }
          case "message_complete":
            sub = { ...sub, completed: true };
            break;
        }

        subagents.set(data.subagent_id, sub);
        return { ...prev, subagents };
      });
      return;
    }

    switch (event) {
      case "typing":
        break;

      case "thinking":
        updateStreamingForSession(sessionId, (prev) =>
          prev ? { ...prev, thinking: prev.thinking + data.content } : prev,
        );
        break;

      case "token":
        // Flush buffered thinking into items before the text appears,
        // so thinking is shown above the text (not below).
        updateStreamingForSession(sessionId, (prev) => {
          if (!prev) return prev;
          let items = prev.items;
          let thinking = prev.thinking;
          if (thinking) {
            const durationSec = prev.thinkingStartTime
              ? Math.round((Date.now() - prev.thinkingStartTime) / 1000)
              : null;
            items = [...items, { type: "thinking" as const, id: `thinking-${items.length}`, data: { content: thinking, durationSec } }];
            thinking = "";
          }
          return { ...prev, items, thinking, text: prev.text + data.content };
        });
        break;

      case "guardrail_correction":
        updateStreamingForSession(sessionId, (prev) =>
          prev ? { ...prev, text: data.content } : prev,
        );
        break;

      case "guardrail_warning":
        if (data.direction === "input") {
          setInputWarnings(data.warnings);
        } else {
          updateStreamingForSession(sessionId, (prev) =>
            prev ? { ...prev, guardrailWarnings: data.warnings } : prev,
          );
        }
        break;

      case "clarifying_question":
        // Store elicitation per-session in the run entry
        {
          const entry = runEntriesRef.current.get(sessionId);
          if (entry) {
            entry.elicitation = {
              id: data.id,
              question: data.question,
              options: data.options,
              multiSelect: data.multi_select || false,
            };
            // Show it in the UI only if the user is viewing this session
            if (activeSessionRef.current === sessionId) {
              setActiveElicitation(entry.elicitation);
            }
          }
        }
        // Mark the tool call as pending_input so the ToolCallBlock shows "waiting"
        updateStreamingForSession(sessionId, (prev) => {
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
        updateStreamingForSession(sessionId, (prev) => {
          if (!prev) return prev;
          // Flush buffered thinking AND text into items before the tool call,
          // so they appear above the tool call (not below).
          let items = prev.items;
          let thinking = prev.thinking;
          let text = prev.text;
          if (thinking) {
            const durationSec = prev.thinkingStartTime
              ? Math.round((Date.now() - prev.thinkingStartTime) / 1000)
              : null;
            items = [...items, { type: "thinking" as const, id: `thinking-${items.length}`, data: { content: thinking, durationSec } }];
            thinking = "";
          }
          if (text) {
            items = [...items, { type: "text" as const, id: `text-${items.length}`, data: { content: text } }];
            text = "";
          }
          const newToolCalls = new Map(prev.toolCalls);
          const existing = newToolCalls.get(data.id);
          const toolData: ToolCallData = {
            id: data.id,
            capability: data.capability,
            args: data.args,
            status: data.status,
            result: data.result,
            approval_id: data.approval_id,
            elicitation_id: existing?.elicitation_id,
          };
          newToolCalls.set(data.id, toolData);
          // Add to items list if not already there
          const exists = items.some(i => i.type === "tool" && i.id === data.id);
          const newItems = exists
            ? items.map(i => i.type === "tool" && i.id === data.id ? { ...i, data: toolData } : i)
            : [...items, { type: "tool" as const, id: data.id, data: toolData }];
          return { ...prev, toolCalls: newToolCalls, items: newItems, thinking, text };
        });
        break;

      case "turn_complete":
        setCachedTokens(data.cached_tokens ?? undefined);
        updateStreamingForSession(sessionId, (prev) => {
          if (!prev) return prev;
          // Push the current turn's thinking into the items list, then reset
          const durationSec = prev.thinkingStartTime
            ? Math.round((Date.now() - prev.thinkingStartTime) / 1000)
            : null;
          let newItems = prev.items;
          if (prev.thinking) {
            newItems = [...newItems, { type: "thinking" as const, id: `thinking-${newItems.length}`, data: { content: prev.thinking, durationSec } }];
          }
          if (prev.text) {
            newItems = [...newItems, { type: "text" as const, id: `text-${newItems.length}`, data: { content: prev.text } }];
          }
          return {
            ...prev,
            thinking: "",
            text: "",
            items: newItems,
            thinkingStartTime: Date.now(),  // reset for next turn
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
        // Update context bar
        if (data.context_tokens != null) setContextTokens(data.context_tokens);
        if (data.max_context_tokens != null) setMaxContextTokens(data.max_context_tokens);
        if (data.compacted != null) setCompacted(data.compacted);
        if (data.context_breakdown != null) setContextBreakdown(data.context_breakdown);
        // Mark streaming as completed — push final turn's thinking, freeze timer
        updateStreamingForSession(sessionId, (prev) => {
          if (!prev) return prev;
          const durationSec = prev.thinkingStartTime
            ? Math.round((Date.now() - prev.thinkingStartTime) / 1000)
            : null;
          let newItems = prev.items;
          if (prev.thinking) {
            newItems = [...newItems, { type: "thinking" as const, id: `thinking-${newItems.length}`, data: { content: prev.thinking, durationSec } }];
          }
          if (prev.text) {
            newItems = [...newItems, { type: "text" as const, id: `text-${newItems.length}`, data: { content: prev.text } }];
          }
          return {
            ...prev,
            thinking: "",
            text: "",
            items: newItems,
            completed: true,
            thinkingEndTime: prev.thinkingEndTime || Date.now(),
          };
        });
        // Stop the SSE connection for this session
        stopStreaming(sessionId);
        // Remove the run entry and update spinner state
        runEntriesRef.current.delete(sessionId);
        setRunningSessionIds(new Set(runEntriesRef.current.keys()));
        // Clear elicitation if this session had one
        if (activeSessionRef.current === sessionId) {
          setActiveElicitation(null);
        }
        // Reload messages from the API so the response becomes a proper
        // MessageRow (with hover/copy/cost) instead of staying as a
        // StreamingMessage block. Also clears the streaming UI.
        if (activeSessionRef.current === sessionId && agentId) {
          api.getSessionMessages(agentId, sessionId).then((msgs) => {
            const mappedMessages = msgs.map((m: Message) => ({
              id: m.id,
              role: m.role,
              content: m.content,
              created_at: m.created_at,
              run_id: m.run_id,
              run_status: m.run_status,
              tokens_in: m.tokens_in,
              tokens_out: m.tokens_out,
              cost: m.cost,
              subagent_id: m.subagent_id,
              attachments: m.attachments,
            }));

            // A top-level run failure can happen before the pipeline stores
            // an assistant message. Keep that failure visible instead of
            // clearing the stream and leaving the conversation blank.
            if (
              data.status === "failed" &&
              data.error &&
              !mappedMessages.some((m) => m.run_id === data.run_id && m.role === "assistant")
            ) {
              mappedMessages.push({
                id: `failed-${sessionId}-${Date.now()}`,
                role: "assistant",
                content: "I couldn't complete this run because an internal error occurred. Please try again.",
                created_at: new Date().toISOString(),
                run_id: data.run_id || `failed-${sessionId}`,
                run_status: "failed",
                tokens_in: undefined,
                tokens_out: undefined,
                cost: undefined,
                subagent_id: undefined,
                attachments: null,
              });
            }

            setMessages(mappedMessages);
            setStreaming(null);
            streamingRef.current = null;
            setIsStreaming(false);
          }).catch(() => {});
        }
        loadSessions();
        break;
    }
  };

  // Stream events from a run, with reconnect + abort support.
  // Only ONE session is actively streamed at a time (the one the user is
  // viewing). When switching away, the abort controller closes the SSE
  // connection. When switching back, streamRun reconnects with Last-Event-ID.
  const streamRun = async (
    agentId: string,
    runId: string,
    sessionId: string,
    fromSeq = 0,
    signal?: AbortSignal,
  ) => {
    let lastEventId = fromSeq;
    try {
      for await (const { event, data, id } of api.streamRunEvents(agentId, runId, lastEventId, signal)) {
        if (id > lastEventId) lastEventId = id;
        const entry = runEntriesRef.current.get(sessionId);
        if (entry) entry.lastEventId = lastEventId;
        handleEvent(event, data, sessionId);
      }
    } catch (err: any) {
      // Aborted (user switched away) — just stop, don't reconnect
      if (err?.name === "AbortError") return;

      // Stream disconnected unexpectedly — reconnect if the run is still active
      // AND the user is still viewing this session
      const entry = runEntriesRef.current.get(sessionId);
      if (entry?.runId === runId && activeSessionRef.current === sessionId) {
        entry.lastEventId = lastEventId;
        await new Promise((r) => setTimeout(r, 1000));
        if (runEntriesRef.current.get(sessionId)?.runId === runId && activeSessionRef.current === sessionId) {
          try {
            const status = await api.getRunStatus(agentId, runId);
            if (status.status === "running" || status.status === "awaiting_approval") {
              // Create a new abort controller for the reconnection
              const newController = new AbortController();
              entry.abortController = newController;
              await streamRun(agentId, runId, sessionId, lastEventId, newController.signal);
            }
          } catch {
            if (activeSessionRef.current === sessionId) {
              setStreaming(null);
              setIsStreaming(false);
            }
            runEntriesRef.current.delete(sessionId);
          }
        }
      }
    }
  };

  // Start streaming for a session (creates abort controller)
  const startStreaming = (sessionId: string) => {
    const entry = runEntriesRef.current.get(sessionId);
    if (!entry || !agentId) return;
    if (entry.abortController) return;  // already streaming
    const controller = new AbortController();
    entry.abortController = controller;
    streamRun(agentId, entry.runId, sessionId, entry.lastEventId, controller.signal).catch(() => {
      if (activeSessionRef.current === sessionId) {
        setStreaming(null);
        streamingRef.current = null;
        setIsStreaming(false);
      }
    });
  };

  // Stop streaming for a session (aborts the SSE connection)
  const stopStreaming = (sessionId: string) => {
    const entry = runEntriesRef.current.get(sessionId);
    if (!entry?.abortController) return;
    entry.abortController.abort();
    entry.abortController = null;
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
    // Stop streaming the current session (close its SSE connection)
    if (activeSessionRef.current) stopStreaming(activeSessionRef.current);
    // Just deselect — the empty state IS the new chat view.
    // A session is created automatically when the first message is sent.
    // NOTE: do NOT clear runEntriesRef here — a run may still be active
    // in the previous session. The spinner stays so the user can see it,
    // and the streaming state survives for when they switch back.
    activeSessionRef.current = null;
    setActiveSessionId(null);
    setMessages([]);
    setStreaming(null);
    setIsStreaming(false);
    setActiveElicitation(null);
  };

  const handleSelectSession = (id: string) => {
    // Save completed streaming text before switching (only for the session we're leaving)
    const leavingSessionId = activeSessionRef.current;
    const leavingEntry = leavingSessionId ? runEntriesRef.current.get(leavingSessionId) : null;
    if (leavingEntry?.streaming?.completed && leavingEntry.streaming.text) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: leavingEntry.streaming!.text,
          created_at: new Date().toISOString(),
        },
      ]);
    }

    // Stop streaming the old session (close its SSE connection)
    if (leavingSessionId) stopStreaming(leavingSessionId);

    // Update the ref immediately so SSE events route to the right session
    activeSessionRef.current = id;

    // Clear messages immediately so the old session's messages don't
    // bleed into the new session's view (the useEffect will fetch the
    // new session's messages and populate them).
    setMessages([]);

    // If switching to a session that has an active run, restore its streaming state
    const entry = runEntriesRef.current.get(id);
    if (entry?.streaming) {
      setStreaming(entry.streaming);
      setIsStreaming(!entry.streaming.completed);
      streamingRef.current = entry.streaming;
      // Reconnect the SSE stream for this session (resumes from lastEventId)
      if (!entry.streaming.completed) {
        startStreaming(id);
      }
    } else {
      // Switching to a session with no active run — hide streaming UI
      setStreaming(null);
      setIsStreaming(false);
      streamingRef.current = null;
    }
    // Restore the elicitation for this session (if any)
    setActiveElicitation(entry?.elicitation || null);
    setActiveSessionId(id);
    // Reset context bar when switching sessions
    setContextTokens(undefined);
    setCachedTokens(undefined);
    setMaxContextTokens(undefined);
    setCompacted(false);
    setContextBreakdown(undefined);
  };

  const handleStop = async () => {
    if (!agentId || !activeSessionId) return;
    const entry = runEntriesRef.current.get(activeSessionId);
    if (!entry) return;
    stopStreaming(activeSessionId);
    try {
      await api.stopRun(agentId, entry.runId);
    } catch {}
    runEntriesRef.current.delete(activeSessionId);
    setStreaming(null);
    streamingRef.current = null;
    setIsStreaming(false);
    setRunningSessionIds(new Set(runEntriesRef.current.keys()));
    // Reload messages so the partial response becomes persistent
    if (agentId && activeSessionId) {
      api.getSessionMessages(agentId, activeSessionId).then((msgs) => {
        setMessages(
          msgs.map((m: Message) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            created_at: m.created_at,
            run_id: m.run_id,
            run_status: m.run_status,
            tokens_in: m.tokens_in,
            tokens_out: m.tokens_out,
            cost: m.cost,
            subagent_id: m.subagent_id,
            attachments: m.attachments,
          })),
        );
      }).catch(() => {});
    }
  };

  const handleDeleteSession = async (id: string) => {
    if (!agentId) return;
    try {
      // If this session has an active run, stop it first
      const entry = runEntriesRef.current.get(id);
      if (entry) {
        stopStreaming(id);
        try {
          await api.stopRun(agentId, entry.runId);
        } catch {}
        runEntriesRef.current.delete(id);
        if (activeSessionId === id) {
          setStreaming(null);
          setIsStreaming(false);
        }
        setRunningSessionIds(new Set(runEntriesRef.current.keys()));
      }
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
    // Clear from the run entry too
    if (activeSessionRef.current) {
      const entry = runEntriesRef.current.get(activeSessionRef.current);
      if (entry) entry.elicitation = null;
    }

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
    modelOverride: { provider_id: string; name: string; thinking_enabled?: boolean | null; thinking_effort?: string | null } | null,
    _context: ContextItem[],
    attachments?: { type: string; mimeType: string; data: string; filename: string }[],
    skill?: string,
  ) => {
    if (!agentId) return;

    // Handle /compact slash command — trigger manual compaction
    if (text.trim() === "/compact") {
      if (activeSessionId) {
        handleCompact();
      }
      return;
    }

    // Don't create a session upfront — let the backend auto-resume or create one.
    // The response will contain the session_id, which we set below.
    const sessionId = activeSessionId;

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
        attachments: attachments && attachments.length > 0
          ? JSON.stringify(attachments.map((a) => ({ type: a.type, mime_type: a.mimeType, filename: a.filename })))
          : null,
      },
    ]);

    setInputWarnings([]);
    setActiveElicitation(null);
    const newStreaming: StreamingResponse = {
      thinking: "",
      items: [],
      text: "",
      toolCalls: new Map(),
      thinkingStartTime: Date.now(),
      thinkingEndTime: null,
      turnCosts: [],
      guardrailWarnings: [],
      completed: false,
      subagents: new Map(),
    };
    setStreaming(newStreaming);
    streamingRef.current = newStreaming;
    setIsStreaming(true);
    autoScrollRef.current = true;

    // Step 1: POST /message to start the run
    try {
      const result = await api.sendMessage(
        agentId,
        text,
        false, // never use demo mode from the UI — real model only
        modelOverride || undefined,
        sessionId || undefined,
        attachments?.map((a) => ({
          type: a.type,
          mime_type: a.mimeType,
          data: a.data,
          filename: a.filename,
        })),
        !sessionId, // new_session=true when no active session (don't auto-resume old ones)
        skill,
      );

      const runSessionId = result.session_id || sessionId || "";

      // Set the session ID from the response (backend auto-resumed or created one)
      if (result.session_id && result.session_id !== activeSessionId) {
        activeSessionRef.current = result.session_id;
        setActiveSessionId(result.session_id);
        loadSessions();
      }

      // Register this run in the multi-run map
      runEntriesRef.current.set(runSessionId, {
        runId: result.run_id,
        sessionId: runSessionId,
        lastEventId: 0,
        streaming: newStreaming,
        elicitation: null,
        abortController: null,
      });
      setRunningSessionIds(new Set([...runningSessionIds, runSessionId]));

      // Step 2: Start streaming events for this session.
      // Only the currently-viewed session is actively streamed.
      startStreaming(runSessionId);
    } catch {
      setStreaming(null);
      streamingRef.current = null;
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

  // --- Full-view drag-and-drop for files ---
  const handleViewDragEnter = (e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    dragCounterRef.current++;
    setIsDraggingFile(true);
  };
  const handleViewDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounterRef.current--;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setIsDraggingFile(false);
    }
  };
  const handleViewDragOver = (e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
  };
  const handleViewDrop = async (e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    dragCounterRef.current = 0;
    setIsDraggingFile(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0 && inputBarRef.current) {
      inputBarRef.current.addFiles(files);
    }
  };

  const handleCompact = async () => {
    if (!agentId || !activeSessionId) return;
    setCompacting(true);
    try {
      const result = await api.compactSession(agentId, activeSessionId);
      setContextTokens(result.compacted_tokens);
      setMaxContextTokens(result.max_context_tokens);
      setCompacted(result.compacted);
    } catch (e) {
      console.error("Compact failed:", e);
    } finally {
      setCompacting(false);
    }
  };

  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: "var(--surface)" }}
      onDragEnter={handleViewDragEnter}
      onDragLeave={handleViewDragLeave}
      onDragOver={handleViewDragOver}
      onDrop={handleViewDrop}
    >
      {/* Sidebar */}
      <ChatSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        runningSessionIds={runningSessionIds}
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

            {(() => {
              // Group consecutive thinking + tool_call messages into ProcessSteps
              const filtered = messages.filter((msg) => !msg.subagent_id);
              const rendered: React.ReactNode[] = [];
              let processGroup: { msg: ChatMessage; index: number }[] = [];
              let groupRunId: string | undefined;

              const flushGroup = () => {
                if (processGroup.length === 0) return;
                const steps = processGroup.map((g) => ({
                  type: g.msg.role as "thinking" | "tool_call",
                  content: g.msg.content,
                }));
                // Find sub-agent messages for the run
                const subagentMsgs = groupRunId
                  ? messages.filter((m) => m.subagent_id && m.run_id === groupRunId)
                  : [];
                rendered.push(
                  <ProcessSteps
                    key={`process-${processGroup[0].index}`}
                    steps={steps}
                    subagentMessages={subagentMsgs}
                  />
                );
                processGroup = [];
                groupRunId = undefined;
              };

              filtered.forEach((msg, i) => {
                if (msg.role === "thinking" || msg.role === "tool_call") {
                  // Start or continue a process group
                  if (processGroup.length === 0) {
                    groupRunId = msg.run_id;
                  }
                  processGroup.push({ msg, index: i });
                } else {
                  // Flush any pending process group
                  flushGroup();

                  // Find sub-agent messages for run_subagent tool calls
                  let subagentMessages: ChatMessage[] | undefined;
                  if (msg.role === "tool_call") {
                    try {
                      const tcData = JSON.parse(msg.content) as ToolCallData;
                      if (tcData.capability === "run_subagent") {
                        subagentMessages = messages.filter(
                          (m) => m.subagent_id && m.run_id === msg.run_id
                        );
                      }
                    } catch { /* ignore */ }
                  }
                  rendered.push(
                    <MessageRow
                      key={msg.id}
                      message={msg}
                      isLastInRun={
                        i === filtered.length - 1 ||
                        filtered[i + 1].run_id !== msg.run_id
                      }
                      subagentMessages={subagentMessages}
                    />
                  );
                }
              });
              // Flush any remaining process group
              flushGroup();
              return rendered;
            })()}

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

            {/* Compacting indicator */}
            {compacting && (
              <div className="flex items-center justify-center gap-2 py-4">
                <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--accent)" }} />
                <span className="text-[13px] text-[var(--ink-2)]">Compacting conversation…</span>
              </div>
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

        {/* No provider / no model configured banner */}
        {agent && !hasModelSelected && (
          (() => {
            const noProviders = providers.length === 0;
            const noModel = !agent.provider_id || !agent.model;
            if (!noProviders && !noModel) return null;
            return (
              <div
                className="flex items-center justify-between gap-3 px-4 py-3"
                style={{
                  background: "var(--sidebar)",
                  borderTop: "1px solid var(--border)",
                }}
              >
                <div className="flex items-center gap-2 text-[13px] text-[var(--ink-2)]">
                  <AlertCircle className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                  <span>
                    {noProviders
                      ? "No provider configured. Add a provider in Settings to start chatting."
                      : "No model configured. Assign a model to this agent to start chatting."}
                  </span>
                </div>
                <button
                  onClick={() =>
                    noProviders ? navigate("/settings") : setSettingsOpen(true)
                  }
                  className="shrink-0 rounded-md px-3 py-1.5 text-[12px] font-medium"
                  style={{
                    background: "var(--accent)",
                    color: "var(--white)",
                  }}
                >
                  {noProviders ? "Add Provider" : "Configure"}
                </button>
              </div>
            );
          })()
        )}

        {/* Input bar */}
        <ChatInputBar
          ref={inputBarRef}
          defaultProviderId={agent?.provider_id || null}
          defaultModelName={agent?.model || null}
          defaultThinkingEnabled={agent?.thinking_enabled ?? null}
          defaultThinkingEffort={agent?.thinking_effort ?? null}
          disabled={
            (isStreaming && !activeElicitation) ||
            compacting
          }
          onModelChange={setHasModelSelected}
          onSend={handleSend}
          onStop={handleStop}
          activeElicitation={activeElicitation}
          onElicitationRespond={handleElicitationRespond}
          contextTokens={contextTokens}
          cachedTokens={cachedTokens}
          maxContextTokens={maxContextTokens}
          compacted={compacted}
          contextBreakdown={contextBreakdown}
          onCompact={handleCompact}
        />
      </div>

      {/* Full-view drag-and-drop overlay */}
      {isDraggingFile && (
        <div
          className="pointer-events-none fixed inset-0 z-[100] flex items-center justify-center"
          style={{ background: "rgba(0, 0, 0, 0.08)" }}
        >
          <div
            className="flex flex-col items-center gap-3 rounded-xl px-8 py-6"
            style={{
              background: "var(--surface)",
              border: "2px dashed var(--accent)",
              boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
            }}
          >
            <Paperclip className="h-8 w-8" style={{ color: "var(--accent)" }} />
            <span className="text-[16px] font-semibold" style={{ color: "var(--ink)" }}>
              Drop files to attach
            </span>
            <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
              Images, PDFs, documents — anywhere in the chat
            </span>
          </div>
        </div>
      )}

      {/* Settings overlay */}
      <SettingsOverlay
        agent={agent}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={() => reloadAgent()}
        providers={providers}
      />
    </div>
  );
}

function StreamingMessage({ streaming }: { streaming: StreamingResponse }) {
  const hasContent = streaming.text || streaming.items.length > 0;
  const endTime = streaming.thinkingEndTime ?? Date.now();
  const currentThinkingDuration = streaming.thinkingStartTime
    ? Math.round((endTime - streaming.thinkingStartTime) / 1000)
    : undefined;
  const isThinkingStreaming = !!streaming.thinking && !streaming.text && !streaming.completed;

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
              <Markdown>{item.data.content}</Markdown>
            </div>
          );
        }
        return <ToolCallBlock
          key={item.id}
          call={item.data}
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
          <Markdown>{streaming.text}</Markdown>
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

function MessageRow({ message, isLastInRun, subagentMessages }: { message: ChatMessage; isLastInRun?: boolean; subagentMessages?: ChatMessage[] }) {
  if (message.role === "user") {
    // Parse attachment metadata (JSON string from the API)
    let attachmentFiles: { type: string; mime_type: string; filename: string }[] = [];
    if (message.attachments) {
      try {
        const parsed = JSON.parse(message.attachments);
        if (Array.isArray(parsed)) {
          attachmentFiles = parsed.filter((a: any) => a.filename);
        }
      } catch { /* ignore */ }
    }

    return (
      <div className="mb-6 flex flex-col items-end gap-1.5">
        {attachmentFiles.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1.5">
            {attachmentFiles.map((f, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px]"
                style={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  color: "var(--ink-2)",
                }}
              >
                <FileIcon className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--ink-3)" }} />
                <span className="font-medium">{f.filename}</span>
                <span className="text-[10px]" style={{ color: "var(--ink-3)" }}>
                  {f.mime_type.split("/")[1]?.toUpperCase() || f.type}
                </span>
              </div>
            ))}
          </div>
        )}
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
          <ToolCallBlock call={data} subagentStream={subagentStream} />
        </div>
      );
    } catch {
      return null;
    }
  }

  if (message.role === "heartbeat") {
    const ts = message.created_at ? new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
    return (
      <div className="mb-6">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="font-mono text-[11px] font-medium" style={{ color: "#7C3AED" }}>♢ heartbeat</span>
          {ts && (
            <span className="font-mono text-[10px]" style={{ color: "var(--ink-3)" }}>· {ts}</span>
          )}
        </div>
        <div
          className="border-l-[3px] pl-4 text-[14px] leading-[1.65]"
          style={{ borderColor: "#7C3AED" }}
        >
          <Markdown>{message.content}</Markdown>
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
        <Markdown>{message.content}</Markdown>
      </div>
      {hasCost && (
        <div className="mt-1.5 font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
          {message.tokens_out || 0} tokens · ${(message.cost || 0).toFixed(3)}
        </div>
      )}
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
