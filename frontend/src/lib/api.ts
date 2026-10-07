// API client — the only way the frontend talks to the backend (D33)

import { invoke } from "@tauri-apps/api/core";
import type {
  Agent,
  AgentVersion,
  Approval,
  ArtifactRevisionInfo,
  AuditOut,
  CapabilityGrant,
  CapabilityInfo,
  ChannelInfo,
  DashboardStats,
  HealthStatus,
  HeartbeatConfig,
  HeartbeatStatus,
  Limits,
  McpCatalogEntry,
  McpServerInfo,
  McpToolInfo,
  Message,
  ModelInfo,
  Notification,
  NotificationPrefs,
  NotificationPrefsPatch,
  Operator,
  OperatorAuditOut,
  PreviewPayload,
  Provider,
  RunDetail,
  RunSummary,
  Schedule,
  ScheduleOccurrence,
  SchedulePayload,
  ScheduleTrigger,
  SchedulerAlert,
  SessionInfo,
  Skill,
  SkillDetail,
  SkillImportResult,
  SkillInfo,
  EffectiveSkill,
  SpendSummary,
  KnowledgeDocument,
  KnowledgeEmbeddingResource,
  KnowledgeGeneration,
  KnowledgeIndexOverview,
  KnowledgeResult,
  KnowledgeScope,
  WorkspaceEntry,
} from "./types";

// Preview source selector shared by the workspace/preview|raw|pdf-page
// family — {path} for live files, {artifactId, revisionId} for managed
// revision bytes.
export interface PreviewSource {
  path?: string;
  artifactId?: string;
  revisionId?: string;
  /** Skill revision number (skill preview endpoints only). */
  revision?: number;
}

function sourceQuery(opts: PreviewSource): string {
  const params = new URLSearchParams();
  if (opts.path) params.set("path", opts.path);
  if (opts.artifactId) params.set("artifact_id", opts.artifactId);
  if (opts.revisionId) params.set("revision_id", opts.revisionId);
  if (opts.revision != null) params.set("revision", String(opts.revision));
  return params.toString();
}

/**
 * The three reads every preview surface needs. Workspace and skill
 * resources each get an implementation so the same renderers serve
 * chat, Workspace, and Skills Studio.
 */
export interface PreviewBackend {
  preview(source: PreviewSource): Promise<import("./types").PreviewPayload>;
  /** Object URL for the source bytes — caller revokes. */
  blob(source: PreviewSource): Promise<string>;
  /** Object URL of a rendered PDF page PNG. */
  pdfPage(page: number, source: PreviewSource): Promise<string>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/**
 * Read a failed response and produce a clean error message — extracts
 * FastAPI `detail` (string, {message, errors}, {code, message}, or the
 * 422 validation array) instead of surfacing raw JSON to the UI.
 */
async function apiError(resp: Response): Promise<ApiError> {
  const text = await resp.text().catch(() => "");
  let code: string | undefined;
  let message = `${resp.status}: ${text || resp.statusText}`;
  try {
    const detail = JSON.parse(text)?.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      message = detail
        .map((d) => (typeof d?.msg === "string" ? d.msg : JSON.stringify(d)))
        .join("; ");
    } else if (detail && typeof detail === "object") {
      if (typeof detail.code === "string") code = detail.code;
      const parts: string[] = [];
      if (typeof detail.message === "string") parts.push(detail.message);
      if (Array.isArray(detail.errors))
        parts.push(...detail.errors.map(String));
      if (parts.length) message = parts.join(": ");
    }
  } catch {
    /* non-JSON error body — keep raw */
  }
  return new ApiError(resp.status, message, code);
}

async function fetchBlob(path: string): Promise<string> {
  const base = await baseReady;
  const resp = await fetch(`${base}${path}`, {
    credentials: "include",
    headers: authHeaders(),
  });
  if (!resp.ok) throw await apiError(resp);
  return URL.createObjectURL(await resp.blob());
}

const isDesktopShell =
  typeof window !== "undefined" &&
  (window.location.protocol === "tauri:" ||
    window.location.hostname === "tauri.localhost");
const configuredBase = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "");
let resolvedBase =
  configuredBase || (isDesktopShell ? "http://127.0.0.1:51718" : "");

const baseReady =
  configuredBase || !isDesktopShell
    ? Promise.resolve(resolvedBase)
    : invoke<string>("gateway_url")
        .then((url) => {
          resolvedBase = url.replace(/\/$/, "");
          return resolvedBase;
        })
        .catch(() => resolvedBase);

const SESSION_TOKEN_KEY = "agentos_session_token";

function getSessionToken(): string | null {
  try {
    return localStorage.getItem(SESSION_TOKEN_KEY);
  } catch {
    return null;
  }
}

function setSessionToken(token: string | null) {
  try {
    if (token) localStorage.setItem(SESSION_TOKEN_KEY, token);
    else localStorage.removeItem(SESSION_TOKEN_KEY);
  } catch {
    // localStorage may be unavailable in some contexts
  }
}

function authHeaders(): Record<string, string> {
  const token = getSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const base = await baseReady;
  const resp = await fetch(`${base}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...options.headers,
    },
    ...options,
  });
  if (!resp.ok) throw await apiError(resp);
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export interface BrowserRuntimeInfo {
  status: string;
  binary?: string;
  managed?: boolean;
  managed_binary?: string | null;
  source?: "override" | "system" | "managed";
  version?: string;
  installable?: boolean;
  detail?: string;
  install_progress?: {
    phase: string;
    downloaded: number;
    total: number | null;
  } | null;
}

export const api = {
  get baseURL() {
    return resolvedBase;
  },
  authHeaders,

  gatewayHealth: () => request<{ status: string }>("/health"),
  gatewayLogPath: () => invoke<string>("gateway_log_path"),

  // Auth
  login: (username: string, password: string) =>
    request<{
      operator: Operator;
      must_change_password: boolean;
      session_token: string;
    }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }).then((resp) => {
      if (resp.session_token) setSessionToken(resp.session_token);
      return resp;
    }),
  logout: () =>
    request<{ status: string }>("/api/auth/logout", { method: "POST" }).then(
      (resp) => {
        setSessionToken(null);
        return resp;
      },
    ),
  me: () => request<Operator>("/api/auth/me"),

  // Agents
  listAgents: () => request<Agent[]>("/api/agents"),
  getAgent: (id: string) => request<Agent>(`/api/agents/${id}`),
  listCapabilities: () => request<CapabilityInfo[]>("/api/agents/capabilities"),
  createAgent: (data: {
    name: string;
    provider_id?: string;
    model_name?: string;
    soul?: string;
    persona?: string;
    task?: string;
  }) =>
    request<{ id: string; name: string; enabled: boolean }>("/api/agents", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateAgent: (
    id: string,
    data: {
      name?: string;
      provider_id?: string;
      model_name?: string;
      thinking_enabled?: boolean | null;
      thinking_effort?: string | null;
      soul?: string;
      persona?: string;
      task?: string;
      sandbox_mode?: "strict" | "open";
      yolo_mode?: boolean;
      capabilities?: CapabilityGrant[] | null;
      limits?: Limits;
      heartbeat?: HeartbeatConfig;
    },
  ) =>
    request<{ id: string; version: number; version_id: string }>(
      `/api/agents/${id}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
      },
    ),
  disableAgent: (id: string) =>
    request<{ id: string; enabled: boolean }>(`/api/agents/${id}/disable`, {
      method: "POST",
    }),
  enableAgent: (id: string) =>
    request<{ id: string; enabled: boolean }>(`/api/agents/${id}/enable`, {
      method: "POST",
    }),
  duplicateAgent: (id: string, newId: string, newName: string) =>
    request<{ id: string; name: string; enabled: boolean }>(
      `/api/agents/${id}/duplicate`,
      {
        method: "POST",
        body: JSON.stringify({ new_id: newId, new_name: newName }),
      },
    ),
  exportAgent: (id: string) =>
    request<{ yaml: string }>(`/api/agents/${id}/export`),
  importAgent: (yaml: string) =>
    request<{ id: string; name: string; enabled: boolean }>(
      "/api/agents/import",
      {
        method: "POST",
        body: JSON.stringify({ yaml }),
      },
    ),
  listVersions: (id: string) =>
    request<AgentVersion[]>(`/api/agents/${id}/versions`),
  getVersion: (id: string, versionId: string) =>
    request<{
      id: string;
      version_number: number;
      is_active: boolean;
      config: Record<string, unknown>;
    }>(`/api/agents/${id}/versions/${versionId}`),
  rollbackAgent: (id: string, versionId: string) =>
    request<{ id: string; version_number: number; is_active: boolean }>(
      `/api/agents/${id}/rollback/${versionId}`,
      { method: "POST" },
    ),

  // Agent files — MEMORY.md, skills, workspace
  getMemory: (id: string) =>
    request<{ content: string; exists: boolean }>(`/api/agents/${id}/memory`),
  updateMemory: (id: string, content: string) =>
    request<{ ok: boolean; bytes: number }>(`/api/agents/${id}/memory`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  listAgentSkills: (id: string) => request<Skill[]>(`/api/agents/${id}/skills`),
  listAvailableSkills: (id: string) =>
    request<SkillInfo[]>(`/api/agents/${id}/available-skills`),
  createAgentSkill: (id: string, name: string, content?: string) =>
    request<{ name: string; path: string }>(`/api/agents/${id}/skills`, {
      method: "POST",
      body: JSON.stringify({ name, content: content || "" }),
    }),
  deleteAgentSkill: (id: string, skillName: string) =>
    request<{ ok: boolean }>(`/api/agents/${id}/skills/${skillName}`, {
      method: "DELETE",
    }),
  listWorkspace: (id: string, path?: string) =>
    request<{
      type: "dir" | "file";
      path: string;
      entries?: WorkspaceEntry[];
      content?: string;
      size?: number;
    }>(
      `/api/agents/${id}/workspace${path ? `?path=${encodeURIComponent(path)}` : ""}`,
    ),
  deleteWorkspaceEntry: (id: string, path: string) =>
    request<{ deleted: boolean; path: string }>(
      `/api/agents/${id}/workspace?path=${encodeURIComponent(path)}`,
      { method: "DELETE" },
    ),

  // File previews (W3) — one param object shared by the whole family:
  // {path} for live files, {artifactId, revisionId} for managed bytes.
  previewFile: (id: string, opts: PreviewSource = {}) =>
    request<PreviewPayload>(
      `/api/agents/${id}/workspace/preview?${sourceQuery(opts)}`,
    ),

  // Binary content can't ride <img src>/<video src> — Bearer auth has no
  // cookie fallback in the desktop shell. Fetch the blob, hand the caller
  // an object URL, and let them revoke it on unmount.
  fetchFileBlob: (id: string, opts: PreviewSource = {}): Promise<string> =>
    fetchBlob(`/api/agents/${id}/workspace/raw?${sourceQuery(opts)}`),

  fetchPdfPage: (
    id: string,
    page: number,
    opts: PreviewSource = {},
  ): Promise<string> =>
    fetchBlob(
      `/api/agents/${id}/workspace/pdf-page?page=${page}&${sourceQuery(opts)}`,
    ),

  listArtifactRevisions: (id: string, artifactId: string) =>
    request<{ revisions: ArtifactRevisionInfo[] }>(
      `/api/agents/${id}/artifacts/${artifactId}/revisions`,
    ),
  restoreArtifactRevision: (
    id: string,
    artifactId: string,
    revisionId: string,
  ) =>
    request<{ revision_id: string; revision_number: number }>(
      `/api/agents/${id}/artifacts/${artifactId}/restore`,
      { method: "POST", body: JSON.stringify({ revision_id: revisionId }) },
    ),
  compareArtifactRevisions: (
    id: string,
    artifactId: string,
    fromRevision: string,
    toRevision?: string,
  ) => {
    const qs = new URLSearchParams({ from_revision: fromRevision });
    if (toRevision) qs.set("to_revision", toRevision);
    return request<{
      comparable: boolean;
      reason?: string;
      diff?: string;
      from_revision_number: number | null;
      to_revision_number: number | null;
      from_bytes: number;
      to_bytes: number;
      identical: boolean;
    }>(`/api/agents/${id}/artifacts/${artifactId}/compare?${qs.toString()}`);
  },
  adoptWorkspaceFile: (id: string, path: string) =>
    request<{ artifact_id: string; revision_id: string; path: string }>(
      `/api/agents/${id}/artifacts/adopt`,
      { method: "POST", body: JSON.stringify({ path }) },
    ),
  // Composer attachment previews (W3c) — ephemeral, nothing persisted.
  previewAttachment: async (
    id: string,
    file: File,
  ): Promise<PreviewPayload> => {
    const formData = new FormData();
    formData.append("file", file);
    const base = await baseReady;
    const resp = await fetch(`${base}/api/agents/${id}/attachments/preview`, {
      method: "POST",
      credentials: "include",
      headers: { ...authHeaders() },
      body: formData,
    });
    if (!resp.ok) throw await apiError(resp);
    return resp.json();
  },
  previewUrl: (id: string, url: string) =>
    request<{ url: string; domain: string; title: string | null }>(
      `/api/agents/${id}/attachments/url-preview?url=${encodeURIComponent(url)}`,
    ),

  // Knowledge Vault
  listKnowledgeOverview: () =>
    request<{ scopes: KnowledgeScope[] }>("/api/knowledge/overview"),
  listKnowledgeDocuments: () =>
    request<{ documents: KnowledgeDocument[] }>("/api/knowledge/documents"),
  uploadKnowledgeDocument: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const base = await baseReady;
    const response = await fetch(`${base}/api/knowledge/documents/upload`, {
      method: "POST",
      credentials: "include",
      headers: authHeaders(),
      body: form,
    });
    if (!response.ok) throw await apiError(response);
    return response.json() as Promise<KnowledgeDocument>;
  },
  searchKnowledge: (query: string, limit = 5) =>
    request<{ results: KnowledgeResult[] }>("/api/knowledge/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  deleteKnowledgeDocument: (documentId: string) =>
    request<void>(`/api/knowledge/documents/${documentId}`, {
      method: "DELETE",
    }),
  listKnowledgeScope: (scope: string) =>
    request<{ documents: KnowledgeDocument[] }>(
      `/api/knowledge/scopes/${scope}/documents`,
    ),
  uploadKnowledgeScope: async (scope: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const base = await baseReady;
    const response = await fetch(
      `${base}/api/knowledge/scopes/${scope}/documents/upload`,
      {
        method: "POST",
        credentials: "include",
        headers: authHeaders(),
        body: form,
      },
    );
    if (!response.ok) throw await apiError(response);
    return response.json() as Promise<KnowledgeDocument>;
  },
  searchKnowledgeScope: (scope: string, query: string, limit = 5) =>
    request<{ results: KnowledgeResult[] }>(
      `/api/knowledge/scopes/${scope}/search`,
      {
        method: "POST",
        body: JSON.stringify({ query, limit }),
      },
    ),
  reindexKnowledgeDocument: (scope: string, documentId: string) =>
    request<KnowledgeDocument>(
      `/api/knowledge/scopes/${scope}/documents/${documentId}/reindex`,
      {
        method: "POST",
      },
    ),
  deleteKnowledgeScope: (scope: string, documentId: string) =>
    request<void>(`/api/knowledge/scopes/${scope}/documents/${documentId}`, {
      method: "DELETE",
    }),

  // Knowledge index (RAG v2 — semantic index lifecycle)
  getKnowledgeIndex: () =>
    request<KnowledgeIndexOverview>("/api/knowledge/index"),
  listKnowledgeGenerations: () =>
    request<{ generations: KnowledgeGeneration[] }>(
      "/api/knowledge/index/generations",
    ),
  rebuildKnowledgeIndex: () =>
    request<KnowledgeGeneration>("/api/knowledge/index/rebuild", {
      method: "POST",
    }),
  repairKnowledgeIndex: () =>
    request<{ fixed: number; still_pending: number; reasons: string[] }>(
      "/api/knowledge/index/repair",
      { method: "POST" },
    ),
  activateKnowledgeGeneration: (generationId: string) =>
    request<KnowledgeGeneration>(
      `/api/knowledge/index/generations/${generationId}/activate`,
      { method: "POST" },
    ),
  deleteKnowledgeGeneration: (generationId: string) =>
    request<void>(`/api/knowledge/index/generations/${generationId}`, {
      method: "DELETE",
    }),
  putEmbeddingResource: (data: {
    provider_id: string;
    model_name: string;
    egress_allowed: boolean;
  }) =>
    request<KnowledgeEmbeddingResource>("/api/knowledge/embedding-resource", {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  validateEmbeddingResource: () =>
    request<KnowledgeEmbeddingResource>(
      "/api/knowledge/embedding-resource/validate",
      {
        method: "POST",
      },
    ),
  putRetrievalProfile: (config: Record<string, unknown>) =>
    request<{ id: string; revision: number; config: Record<string, unknown> }>(
      "/api/knowledge/retrieval-profile",
      { method: "PUT", body: JSON.stringify(config) },
    ),

  // Chat — POST /message starts a run, returns {run_id, session_id}
  sendMessage: (
    agentId: string,
    text: string,
    isTest = false,
    modelOverride?: {
      provider_id: string;
      name: string;
      thinking_enabled?: boolean | null;
      thinking_effort?: string | null;
    },
    sessionId?: string,
    attachments?: {
      type: string;
      mime_type: string;
      data: string;
      filename: string;
    }[],
    newSession = false,
    skill?: string,
  ) =>
    request<{ run_id: string; session_id: string; status: string }>(
      `/api/chat/${agentId}/message`,
      {
        method: "POST",
        body: JSON.stringify({
          text,
          is_test: isTest,
          model_override: modelOverride,
          session_id: sessionId,
          new_session: newSession,
          attachments: attachments || [],
          skill,
        }),
      },
    ),

  // Stream run events via SSE (reconnectable with Last-Event-ID)
  streamRunEvents: async function* (
    agentId: string,
    runId: string,
    lastEventId = 0,
    signal?: AbortSignal,
  ): AsyncGenerator<{ event: string; data: any; id: number }> {
    const base = await baseReady;
    const resp = await fetch(
      `${base}/api/chat/${agentId}/runs/${runId}/events`,
      {
        credentials: "include",
        headers: {
          ...authHeaders(),
          ...(lastEventId > 0 ? { "Last-Event-ID": String(lastEventId) } : {}),
        },
        signal,
      },
    );
    if (!resp.ok) throw await apiError(resp);
    if (!resp.body) return;

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events (separated by \n\n)
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);

        let event = "message";
        let data = "";
        let eventId = 0;
        for (const line of raw.split("\n")) {
          if (line.startsWith("id: "))
            eventId = parseInt(line.slice(4), 10) || 0;
          else if (line.startsWith("event: ")) event = line.slice(7);
          else if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (data) {
          try {
            yield { event, data: JSON.parse(data), id: eventId };
          } catch {
            yield { event, data, id: eventId };
          }
        }
      }
    }
  },

  // Run management
  getRunStatus: (agentId: string, runId: string) =>
    request<{
      run_id: string;
      session_id: string;
      agent_id: string;
      status: string;
      event_count: number;
    }>(`/api/chat/${agentId}/runs/${runId}`),
  stopRun: (agentId: string, runId: string) =>
    request<{ status: string }>(`/api/chat/${agentId}/runs/${runId}/stop`, {
      method: "POST",
    }),
  getHistory: (agentId: string, limit = 50) =>
    request<Message[]>(`/api/chat/${agentId}/history?limit=${limit}`),

  // Sessions
  listSessions: (agentId: string) =>
    request<SessionInfo[]>(`/api/chat/${agentId}/sessions`),
  createSession: (agentId: string, title?: string) =>
    request<{ id: string; title: string; status: string }>(
      `/api/chat/${agentId}/sessions`,
      { method: "POST", body: JSON.stringify({ title }) },
    ),
  getSessionMessages: (
    agentId: string,
    sessionId: string,
    limit = 100,
    beforeId?: string,
  ) =>
    request<{ messages: Message[]; has_more: boolean }>(
      `/api/chat/${agentId}/sessions/${sessionId}/messages?limit=${limit}` +
        (beforeId ? `&before_id=${encodeURIComponent(beforeId)}` : ""),
    ),
  deleteSession: (agentId: string, sessionId: string) =>
    request<{ deleted: boolean }>(
      `/api/chat/${agentId}/sessions/${sessionId}`,
      { method: "DELETE" },
    ),
  compactSession: (agentId: string, sessionId: string) =>
    request<{
      compacted: boolean;
      original_tokens: number;
      compacted_tokens: number;
      max_context_tokens: number;
      head_count: number;
      middle_count: number;
      tail_count: number;
      summary: string | null;
    }>(`/api/chat/${agentId}/compact`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),

  // Notifications
  listNotifications: (unreadOnly = false, signal?: AbortSignal) =>
    request<Notification[]>(
      `/api/notifications${unreadOnly ? "?unread_only=true" : ""}`,
      { signal },
    ),
  markNotificationRead: (id: string) =>
    request<{ updated: boolean }>(`/api/notifications/${id}/read`, {
      method: "POST",
    }),
  markAllNotificationsRead: () =>
    request<{ updated: boolean }>("/api/notifications/read-all", {
      method: "POST",
    }),
  // W9 — delivery state, prefs, frontend-driven emits
  reportDelivery: (notificationId: string, adapter: string, state: string, error?: string) =>
    request<{ recorded: boolean }>(`/api/notifications/${notificationId}/delivery`, {
      method: "POST",
      body: JSON.stringify({ adapter, state, error: error ?? null }),
    }),
  failedDeliveries: () =>
    request<{ notification: Notification; adapter: string; attempts: number }[]>(
      "/api/notifications/deliveries/failed",
    ),
  getNotificationPrefs: () => request<NotificationPrefs>("/api/notifications/prefs"),
  putNotificationPrefs: (prefs: NotificationPrefsPatch) =>
    request<NotificationPrefs>("/api/notifications/prefs", {
      method: "PUT",
      body: JSON.stringify(prefs),
    }),
  emitNotification: (data: {
    notification_type: string;
    title: string;
    message: string;
    severity?: string;
    action_path?: string | null;
    entity_id?: string | null;
    entity_type?: string | null;
    event_id?: string | null;
  }) =>
    request<Notification>("/api/notifications/emit", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  // W9 — SSE fan-out; one event per committed notification row
  streamNotifications: async function* (
    signal?: AbortSignal,
  ): AsyncGenerator<Notification> {
    const base = await baseReady;
    const resp = await fetch(`${base}/api/notifications/stream`, {
      credentials: "include",
      headers: authHeaders(),
      signal,
    });
    if (!resp.ok) throw await apiError(resp);
    if (!resp.body) return;
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        let data = "";
        for (const line of raw.split("\n")) {
          if (line.startsWith("data: ")) data += line.slice(6);
        }
        if (!data) continue;
        try {
          const payload = JSON.parse(data);
          if (payload?.type === "notification" && payload.notification) {
            yield payload.notification as Notification;
          }
        } catch {
          // keepalive / malformed frame — skip
        }
      }
    }
  },

  // Data migration
  importBackup: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mode", "merge");
    const base = await baseReady;
    const response = await fetch(`${base}/api/data/import`, {
      method: "POST",
      credentials: "include",
      headers: authHeaders(),
      body: form,
    });
    if (!response.ok) throw await apiError(response);
    return response.json() as Promise<{ status: string }>;
  },
  deleteAllData: () =>
    request<{ status: string; requires_relogin: boolean }>(
      "/api/data/delete-all",
      {
        method: "POST",
        body: JSON.stringify({ confirmation: "DELETE ALL DATA" }),
      },
    ),

  // Providers
  listProviders: () => request<Provider[]>("/api/providers"),
  createProvider: (data: Partial<Provider> & { api_key?: string }) =>
    request<Provider>("/api/providers", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateProvider: (
    id: string,
    data: Partial<Provider> & { api_key?: string },
  ) =>
    request<Provider>(`/api/providers/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteProvider: (id: string) =>
    request<{ status: string }>(`/api/providers/${id}`, { method: "DELETE" }),
  listModels: (id: string) =>
    request<{ discovery: string; models: ModelInfo[] }>(
      `/api/providers/${id}/models`,
    ),
  addCustomModel: (id: string, modelName: string) =>
    request<{ custom_models: string[] }>(`/api/providers/${id}/models`, {
      method: "POST",
      body: JSON.stringify({ model_name: modelName }),
    }),
  removeCustomModel: (id: string, modelName: string) =>
    request<{ custom_models: string[] }>(
      `/api/providers/${id}/models/${encodeURIComponent(modelName)}`,
      {
        method: "DELETE",
      },
    ),

  // Approvals
  listApprovals: (status = "pending") =>
    request<Approval[]>(`/api/approvals?status=${status}`),
  approveCall: (
    id: string,
    remember = false,
    rememberScope: "exact" | "same_verb" | "pattern" | "capability" = "exact",
    rememberPattern?: string,
  ) =>
    request<{ status: string }>(`/api/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({
        remember,
        remember_scope: rememberScope,
        remember_pattern: rememberPattern,
      }),
    }),
  rejectCall: (id: string) =>
    request<{ status: string }>(`/api/approvals/${id}/reject`, {
      method: "POST",
    }),

  // Elicitation
  respondToElicitation: (id: string, response: string) =>
    request<{ status: string }>(`/api/elicitation/${id}/respond`, {
      method: "POST",
      body: JSON.stringify({ response }),
    }),

  // Skills Studio (W6) — scoped, revisioned, DB-backed library.
  listSkills: (view = "all", agentId?: string, q?: string) => {
    const params = new URLSearchParams({ view });
    if (agentId) params.set("agent_id", agentId);
    if (q) params.set("q", q);
    return request<{ skills: SkillInfo[]; count: number }>(
      `/api/skills?${params.toString()}`,
    );
  },
  effectiveSkills: (agentId: string) =>
    request<{ agent_id: string; skills: EffectiveSkill[] }>(
      `/api/skills/effective?agent_id=${agentId}`,
    ),
  skillDetail: (id: string) => request<SkillDetail>(`/api/skills/${id}`),
  skillFiles: (id: string, revision?: number) =>
    request<{ files: { path: string; size: number; mime: string }[] }>(
      `/api/skills/${id}/files${revision != null ? `?revision=${revision}` : ""}`,
    ),
  validateSkill: (id: string) =>
    request<{
      errors: string[];
      warnings: string[];
      stats: Record<string, number>;
    }>(`/api/skills/${id}/validate`),
  createSkillDraft: (body: {
    name: string;
    agent_id?: string;
    launch_session?: boolean;
  }) =>
    request<{
      id: string;
      name: string;
      status: string;
      session_id: string | null;
    }>("/api/skills/drafts", { method: "POST", body: JSON.stringify(body) }),
  deleteSkill: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/api/skills/${id}`, {
      method: "DELETE",
    }),
  publishSkill: (
    id: string,
    body: {
      scope: "global" | "agent-local";
      owner_agent_id?: string;
      availability?: "all" | "selected";
      agent_ids?: string[];
      change_summary?: string;
    },
  ) =>
    request<{ published: boolean; revision: number; id: string }>(
      `/api/skills/${id}/publish`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  promoteSkill: (
    id: string,
    body: {
      availability?: "all" | "selected";
      agent_ids?: string[];
      change_summary?: string;
    } = {},
  ) =>
    request<{ promoted: boolean; revision: number }>(
      `/api/skills/${id}/promote`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  duplicateSkill: (
    id: string,
    body: { owner_agent_id?: string; new_name?: string },
  ) =>
    request<{ id: string; name: string; status: string }>(
      `/api/skills/${id}/duplicate`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  restoreSkill: (id: string, revision_number: number) =>
    request<{ restored: boolean; revision: number }>(
      `/api/skills/${id}/restore`,
      { method: "POST", body: JSON.stringify({ revision_number }) },
    ),
  setSkillStatus: (id: string, status: "published" | "disabled" | "archived") =>
    request<{ id: string; status: string }>(`/api/skills/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),
  exportSkill: (id: string, revision?: number): Promise<string> =>
    fetchBlob(
      `/api/skills/${id}/export${revision != null ? `?revision=${revision}` : ""}`,
    ),
  importSkillZip: async (
    file: File,
    opts: { owner_agent_id?: string; paths?: string[] } = {},
  ): Promise<SkillImportResult> => {
    const formData = new FormData();
    formData.append("file", file);
    if (opts.owner_agent_id)
      formData.append("owner_agent_id", opts.owner_agent_id);
    if (opts.paths) formData.append("paths", JSON.stringify(opts.paths));
    const base = await baseReady;
    return fetch(`${base}/api/skills/import`, {
      method: "POST",
      credentials: "include",
      headers: { ...authHeaders() },
      body: formData,
    }).then(async (r) => {
      if (!r.ok) throw await apiError(r);
      return r.json();
    });
  },
  importSkillUrl: (body: {
    url: string;
    owner_agent_id?: string;
    paths?: string[];
  }) =>
    request<SkillImportResult>("/api/skills/import-url", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // Skill resource previews — same payload shape as workspace previews,
  // rooted at the skill's revision/draft/live dir. `revision` selects a
  // specific SkillRevision's bytes.
  previewSkillResource: (id: string, opts: PreviewSource = {}) =>
    request<PreviewPayload>(`/api/skills/${id}/preview?${sourceQuery(opts)}`),
  fetchSkillBlob: (id: string, opts: PreviewSource = {}): Promise<string> =>
    fetchBlob(`/api/skills/${id}/raw?${sourceQuery(opts)}`),
  fetchSkillPdfPage: (
    id: string,
    page: number,
    opts: PreviewSource = {},
  ): Promise<string> =>
    fetchBlob(`/api/skills/${id}/pdf-page?page=${page}&${sourceQuery(opts)}`),

  // Scheduler — heartbeat
  listHeartbeats: () => request<HeartbeatStatus[]>("/api/scheduler/heartbeat"),
  updateHeartbeat: (agentId: string, data: Partial<HeartbeatConfig>) =>
    request<{ agent_id: string; version: number; heartbeat: HeartbeatConfig }>(
      `/api/scheduler/heartbeat/${agentId}`,
      { method: "PUT", body: JSON.stringify(data) },
    ),
  fireHeartbeat: (agentId: string) =>
    request<{
      run_id: string;
      session_id: string;
      status: string;
      cost: number;
      error: string | null;
    }>(`/api/scheduler/heartbeat/${agentId}/fire`, { method: "POST" }),
  listSchedulerAlerts: () => request<SchedulerAlert[]>("/api/scheduler/alerts"),
  clearSchedulerAlert: (agentId: string) =>
    request<{ agent_id: string; cleared: boolean }>(
      `/api/scheduler/alerts/${agentId}/clear`,
      { method: "POST" },
    ),

  // Schedules (v0.2 W8)
  listSchedules: () => request<Schedule[]>("/api/schedules"),
  getSchedule: (id: string) => request<Schedule>(`/api/schedules/${id}`),
  createSchedule: (data: SchedulePayload) =>
    request<Schedule>("/api/schedules", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateSchedule: (id: string, data: SchedulePayload) =>
    request<Schedule>(`/api/schedules/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  pauseSchedule: (id: string) =>
    request<{ id: string; enabled: boolean }>(`/api/schedules/${id}/pause`, {
      method: "POST",
    }),
  resumeSchedule: (id: string) =>
    request<Schedule>(`/api/schedules/${id}/resume`, { method: "POST" }),
  duplicateSchedule: (id: string) =>
    request<Schedule>(`/api/schedules/${id}/duplicate`, { method: "POST" }),
  deleteSchedule: (id: string) =>
    request<{ id: string; archived: boolean }>(`/api/schedules/${id}`, {
      method: "DELETE",
    }),
  runScheduleNow: (id: string) =>
    request<{ run_id: string | null; status: string; error: string | null }>(
      `/api/schedules/${id}/run-now`,
      { method: "POST" },
    ),
  testRunSchedule: (id: string) =>
    request<{ run_id: string | null; status: string; error: string | null }>(
      `/api/schedules/${id}/test-run`,
      { method: "POST" },
    ),
  previewSchedule: (trigger: ScheduleTrigger, count = 5) =>
    request<{ timezone: string; occurrences: string[] }>(
      "/api/schedules/preview",
      { method: "POST", body: JSON.stringify({ trigger, count }) },
    ),
  listScheduleOccurrences: (id: string, limit = 50, offset = 0) =>
    request<{ occurrences: ScheduleOccurrence[]; total: number }>(
      `/api/schedules/${id}/occurrences?limit=${limit}&offset=${offset}`,
    ),

  // MCP servers
  listMcpServers: () => request<McpServerInfo[]>("/api/mcp/servers"),
  createMcpServer: (data: {
    name: string;
    transport: string;
    command?: string;
    args?: string[];
    url?: string;
    env_template?: Record<string, string>;
    tool_filter?: string[];
    enabled?: boolean;
  }) =>
    request<{ id: string; name: string; connected: boolean }>(
      "/api/mcp/servers",
      {
        method: "POST",
        body: JSON.stringify(data),
      },
    ),
  deleteMcpServer: (id: string) =>
    request<{ id: string; deleted: boolean }>(`/api/mcp/servers/${id}`, {
      method: "DELETE",
    }),
  listMcpServerTools: (id: string) =>
    request<McpToolInfo[]>(`/api/mcp/servers/${id}/tools`),
  getMcpServerBlastRadius: (id: string) =>
    request<{ agent_id: string; agent_name: string; capabilities: string[] }[]>(
      `/api/mcp/servers/${id}/agents`,
    ),
  connectMcpServer: (id: string) =>
    request<{ id: string; connected: boolean }>(
      `/api/mcp/servers/${id}/connect`,
      {
        method: "POST",
      },
    ),
  updateMcpServer: (
    id: string,
    data: {
      require_approval?: boolean;
      enabled?: boolean;
      tool_filter?: string[] | null;
    },
  ) =>
    request<{
      id: string;
      require_approval: boolean;
      enabled: boolean;
      tool_filter: string[] | null;
      connected: boolean;
    }>(`/api/mcp/servers/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  storeMcpCredential: (
    serverId: string,
    data: {
      credential_type: string;
      value: string | Record<string, unknown>;
      label?: string;
    },
  ) =>
    request<{
      id: string;
      credential_type: string;
      label: string | null;
      connected: boolean;
    }>(`/api/mcp/servers/${serverId}/credentials`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  listMcpCredentials: (serverId: string) =>
    request<
      {
        id: string;
        credential_type: string;
        label: string | null;
        created_at: string;
      }[]
    >(`/api/mcp/servers/${serverId}/credentials`),
  deleteMcpCredential: (serverId: string, credentialId: string) =>
    request<{ deleted: boolean }>(
      `/api/mcp/servers/${serverId}/credentials/${credentialId}`,
      { method: "DELETE" },
    ),
  startMcpOAuth: (serverId: string) =>
    request<{ authorize_url: string }>(
      `/api/mcp/servers/${serverId}/oauth/start`,
      { method: "POST" },
    ),
  getMcpOAuthStatus: (serverId: string) =>
    request<{ status: string; authorize_url?: string; error?: string }>(
      `/api/mcp/servers/${serverId}/oauth/status`,
    ),

  // MCP catalog (marketplace)
  listMcpCatalog: (category?: string, q?: string) => {
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    if (q) params.set("q", q);
    const qs = params.toString();
    return request<McpCatalogEntry[]>(`/api/mcp/catalog${qs ? "?" + qs : ""}`);
  },
  listMcpCatalogCategories: () =>
    request<{ name: string; count: number }[]>("/api/mcp/catalog/categories"),
  installFromCatalog: (name: string) =>
    request<{
      id: string;
      name: string;
      connected: boolean;
      auth_type: string;
      message: string | null;
    }>("/api/mcp/catalog/install", {
      method: "POST",
      body: JSON.stringify({ name, enabled: true }),
    }),

  // Channels (external messaging — Telegram, Discord, Zalo, ...)
  listChannels: () => request<ChannelInfo[]>("/api/channels"),
  createChannel: (data: {
    platform: string;
    agent_id: string;
    bot_token: string;
    webhook_secret?: string;
    mode?: string;
  }) =>
    request<ChannelInfo>("/api/channels", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateChannel: (
    id: string,
    data: {
      bot_token?: string;
      webhook_secret?: string;
      enabled?: boolean;
      mode?: string;
    },
  ) =>
    request<ChannelInfo>(`/api/channels/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteChannel: (id: string) =>
    request<{ status: string }>(`/api/channels/${id}`, { method: "DELETE" }),
  testChannel: (id: string, chat_id: string) =>
    request<{ success: boolean; error: string | null }>(
      `/api/channels/${id}/test`,
      {
        method: "POST",
        body: JSON.stringify({ chat_id }),
      },
    ),

  // Observability (Ticket 09)
  listRuns: (params?: {
    agent_id?: string;
    status?: string;
    trigger?: string;
    is_test?: boolean;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.agent_id) qs.set("agent_id", params.agent_id);
    if (params?.status) qs.set("status", params.status);
    if (params?.trigger) qs.set("trigger", params.trigger);
    if (params?.is_test !== undefined)
      qs.set("is_test", String(params.is_test));
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<RunSummary[]>(`/api/runs${q ? `?${q}` : ""}`);
  },
  getRunDetail: (runId: string) => request<RunDetail>(`/api/runs/${runId}`),
  listAudit: (params?: {
    agent_id?: string;
    capability_name?: string;
    allowed?: boolean;
    run_id?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    if (params?.agent_id) qs.set("agent_id", params.agent_id);
    if (params?.capability_name)
      qs.set("capability_name", params.capability_name);
    if (params?.allowed !== undefined)
      qs.set("allowed", String(params.allowed));
    if (params?.run_id) qs.set("run_id", params.run_id);
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.offset) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return request<AuditOut[]>(`/api/audit${q ? `?${q}` : ""}`);
  },
  getSpend: (days = 1, agentId?: string) => {
    const qs = new URLSearchParams({ days: String(days) });
    if (agentId) qs.set("agent_id", agentId);
    return request<SpendSummary>(`/api/spend?${qs.toString()}`);
  },
  listOperatorAudit: (limit = 50, offset = 0) =>
    request<OperatorAuditOut[]>(
      `/api/operator-audit?limit=${limit}&offset=${offset}`,
    ),
  getHealth: () => request<HealthStatus>("/api/health"),
  getDashboardStats: (days = 7) =>
    request<DashboardStats>(`/api/stats?days=${days}`),

  // Global settings
  getYoloMode: () => request<{ yolo_mode: boolean }>("/api/settings/yolo"),

  // --- Browser (W4) ---
  getBrowserSettings: () =>
    request<{
      binary_override: string;
      override_source: "env" | "persisted" | "none";
      resolved_binary: string | null;
      detected: { name: string; path: string }[];
      runtime: BrowserRuntimeInfo;
    }>("/api/settings/browser"),
  updateBrowserSettings: (binaryOverride: string) =>
    request<{
      binary_override: string;
      override_source: "env" | "persisted" | "none";
      resolved_binary: string | null;
      detected: { name: string; path: string }[];
      runtime: BrowserRuntimeInfo;
    }>("/api/settings/browser", {
      method: "PUT",
      body: JSON.stringify({ binary_override: binaryOverride }),
    }),
  installBrowserRuntime: () =>
    request<{
      status: string;
      version?: string;
      binary?: string;
      detail?: string;
    }>("/api/browser/runtime/install", { method: "POST" }),
  removeBrowserRuntime: () =>
    request<{ status: string }>("/api/browser/runtime", { method: "DELETE" }),
  listBrowserProfiles: () =>
    request<
      {
        id: string;
        name: string;
        allowed_domains: string[];
        description: string | null;
      }[]
    >("/api/browser/profiles"),
  createBrowserProfile: (
    name: string,
    allowedDomains: string[],
    description?: string,
  ) =>
    request<{ id: string }>("/api/browser/profiles", {
      method: "POST",
      body: JSON.stringify({
        name,
        allowed_domains: allowedDomains,
        description: description || null,
      }),
    }),
  deleteBrowserProfile: (id: string) =>
    request<{ deleted: string }>(`/api/browser/profiles/${id}`, {
      method: "DELETE",
    }),

  setYoloMode: (enabled: boolean) =>
    request<{ yolo_mode: boolean }>("/api/settings/yolo", {
      method: "PUT",
      body: JSON.stringify({ yolo_mode: enabled }),
    }),
};

/** PreviewBackend implementations — one per content root. */
export function workspaceBackend(agentId: string): PreviewBackend {
  return {
    preview: (source) => api.previewFile(agentId, source),
    blob: (source) => api.fetchFileBlob(agentId, source),
    pdfPage: (page, source) => api.fetchPdfPage(agentId, page, source),
  };
}

export function skillBackend(
  skillId: string,
  revision?: number,
): PreviewBackend {
  return {
    preview: (source) =>
      api.previewSkillResource(skillId, { ...source, revision }),
    blob: (source) => api.fetchSkillBlob(skillId, { ...source, revision }),
    pdfPage: (page, source) =>
      api.fetchSkillPdfPage(skillId, page, { ...source, revision }),
  };
}
