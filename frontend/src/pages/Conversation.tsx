import { useEffect, useLayoutEffect, useMemo, useRef, useState, useCallback } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowDown, PanelLeft, PanelRight, Plus, Search, Globe, FileText, CalendarClock, Sparkles, AlertCircle, BookOpen, ChevronDown, Paperclip, Loader2, MessageSquare } from "lucide-react";
import { api, workspaceBackend, type PreviewSource } from "@/lib/api";
import type { Agent, Citation, Message, Provider, SessionInfo } from "@/lib/types";
import { WorkspacePanel } from "@/components/WorkspacePanel";
import { type SelectedModel } from "@/components/ModelPicker";
import { useObjectUrl } from "@/components/previews/useObjectUrl";
import { AttachmentCard } from "@/components/AttachmentCard";
import { ToolCallBlock, FileChips, collectFileRefs, type ToolCallData, type SubAgentStreamData, type FileRef } from "@/components/ToolCallBlock";
import { Markdown } from "@/components/Markdown";
import { ThinkingBlock } from "@/components/ThinkingBlock";
import { ProcessSteps } from "@/components/ProcessSteps";
import { ChatSidebar } from "@/components/ChatSidebar";
import { StatusWord } from "@/components/ui/status-word";
import { ChatInputBar, type Attachment, type ChatInputBarHandle, type ContextItem } from "@/components/ChatInputBar";
import { SettingsOverlay } from "@/components/SettingsOverlay";
import { useDesktopFileDrop } from "@/lib/desktopFileDrop";
import {
  markReadForFocusedEntities,
  refreshNotifications,
} from "@/lib/notificationStore";
import {
  onSessionActivity,
  primeLearning,
  startSessionActivity,
  stopSessionActivity,
  useLearningSessions,
} from "@/lib/sessionActivity";
import { setFocusedEntities } from "@/lib/focusRegistry";
import { useResizableWidth } from "@/lib/useResizableWidth";

interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  run_id?: string;
  run_status?: string;
  trigger?: string;
  is_test?: boolean;
  tokens_in?: number;
  tokens_out?: number;
  cost?: number;
  subagent_id?: string | null;
  attachments?: string | null;
  citations?: Message["citations"];
}

const mapApiMessage = (m: Message): ChatMessage => ({
  id: m.id,
  role: m.role,
  content: m.content,
  created_at: m.created_at,
  run_id: m.run_id,
  run_status: m.run_status,
  trigger: m.trigger,
  is_test: m.is_test,
  tokens_in: m.tokens_in,
  tokens_out: m.tokens_out,
  cost: m.cost,
  subagent_id: m.subagent_id,
  attachments: m.attachments,
  citations: m.citations,
});

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
  awaitingModel: boolean;    // a model call is dispatched, nothing streamed back yet — the between-turns gap
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

function createStreamingResponse(): StreamingResponse {
  return {
    thinking: "",
    items: [],
    text: "",
    awaitingModel: false,
    toolCalls: new Map(),
    thinkingStartTime: Date.now(),
    thinkingEndTime: null,
    turnCosts: [],
    guardrailWarnings: [],
    completed: false,
    subagents: new Map(),
  };
}

export function Conversation() {
  const { id: agentId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

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
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [yoloMode, setYoloMode] = useState(false);
  const [contextBreakdown, setContextBreakdown] = useState<{ system_prompt: number; conversation: number; tools: number } | undefined>(undefined);
  const [hasModelSelected, setHasModelSelected] = useState(false);
  const [previewSource, setPreviewSource] = useState<PreviewSource | null>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [composerModel, setComposerModel] = useState<SelectedModel | null>(null);
  const {
    width: previewWidth,
    dragging: previewDragging,
    startResize: startPreviewResize,
  } = useResizableWidth({ initial: 420, min: 300, max: 960, storageKey: "caberos.preview.width" });

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const activeSessionRef = useRef<string | null>(null);
  const streamingRef = useRef<StreamingResponse | null>(null);
  const inputBarRef = useRef<ChatInputBarHandle>(null);
  const dragCounterRef = useRef(0);
  // History pagination — oldest message id returned by the API plus re-entry
  // guards. Scroll-top loads prepend older pages; anchorRef keeps the
  // viewport pinned to the same spot while they land.
  const oldestFetchedIdRef = useRef<string | null>(null);
  const loadingOlderRef = useRef(false);
  const anchorRef = useRef<{ height: number; top: number } | null>(null);

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
    task?: { done: boolean };  // marker for channel-run polling (not a real task)
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
    api.listSessions(agentId)
      .then((list) => {
        setSessions(list);
        primeLearning(list.filter((s) => s.learning).map((s) => s.id));
      })
      .catch(() => {});
  }, [agentId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Session-close learning is background work — subscribe to the per-agent
  // activity stream so the UI can show it in progress, then refresh the
  // session list when an attempt resolves (status flips to closed/open).
  const learningSessions = useLearningSessions();
  useEffect(() => {
    if (!agentId) return;
    startSessionActivity(agentId);
    return () => stopSessionActivity();
  }, [agentId]);
  useEffect(() => onSessionActivity(() => loadSessions()), [loadSessions]);

  // Deep-link: ?session=<id> selects that session (e.g. from a notification)
  useEffect(() => {
    const wanted = searchParams.get("session");
    if (wanted && sessions.some((s) => s.id === wanted)) {
      setActiveSessionId(wanted);
    }
  }, [searchParams, sessions]);

  // Deep-link: ?prompt=<text> prefills the composer (e.g. starter ideas from
  // onboarding). Fires once per prompt value, then clears itself from the URL.
  const [appliedPrompt, setAppliedPrompt] = useState<string | null>(null);
  useEffect(() => {
    const prompt = searchParams.get("prompt");
    if (prompt && prompt !== appliedPrompt) {
      setAppliedPrompt(prompt);
      inputBarRef.current?.prefill(prompt);
    }
  }, [searchParams, appliedPrompt]);

  // YOLO mode banner — global flag fetched once; the per-agent flag lives on
  // `agent` and is kept live by the CustomEvent from SettingsOverlay's toggle.
  useEffect(() => {
    api.getYoloMode().then((r) => setYoloMode(r.yolo_mode)).catch(() => {});
    const onYolo = (e: Event) => {
      const d = (e as CustomEvent<{ agentId: string; enabled: boolean }>).detail;
      setAgent((prev) =>
        prev && prev.id === d.agentId ? { ...prev, yolo_mode: d.enabled } : prev,
      );
    };
    window.addEventListener("caberos:yolo-mode", onYolo);
    return () => window.removeEventListener("caberos:yolo-mode", onYolo);
  }, []);

  // Composer YOLO toggle — same write path as SettingsOverlay: optimistic
  // per-agent flag, revert on failure, CustomEvent so other surfaces sync.
  const toggleYolo = async () => {
    if (!agent || yoloMode) return; // global override can't be undone per-agent
    const next = !agent.yolo_mode;
    setAgent((prev) => (prev ? { ...prev, yolo_mode: next } : prev));
    try {
      await api.updateAgent(agent.id, { yolo_mode: next });
      window.dispatchEvent(
        new CustomEvent("caberos:yolo-mode", {
          detail: { agentId: agent.id, enabled: next },
        }),
      );
    } catch {
      setAgent((prev) => (prev ? { ...prev, yolo_mode: !next } : prev));
    }
  };

  // W9 — declare what the operator is looking at so matching notifications
  // suppress their pings (inbox still records, auto-read).
  useEffect(() => {
    const keys: string[] = [];
    if (agentId) keys.push(`agent:${agentId}`);
    if (activeSessionId) keys.push(`session:${activeSessionId}`);
    setFocusedEntities(keys);
    // Retro-read: notifications that landed while the window was unfocused
    // stay unread even though the operator is now looking at the entity.
    markReadForFocusedEntities(keys);
    return () => setFocusedEntities([]);
  }, [agentId, activeSessionId]);

  useEffect(() => {
    if (!agentId || !activeSessionId) {
      setMessages([]);
      setHasMoreHistory(false);
      oldestFetchedIdRef.current = null;
      return;
    }
    api
      .getSessionMessages(agentId, activeSessionId)
      .then((res) => {
        oldestFetchedIdRef.current = res.messages[0]?.id ?? null;
        setHasMoreHistory(res.has_more);
        let mapped = res.messages.map(mapApiMessage);
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
          // The pipeline persists attachment metadata after the message row —
          // a reload in that window returns the user message with
          // attachments=null. Carry the optimistic copy's attachments forward
          // so the card doesn't flash out mid-run and return on completion.
          // Only the latest user message can be the in-flight one — patching
          // older same-text twins would mislabel them.
          const lastUserIdx = mapped.map((m, i) => (m.role === "user" ? i : -1)).filter((i) => i >= 0).pop();
          const carried = mapped.map((m, i) => {
            if (i !== lastUserIdx || m.attachments) return m;
            const twin = prev.find(
              (o) => o.role === "user" && o.content === m.content && o.attachments,
            );
            return twin ? { ...m, attachments: twin.attachments } : m;
          });
          return [...carried, ...optimistic];
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
              approval_batch_id: data.approval_batch_id,
              approval_batch_size: data.approval_batch_size,
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
        // A new turn's model call was dispatched — the gap between turns.
        updateStreamingForSession(sessionId, (prev) =>
          prev ? { ...prev, awaitingModel: true } : prev,
        );
        break;

      case "thinking":
        updateStreamingForSession(sessionId, (prev) =>
          prev ? { ...prev, thinking: prev.thinking + data.content, awaitingModel: false } : prev,
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
          return { ...prev, items, thinking, text: prev.text + data.content, awaitingModel: false };
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
        // An elicitation_required notification was just persisted — refetch
        // now (small delay for the commit) so the toast is instant.
        refreshNotifications(400);
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
          // Now waiting on the operator, not the model.
          return { ...prev, toolCalls: newToolCalls, awaitingModel: false };
        });
        break;

      case "tool_call":
        // An approval-gated tool call persists an approval_required
        // notification — refetch now so the toast is instant.
        if (data.approval_id || data.approval_batch_id) refreshNotifications(400);
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
            approval_batch_id: data.approval_batch_id,
            approval_batch_size: data.approval_batch_size,
            elicitation_id: existing?.elicitation_id,
          };
          newToolCalls.set(data.id, toolData);
          // Add to items list if not already there
          const exists = items.some(i => i.type === "tool" && i.id === data.id);
          const newItems = exists
            ? items.map(i => i.type === "tool" && i.id === data.id ? { ...i, data: toolData } : i)
            : [...items, { type: "tool" as const, id: data.id, data: toolData }];
          return { ...prev, toolCalls: newToolCalls, items: newItems, thinking, text, awaitingModel: false };
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
            // Turn boundary → next turn's model call starts here (or
            // message_complete clears this for the final turn).
            awaitingModel: true,
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
        // The run just finished — a run_completed/failed notification was
        // persisted. Refetch now so the toast is instant instead of waiting
        // for the next poll tick.
        refreshNotifications(400);
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
            awaitingModel: false,
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
          api.getSessionMessages(agentId, sessionId).then((res) => {
            oldestFetchedIdRef.current = res.messages[0]?.id ?? null;
            setHasMoreHistory(res.has_more);
            const mappedMessages = res.messages.map(mapApiMessage);

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
                trigger: undefined,
                is_test: undefined,
                tokens_in: undefined,
                tokens_out: undefined,
                cost: undefined,
                subagent_id: undefined,
                attachments: null,
                citations: undefined,
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

  const handleEventRef = useRef(handleEvent);
  handleEventRef.current = handleEvent;

  // Poll for new runs on channel sessions (Zalo, Telegram, etc.) and
  // stream them live in the dashboard. Dashboard sessions don't need this
  // because the user initiates the run and subscribes directly.
  useEffect(() => {
    if (!agentId || !activeSessionId) return;
    const activeSession = sessions.find((s) => s.id === activeSessionId);
    if (!activeSession?.channel) return;

    // Don't poll if we're already streaming a run for this session
    const existingEntry = runEntriesRef.current.get(activeSessionId);
    if (existingEntry && !existingEntry.task?.done) return;

    let cancelled = false;
    let lastRunId: string | null = null;

    const poll = async () => {
      if (cancelled) return;
      try {
        const { messages: polled } = await api.getSessionMessages(agentId, activeSessionId);
        const latestRun = polled[polled.length - 1]?.run_id;
        if (!latestRun || latestRun === lastRunId) return;

        const status = await api.getRunStatus(agentId, latestRun);
        if (!status || cancelled) return;

        if (status.status === "running" || status.status === "awaiting_approval") {
          lastRunId = latestRun;
          const runSessionId = activeSessionId;
          const newStreaming = createStreamingResponse();
          runEntriesRef.current.set(runSessionId, {
            runId: latestRun,
            sessionId: runSessionId,
            lastEventId: 0,
            streaming: newStreaming,
            elicitation: null,
            abortController: null,
            task: { done: false },
          });
          if (activeSessionRef.current === runSessionId) {
            setStreaming(newStreaming);
            streamingRef.current = newStreaming;
            setIsStreaming(true);
          }
          setRunningSessionIds((prev) => new Set([...prev, runSessionId]));

          const abortController = new AbortController();
          const entry = runEntriesRef.current.get(runSessionId);
          if (entry) entry.abortController = abortController;

          (async () => {
            try {
              for await (const { event, data, id } of api.streamRunEvents(
                agentId, latestRun, 0, abortController.signal,
              )) {
                if (cancelled) break;
                const e = runEntriesRef.current.get(runSessionId);
                if (e) e.lastEventId = id;
                handleEventRef.current(event, data, runSessionId);
              }
            } catch {
              // SSE disconnected — ok
            }
            if (!cancelled) {
              loadSessions();
              if (activeSessionRef.current === runSessionId) {
                setIsStreaming(false);
              }
              setRunningSessionIds((prev) => {
                const next = new Set(prev);
                next.delete(runSessionId);
                return next;
              });
              runEntriesRef.current.delete(runSessionId);
            }
          })();
        }
      } catch {
        // ignore polling errors
      }
    };

    poll();
    const interval = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [agentId, activeSessionId, sessions, loadSessions]);

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

  const streamRunRef = useRef(streamRun);
  streamRunRef.current = streamRun;

  // Start streaming for a session (creates abort controller)
  const startStreaming = useCallback((sessionId: string) => {
    const entry = runEntriesRef.current.get(sessionId);
    if (!entry || !agentId) return;
    if (entry.abortController) return;  // already streaming
    const controller = new AbortController();
    entry.abortController = controller;
    streamRunRef.current(agentId, entry.runId, sessionId, entry.lastEventId, controller.signal).catch(() => {
      if (activeSessionRef.current === sessionId) {
        setStreaming(null);
        streamingRef.current = null;
        setIsStreaming(false);
      }
    });
  }, [agentId]);

  useEffect(() => {
    if (!agentId) return;
    const recoverableSessions = sessions.filter(
      (session) =>
        session.active_run_id &&
        (session.active_run_status === "pending" ||
          session.active_run_status === "running" ||
          session.active_run_status === "awaiting_approval"),
    );
    if (recoverableSessions.length === 0) return;

    let cancelled = false;
    const restoreRuns = async () => {
      for (const session of recoverableSessions) {
        if (cancelled || !session.active_run_id || runEntriesRef.current.has(session.id)) {
          continue;
        }

        const status = await api.getRunStatus(agentId, session.active_run_id).catch(() => null);
        if (
          cancelled ||
          !status ||
          (status.status !== "running" && status.status !== "awaiting_approval")
        ) {
          continue;
        }

        const restoredStreaming = createStreamingResponse();
        runEntriesRef.current.set(session.id, {
          runId: session.active_run_id,
          sessionId: session.id,
          lastEventId: 0,
          streaming: restoredStreaming,
          elicitation: null,
          abortController: null,
        });

        if (!activeSessionRef.current) {
          activeSessionRef.current = session.id;
          setActiveSessionId(session.id);
        }
        if (activeSessionRef.current === session.id) {
          setStreaming(restoredStreaming);
          streamingRef.current = restoredStreaming;
          setIsStreaming(true);
        }
        setRunningSessionIds(new Set(runEntriesRef.current.keys()));
        startStreaming(session.id);
      }
    };

    void restoreRuns();
    return () => {
      cancelled = true;
    };
  }, [agentId, sessions, startStreaming]);

  // Stop streaming for a session (aborts the SSE connection)
  const stopStreaming = (sessionId: string) => {
    const entry = runEntriesRef.current.get(sessionId);
    if (!entry?.abortController) return;
    entry.abortController.abort();
    entry.abortController = null;
  };

  const loadOlderMessages = async () => {
    const sessionId = activeSessionRef.current;
    const oldestId = oldestFetchedIdRef.current;
    const container = scrollContainerRef.current;
    if (!agentId || !sessionId || !oldestId || !container) return;
    if (loadingOlderRef.current || !hasMoreHistory) return;
    loadingOlderRef.current = true;
    setLoadingOlder(true);
    try {
      const res = await api.getSessionMessages(agentId, sessionId, 50, oldestId);
      if (activeSessionRef.current !== sessionId) return;
      const older = res.messages.map(mapApiMessage);
      setHasMoreHistory(res.has_more);
      if (older.length > 0) {
        oldestFetchedIdRef.current = older[0].id;
        anchorRef.current = {
          height: container.scrollHeight,
          top: container.scrollTop,
        };
        setMessages((prev) => {
          const seen = new Set(prev.map((m) => m.id));
          return [...older.filter((m) => !seen.has(m.id)), ...prev];
        });
      }
    } catch {
      // Cursor can go stale after a reload — just stop paging for this view.
      setHasMoreHistory(false);
    } finally {
      loadingOlderRef.current = false;
      setLoadingOlder(false);
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
    if (container.scrollTop < 80) void loadOlderMessages();
  };

  // Restore scroll position after an older page prepends — keep the same
  // messages under the cursor instead of jumping to the top.
  useLayoutEffect(() => {
    const anchor = anchorRef.current;
    const container = scrollContainerRef.current;
    if (anchor && container) {
      container.scrollTop = container.scrollHeight - anchor.height + anchor.top;
      anchorRef.current = null;
    }
  }, [messages]);

  const prefersReducedMotion = useRef(
    typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );

  useEffect(() => {
    if (autoScrollRef.current) {
      messagesEndRef.current?.scrollIntoView({
        behavior: prefersReducedMotion.current ? "instant" : "smooth",
      });
    }
  }, [messages, streaming, isStreaming]);

  const handleJumpToLatest = () => {
    autoScrollRef.current = true;
    setShowJumpToLatest(false);
    messagesEndRef.current?.scrollIntoView({
      behavior: prefersReducedMotion.current ? "instant" : "smooth",
    });
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
    setHasMoreHistory(false);
    oldestFetchedIdRef.current = null;
    setStreaming(null);
    setIsStreaming(false);
    setActiveElicitation(null);
  };

  const handleSelectSession = (id: string) => {
    // Re-clicking the active session is a no-op — otherwise we'd clear
    // messages but React would bail on the identical setActiveSessionId and
    // never re-run the fetch effect, leaving an empty (new-chat) view.
    if (id === activeSessionRef.current) return;
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
    setHasMoreHistory(false);
    oldestFetchedIdRef.current = null;

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
      api.getSessionMessages(agentId, activeSessionId).then((res) => {
        oldestFetchedIdRef.current = res.messages[0]?.id ?? null;
        setHasMoreHistory(res.has_more);
        setMessages(res.messages.map(mapApiMessage));
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
        setHasMoreHistory(false);
        oldestFetchedIdRef.current = null;
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

  // --- File preview (W3) — shared right-side panel ---
  const openPreview = useCallback((source: PreviewSource) => {
    setPreviewSource(source);
    setWorkspaceOpen(true);
  }, []);

  const closeWorkspace = useCallback(() => {
    setWorkspaceOpen(false);
    setPreviewSource(null);
  }, []);

  // Workspace paths this session's runs produced — "changed in this
  // chat" markers in the workspace tree.
  const changedPaths = useMemo(() => {
    const s = new Set<string>();
    const add = (calls: ToolCallData[]) => {
      for (const ref of collectFileRefs(calls)) {
        if (ref.source.path) s.add(ref.source.path);
      }
    };
    for (const msg of messages) {
      if (msg.role !== "tool_call") continue;
      try {
        add([JSON.parse(msg.content) as ToolCallData]);
      } catch {
        /* malformed tool_call payload — skip */
      }
    }
    if (streaming) add([...streaming.toolCalls.values()]);
    return s;
  }, [messages, streaming]);

  const allCitations = useMemo(
    () =>
      messages.flatMap(
        (m) => (m as { citations?: Citation[] }).citations ?? [],
      ),
    [messages],
  );

  // Returns success so the composer can keep the draft + tray on failure.
  const handleSend = async (
    text: string,
    modelOverride: { provider_id: string; name: string; thinking_enabled?: boolean | null; thinking_effort?: string | null } | null,
    _context: ContextItem[],
    attachments?: Attachment[],
    skill?: string,
  ): Promise<boolean> => {
    if (!agentId) return false;

    // Don't allow sending messages from the dashboard into channel sessions
    // (Zalo, Telegram, etc.) — those are external conversations. The dashboard
    // view of a channel session is read-only.
    const activeSession = sessions.find((s) => s.id === activeSessionId);
    if (activeSession?.channel) {
      return false;
    }

    // Handle /compact slash command — trigger manual compaction
    if (text.trim() === "/compact") {
      if (activeSessionId) {
        handleCompact();
      }
      return true;
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

    const optimisticId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      {
        id: optimisticId,
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
        attachments: attachments && attachments.length > 0
          ? JSON.stringify(attachments.map((a) => ({
            type: a.type,
            mime_type: a.mimeType,
            filename: a.filename,
            size: a.size,
            // Ephemeral thumbnail — the composer's object URL is revoked on
            // send, so carry a self-owned data URL instead: image bytes are
            // already base64 for transport; PDF/Office drafts reuse the
            // backend-rendered thumb. Dropped once the persisted record
            // (with path) replaces this optimistic one.
            ...(a.type === "image" && a.data
              ? { preview_url: `data:${a.mimeType};base64,${a.data}` }
              : a.thumb ? { preview_url: a.thumb } : {}),
            ...(a.type === "url" ? { url: a.data } : {}),
          })))
          : null,
      },
    ]);

    setInputWarnings([]);
    setActiveElicitation(null);
    const newStreaming = createStreamingResponse();
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
      return true;
    } catch (err) {
      console.error("Failed to send message:", err);
      setStreaming(null);
      streamingRef.current = null;
      setIsStreaming(false);
      // Roll back the optimistic message — the run never started, and
      // the composer keeps the draft + attachments for a retry.
      setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
      return false;
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

  useDesktopFileDrop({
    onFiles: (files) => inputBarRef.current?.addFiles(files),
    onDraggingChange: setIsDraggingFile,
    onError: () => setInputWarnings(["The dropped file could not be read."]),
  });

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
      style={{ background: "var(--ground)" }}
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
        agentName={agent?.name}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onOpenSettings={() => setSettingsOpen(true)}
        onBackToAgents={() => navigate("/agents")}
        onCollapse={() => setSidebarCollapsed(true)}
      />

      {/* Collapsed icon rail — expand, new chat, search + session list. */}
      {sidebarCollapsed && (
        <div className="flex w-12 shrink-0 flex-col items-center gap-1.5 border-r border-line bg-ground py-3">
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-[9px] border border-line bg-surface text-ink-muted transition-colors hover:text-ink"
            title="Show sidebar"
            aria-label="Show sidebar"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          <button
            onClick={handleNewChat}
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-[9px] bg-ink text-surface transition-opacity hover:opacity-85"
            title="New chat"
            aria-label="New chat"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-[9px] border border-line bg-surface text-ink-muted transition-colors hover:text-ink"
            title="Search chats"
            aria-label="Search chats"
          >
            <Search className="h-4 w-4" />
          </button>
          <button
            onClick={() => setSidebarCollapsed(false)}
            className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-[9px] border border-line bg-surface text-ink-muted transition-colors hover:text-ink"
            title="Show chat list"
            aria-label="Show chat list"
          >
            <MessageSquare className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Main */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Header — agent tile + session title + run state */}
        <div className="flex items-center gap-3 border-b border-line bg-ground px-5 py-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-accent-tint text-[15px] font-semibold text-accent">
            {(agent?.name ?? agentId ?? "?").charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-[15px] font-semibold leading-[20px] text-ink">
                {headerTitle}
              </span>
              {isStreaming && <StatusWord status="running" />}
              {activeSessionId && learningSessions.has(activeSessionId) && (
                <span
                  className="flex shrink-0 items-center gap-1 text-[11px] text-accent"
                  title="Closing this session — summarizing and saving durable memory"
                >
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Learning
                </span>
              )}
            </div>
            <div className="flex items-center gap-1.5 truncate text-[12px] leading-[16px] text-ink-muted">
              <StatusWord status={isStreaming ? "running" : "idle"} />
              <span>·</span>
              <span className="truncate">Working in workspace</span>
            </div>
          </div>
          {sessionElapsed && (
            <span
              className="shrink-0 font-mono text-[12px] tabular-nums text-ink-faint"
              title="Session elapsed time"
            >
              {sessionElapsed}
            </span>
          )}
          {/* Model chip — reflects the composer's picker selection
              (mockup's header chip is a display, not a control). */}
          {(composerModel?.name || agent?.model) && (
            <span
              className="shrink-0 rounded-[8px] border border-line bg-surface px-2 py-1 font-mono text-[11px] text-ink-muted"
              title="Model — change it in the composer"
            >
              {composerModel?.name ?? agent?.model}
            </span>
          )}
          <button
            onClick={() =>
              workspaceOpen ? closeWorkspace() : setWorkspaceOpen(true)
            }
            className={`flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-[8px] border transition-colors ${
              workspaceOpen
                ? "border-accent/40 bg-accent-tint text-accent"
                : "border-line bg-surface text-ink-muted hover:text-ink"
            }`}
            title={workspaceOpen ? "Hide workspace" : "Show workspace"}
          >
            <PanelRight className="h-4 w-4" />
          </button>
        </div>

        {/* Messages */}
        <div className="relative flex min-h-0 flex-1 flex-col">
        {(yoloMode || agent?.yolo_mode) && (
          <div className="flex items-center justify-center gap-2 border-b border-[var(--danger)]/30 bg-[rgba(239,68,68,0.06)] px-4 py-1.5 text-[12px] font-medium text-[var(--danger)]">
            <AlertCircle className="h-3.5 w-3.5" />
            YOLO mode is on — tools run without approval
          </div>
        )}
        <div
          ref={scrollContainerRef}
          onScroll={handleScroll}
          className="relative flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-[672px] px-6 pb-[170px] pt-6">
            {loadingOlder && (
              <div className="flex items-center justify-center gap-2 pb-4 text-[12px] text-[var(--ink-2)]">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading earlier messages…
              </div>
            )}
            {messages.length === 0 && !isStreaming && (
              <div className="flex h-full flex-col items-center justify-center px-6 text-center">
                <span className="flex h-14 w-14 items-center justify-center rounded-[16px] bg-accent-tint text-[22px] font-semibold text-accent">
                  {(agent?.name ?? agentId ?? "?").charAt(0).toUpperCase()}
                </span>
                <h2 className="mt-3 text-[18px] font-semibold text-ink">
                  {agent?.name || agentId}
                </h2>
                <p className="mt-1.5 max-w-[420px] text-[13px] leading-[1.5] text-ink-muted">
                  {agent?.soul || "Start a conversation to begin."}
                </p>
                <button
                  onClick={() => setSettingsOpen(true)}
                  className="mt-2 cursor-pointer text-[12px] font-medium text-accent hover:underline"
                >
                  View full persona
                </button>
                <div className="mt-6 grid w-full max-w-[520px] grid-cols-2 gap-2 max-sm:grid-cols-1">
                  {(
                    [
                      {
                        icon: <Globe className="h-4 w-4" />,
                        label: "Research a topic on the web",
                        prompt:
                          "Research this topic on the web and summarize the key points: ",
                      },
                      {
                        icon: <FileText className="h-4 w-4" />,
                        label: "Read a file and summarize it",
                        prompt:
                          "Read this file from the workspace and summarize it: ",
                      },
                      {
                        icon: <CalendarClock className="h-4 w-4" />,
                        label: "Set up a daily brief",
                        prompt:
                          "Set up a daily brief — every morning, gather ",
                      },
                      {
                        icon: <Sparkles className="h-4 w-4" />,
                        label: "Draft a new skill",
                        prompt: "Help me draft a new skill that ",
                      },
                    ]
                  ).map((s) => (
                    <button
                      key={s.label}
                      onClick={() => inputBarRef.current?.prefill(s.prompt)}
                      className="flex cursor-pointer items-center gap-2.5 rounded-[12px] border border-line bg-surface px-3.5 py-3 text-left text-[13px] font-medium text-ink transition-colors hover:border-accent/40 hover:bg-accent-tint/40"
                    >
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] bg-sunken text-ink-muted">
                        {s.icon}
                      </span>
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {(() => {
              // Group consecutive thinking + tool_call messages into ProcessSteps
              const filtered = messages.filter((msg) => !msg.subagent_id);
              const rendered: React.ReactNode[] = [];
              let processGroup: { msg: ChatMessage; index: number }[] = [];
              let groupRunId: string | undefined;
              // Output files accumulate per run — chips render once, at the
              // END of the run (after the reply), not mid-run under the
              // collapsed steps.
              const runFiles = new Map<string, FileRef[]>();
              const mergeRefs = (runId: string, refs: FileRef[]) => {
                const acc = runFiles.get(runId) ?? [];
                for (const r of refs) {
                  const key = r.source.path ?? `a:${r.source.artifactId}`;
                  const idx = acc.findIndex(
                    (o) => (o.source.path ?? `a:${o.source.artifactId}`) === key
                  );
                  if (idx >= 0) acc[idx] = r;
                  else acc.push(r);
                }
                runFiles.set(runId, acc);
              };
              const emitRunChips = (runId: string | undefined) => {
                if (!runId) return;
                const refs = runFiles.get(runId);
                if (!refs?.length) return;
                runFiles.delete(runId);
                rendered.push(
                  <FileChips
                    key={`files-${runId}`}
                    refs={refs}
                    onPreview={openPreview}
                  />
                );
              };

              const flushGroup = (nextRunId?: string) => {
                if (processGroup.length === 0) return;
                const steps = processGroup.map((g) => ({
                  type: g.msg.role as "thinking" | "tool_call",
                  content: g.msg.content,
                }));
                // Find sub-agent messages for the run
                const subagentMsgs = groupRunId
                  ? messages.filter((m) => m.subagent_id && m.run_id === groupRunId)
                  : [];
                // Output files this step group produced — accumulated per run.
                const fileRefs = collectFileRefs(
                  processGroup
                    .filter((g) => g.msg.role === "tool_call")
                    .map((g) => {
                      try {
                        return JSON.parse(g.msg.content) as ToolCallData;
                      } catch {
                        return null;
                      }
                    })
                    .filter((c): c is ToolCallData => c !== null)
                );
                if (groupRunId && fileRefs.length > 0) {
                  mergeRefs(groupRunId, fileRefs);
                }
                rendered.push(
                  <ProcessSteps
                    key={`process-${processGroup[0].index}`}
                    steps={steps}
                    subagentMessages={subagentMsgs}
                    onPreview={openPreview}
                    agentInitial={(agent?.name ?? agentId ?? "?").charAt(0).toUpperCase()}
                  />
                );
                // Run ended on tool calls (no reply follows) — emit its
                // output chips right here, at the run boundary.
                if (groupRunId && nextRunId !== groupRunId) {
                  emitRunChips(groupRunId);
                }
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
                  flushGroup(msg.run_id);

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
                  const isLastInRun =
                    i === filtered.length - 1 ||
                    filtered[i + 1].run_id !== msg.run_id;
                  const runRefs =
                    isLastInRun && msg.run_id ? runFiles.get(msg.run_id) : undefined;
                  if (runRefs) runFiles.delete(msg.run_id!);
                  rendered.push(
                    <MessageRow
                      key={msg.id}
                      message={msg}
                      isLastInRun={isLastInRun}
                      subagentMessages={subagentMessages}
                      onPreview={openPreview}
                      agentId={agentId}
                      runFileRefs={msg.role === "assistant" ? runRefs : undefined}
                    />
                  );
                  // Non-assistant run tail — chips still land at the end.
                  if (isLastInRun && runRefs?.length && msg.role !== "assistant") {
                    rendered.push(
                      <FileChips
                        key={`files-${msg.run_id}`}
                        refs={runRefs}
                        onPreview={openPreview}
                      />
                    );
                  }
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
              <StreamingMessage streaming={streaming} onPreview={openPreview} />
            )}
            {isStreaming && !streaming && <TypingIndicator />}
            {/* Completed streaming block — keeps thinking/tool calls/costs visible after run ends */}
            {!isStreaming && streaming && streaming.completed && (
              <StreamingMessage streaming={streaming} onPreview={openPreview} />
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
        </div>

        {showJumpToLatest && (
          <button
            onClick={handleJumpToLatest}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                handleJumpToLatest();
              }
            }}
            className="absolute bottom-[170px] left-1/2 -translate-x-1/2 rounded-full px-3 py-1.5 text-[12px] font-medium shadow-lg transition-shadow focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
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

        {/* Disabled agent banner — the composer stays dead too (B39) */}
        {agent && agent.enabled === false && (
          <div
            className="flex items-center gap-2 px-4 py-3 text-[13px] text-[var(--ink-2)]"
            style={{
              background: "var(--surface)",
              borderTop: "1px solid var(--border)",
            }}
          >
            <AlertCircle className="h-4 w-4 shrink-0 text-[var(--ink-3)]" />
            <span>
              This agent is disabled — conversation history is read-only.
              Re-enable it in Agents to chat.
            </span>
          </div>
        )}

        {/* No provider / no model configured banner */}
        {agent && agent.enabled !== false && !hasModelSelected && (
          (() => {
            const noProviders = providers.length === 0;
            const noModel = !agent.provider_id || !agent.model;
            if (!noProviders && !noModel) return null;
            return (
              <div
                className="flex items-center justify-between gap-3 px-4 py-3"
                style={{
                  background: "var(--surface)",
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

        {/* Floating composer — overlaps the chat surface. One continuous
            gradient (transparent → ground at 48px → solid ground below)
            fades scrolled text into the page with no seam. Channel
            sessions render a read-only notice in the same slot. */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-[linear-gradient(to_bottom,transparent_0px,var(--ground)_48px)]">
          <div className="pointer-events-auto relative mt-12 px-4 pb-3">
        {(() => {
          const activeSession = sessions.find((s) => s.id === activeSessionId);
          if (activeSession?.channel) {
            const channelName = { telegram: "Telegram", zalo_bot: "Zalo", discord: "Discord", zalo_oa: "Zalo OA" }[activeSession.channel] || activeSession.channel;
            return (
              <div
                className="flex items-center justify-center gap-2 px-4 py-3 text-[13px] text-[var(--ink-3)]"
                style={{ borderTop: "1px solid var(--border)" }}
              >
                <MessageSquare className="h-4 w-4" />
                <span>
                  This is a {channelName} conversation — messages are received and replied to from {channelName}.
                </span>
              </div>
            );
          }
          return (
            <ChatInputBar
              ref={inputBarRef}
              agentId={agentId || ""}
              agentName={agent?.name}
              yoloMode={yoloMode || agent?.yolo_mode === true}
              yoloLocked={yoloMode}
              onToggleYolo={toggleYolo}
              model={composerModel}
              defaultProviderId={agent?.provider_id || null}
              defaultModelName={agent?.model || null}
              defaultThinkingEnabled={agent?.thinking_enabled ?? null}
              defaultThinkingEffort={agent?.thinking_effort ?? null}
              disabled={
                agent?.enabled === false ||
                (isStreaming && !activeElicitation) ||
                compacting
              }
              onModelChange={(m) => {
                setComposerModel(m);
                setHasModelSelected(Boolean(m));
              }}
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
          );
        })()}
          </div>
        </div>
      </div>

      {/* Workspace panel — Run | Workspace | Sources tabs over a file
          tree + shared preview (W13). Resizable; full-width overlay on
          narrow screens. */}
      {workspaceOpen && (
        <div
          className="relative shrink-0 max-md:fixed max-md:inset-0 max-md:z-40"
          style={{ width: `min(100%, ${previewWidth}px)` }}
        >
          <div
            onMouseDown={startPreviewResize}
            className={`absolute -left-1 top-0 z-10 h-full w-2 cursor-col-resize transition-colors hover:bg-[var(--accent)]/40 max-md:hidden ${previewDragging ? "bg-[var(--accent)]/40" : ""}`}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize workspace panel"
          />
          <WorkspacePanel
            agentId={agentId || ""}
            agentName={agent?.name ?? agentId ?? ""}
            sessionId={activeSessionId}
            selected={previewSource}
            onSelect={setPreviewSource}
            changedPaths={changedPaths}
            citations={allCitations}
            runStatus={
              sessions.find((s) => s.id === activeSessionId)
                ?.active_run_status ?? (isStreaming ? "running" : null)
            }
            onClose={closeWorkspace}
          />
        </div>
      )}

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

function StreamingMessage({
  streaming,
  onPreview,
}: {
  streaming: StreamingResponse;
  onPreview?: (source: PreviewSource) => void;
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
              <Markdown>{item.data.content}</Markdown>
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
          <Markdown>{streaming.text}</Markdown>
          {!streaming.completed && <span className="streaming-cursor" />}
        </div>
      )}

      {/* Between-turns affordance: a model call is in flight, nothing
          streamed back yet — otherwise the gap after a completed tool
          call reads as dead air. */}
      {streaming.awaitingModel && !streaming.completed && <TypingIndicator />}

      {/* Output files the run produced — at the end of the run, not buried
          inside collapsed tool-call steps. */}
      {fileRefs.length > 0 && <FileChips refs={fileRefs} onPreview={onPreview} />}

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

function MessageRow({
  message,
  isLastInRun,
  subagentMessages,
  onPreview,
  agentId,
  runFileRefs,
}: {
  message: ChatMessage;
  isLastInRun?: boolean;
  subagentMessages?: ChatMessage[];
  onPreview?: (source: PreviewSource) => void;
  agentId?: string;
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
              <MessageAttachmentCard key={i} file={f} agentId={agentId} onPreview={onPreview} />
            ))}
          </div>
        )}
        <div
          className="max-w-[75%] rounded-lg px-3.5 py-2.5 text-[14px] leading-[1.65] bg-ink text-surface"
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
      {/* Output files the run produced — end of the run, above sources. */}
      {runFileRefs && runFileRefs.length > 0 && (
        <FileChips refs={runFileRefs} onPreview={onPreview} />
      )}
      {message.citations && message.citations.length > 0 && <CitationList citations={message.citations} />}
      {hasCost && (
        <div className="mt-1.5 font-mono text-[11px]" style={{ color: "var(--ink-3)" }}>
          {message.tokens_out || 0} tokens · ${(message.cost || 0).toFixed(3)}
        </div>
      )}
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

/** Message-level attachment card — the shared AttachmentCard in open mode.
 *  Images fetch a real thumbnail through the preview backend's blob read;
 *  files with a stored path open the preview panel; URLs open a new tab. */
function MessageAttachmentCard({
  file,
  agentId,
  onPreview,
}: {
  file: { type: string; mime_type: string; filename: string; url?: string; path?: string; size?: number; preview_url?: string };
  agentId?: string;
  onPreview?: (source: PreviewSource) => void;
}) {
  const isUrl = file.type === "url" || file.type === "image_url";
  const isImage = !isUrl && (file.type === "image" || file.mime_type?.startsWith("image/"));
  // Persisted blob wins once path exists; `preview_url` is the draft's
  // ephemeral data URL covering the window before persistence lands.
  const { url: blobUrl } = useObjectUrl(
    isImage && file.path && agentId
      ? () => workspaceBackend(agentId).blob({ path: file.path! })
      : null,
    [file.path, agentId]
  );

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
