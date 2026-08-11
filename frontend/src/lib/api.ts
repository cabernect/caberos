// API client — the only way the frontend talks to the backend (D33)

import type { Agent, AgentVersion, Approval, CapabilityGrant, ChannelInfo, HeartbeatConfig, Limits, Message, ModelInfo, Operator, Provider, SessionInfo, Skill, SkillInfo, WorkspaceEntry } from "./types";

const BASE = ""; // same origin via Vite proxy

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status}: ${text || resp.statusText}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    request<{ operator: Operator; must_change_password: boolean }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify({ username, password }) },
    ),
  logout: () => request<{ status: string }>("/api/auth/logout", { method: "POST" }),
  me: () => request<Operator>("/api/auth/me"),

  // Agents
  listAgents: () => request<Agent[]>("/api/agents"),
  getAgent: (id: string) => request<Agent>(`/api/agents/${id}`),
  listCapabilities: () => request<{ name: string; kind: string; description: string; egress: boolean; require_approval: boolean }[]>("/api/agents/capabilities"),
  createAgent: (data: { name: string; provider_id?: string; model_name?: string; soul?: string; persona?: string; task?: string }) =>
    request<{ id: string; name: string; enabled: boolean }>("/api/agents", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateAgent: (id: string, data: {
    name?: string;
    provider_id?: string;
    model_name?: string;
    soul?: string;
    persona?: string;
    task?: string;
    capabilities?: CapabilityGrant[] | null;
    limits?: Limits;
    heartbeat?: HeartbeatConfig;
  }) =>
    request<{ id: string; version: number; version_id: string }>(`/api/agents/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  disableAgent: (id: string) =>
    request<{ id: string; enabled: boolean }>(`/api/agents/${id}/disable`, { method: "POST" }),
  enableAgent: (id: string) =>
    request<{ id: string; enabled: boolean }>(`/api/agents/${id}/enable`, { method: "POST" }),
  duplicateAgent: (id: string, newId: string, newName: string) =>
    request<{ id: string; name: string; enabled: boolean }>(`/api/agents/${id}/duplicate`, {
      method: "POST",
      body: JSON.stringify({ new_id: newId, new_name: newName }),
    }),
  exportAgent: (id: string) =>
    request<{ yaml: string }>(`/api/agents/${id}/export`),
  importAgent: (yaml: string) =>
    request<{ id: string; name: string; enabled: boolean }>("/api/agents/import", {
      method: "POST",
      body: JSON.stringify({ yaml }),
    }),
  listVersions: (id: string) =>
    request<AgentVersion[]>(`/api/agents/${id}/versions`),
  getVersion: (id: string, versionId: string) =>
    request<{ id: string; version_number: number; is_active: boolean; config: Record<string, unknown> }>(
      `/api/agents/${id}/versions/${versionId}`,
    ),
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
  listAgentSkills: (id: string) =>
    request<Skill[]>(`/api/agents/${id}/skills`),
  createAgentSkill: (id: string, name: string, content?: string) =>
    request<{ name: string; path: string }>(`/api/agents/${id}/skills`, {
      method: "POST",
      body: JSON.stringify({ name, content: content || "" }),
    }),
  deleteAgentSkill: (id: string, skillName: string) =>
    request<{ ok: boolean }>(`/api/agents/${id}/skills/${skillName}`, { method: "DELETE" }),
  listWorkspace: (id: string, path?: string) =>
    request<{ type: "dir" | "file"; path: string; entries?: WorkspaceEntry[]; content?: string; size?: number }>(
      `/api/agents/${id}/workspace${path ? `?path=${encodeURIComponent(path)}` : ""}`,
    ),

  // Chat — POST /message starts a run, returns {run_id, session_id}
  sendMessage: (
    agentId: string,
    text: string,
    isTest = false,
    modelOverride?: { provider_id: string; name: string; thinking_enabled?: boolean | null; thinking_effort?: string | null },
    sessionId?: string,
    attachments?: { type: string; mime_type: string; data: string; filename: string }[],
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
    const resp = await fetch(
      `${BASE}/api/chat/${agentId}/runs/${runId}/events`,
      {
        credentials: "include",
        headers: lastEventId > 0 ? { "Last-Event-ID": String(lastEventId) } : {},
        signal,
      },
    );
    if (!resp.ok) {
      const errorText = await resp.text().catch(() => "");
      throw new Error(`${resp.status}: ${errorText || resp.statusText}`);
    }
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
          if (line.startsWith("id: ")) eventId = parseInt(line.slice(4), 10) || 0;
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
    request<{ run_id: string; session_id: string; agent_id: string; status: string; event_count: number }>(
      `/api/chat/${agentId}/runs/${runId}`,
    ),
  stopRun: (agentId: string, runId: string) =>
    request<{ status: string }>(`/api/chat/${agentId}/runs/${runId}/stop`, { method: "POST" }),
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
  getSessionMessages: (agentId: string, sessionId: string, limit = 100) =>
    request<Message[]>(
      `/api/chat/${agentId}/sessions/${sessionId}/messages?limit=${limit}`,
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

  // Providers
  listProviders: () => request<Provider[]>("/api/providers"),
  createProvider: (data: Partial<Provider> & { api_key?: string }) =>
    request<Provider>("/api/providers", { method: "POST", body: JSON.stringify(data) }),
  updateProvider: (id: string, data: Partial<Provider> & { api_key?: string }) =>
    request<Provider>(`/api/providers/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteProvider: (id: string) =>
    request<{ status: string }>(`/api/providers/${id}`, { method: "DELETE" }),
  listModels: (id: string) =>
    request<{ discovery: string; models: ModelInfo[] }>(`/api/providers/${id}/models`),
  addCustomModel: (id: string, modelName: string) =>
    request<{ custom_models: string[] }>(`/api/providers/${id}/models`, {
      method: "POST",
      body: JSON.stringify({ model_name: modelName }),
    }),
  removeCustomModel: (id: string, modelName: string) =>
    request<{ custom_models: string[] }>(`/api/providers/${id}/models/${encodeURIComponent(modelName)}`, {
      method: "DELETE",
    }),

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
      body: JSON.stringify({ remember, remember_scope: rememberScope, remember_pattern: rememberPattern }),
    }),
  rejectCall: (id: string) =>
    request<{ status: string }>(`/api/approvals/${id}/reject`, { method: "POST" }),

  // Elicitation
  respondToElicitation: (id: string, response: string) =>
    request<{ status: string }>(`/api/elicitation/${id}/respond`, {
      method: "POST",
      body: JSON.stringify({ response }),
    }),

  // Skills management (system-level)
  listSkills: () =>
    request<{ skills: SkillInfo[]; count: number }>("/api/skills"),
  importSkillZip: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return fetch("/api/skills/import", {
      method: "POST",
      credentials: "include",
      body: formData,
    }).then(async (r) => {
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        throw new Error(`${r.status}: ${text || r.statusText}`);
      }
      return r.json();
    });
  },
  deleteSkill: (name: string) =>
    request<{ deleted: boolean; name: string }>(`/api/skills/${name}`, {
      method: "DELETE",
    }),
  promoteSkill: (name: string, agentId: string) =>
    request<{ promoted: boolean; name: string }>(`/api/skills/${name}/promote?agent_id=${agentId}`, {
      method: "POST",
    }),

  // Scheduler — heartbeat
  listHeartbeats: () =>
    request<HeartbeatStatus[]>("/api/scheduler/heartbeat"),
  updateHeartbeat: (agentId: string, data: Partial<HeartbeatConfig>) =>
    request<{ agent_id: string; version: number; heartbeat: HeartbeatConfig }>(
      `/api/scheduler/heartbeat/${agentId}`,
      { method: "PUT", body: JSON.stringify(data) },
    ),
  fireHeartbeat: (agentId: string) =>
    request<{ run_id: string; session_id: string; status: string; cost: number; error: string | null }>(
      `/api/scheduler/heartbeat/${agentId}/fire`,
      { method: "POST" },
    ),
  listSchedulerAlerts: () =>
    request<SchedulerAlert[]>("/api/scheduler/alerts"),
  clearSchedulerAlert: (agentId: string) =>
    request<{ agent_id: string; cleared: boolean }>(
      `/api/scheduler/alerts/${agentId}/clear`,
      { method: "POST" },
    ),

  // MCP servers
  listMcpServers: () =>
    request<McpServerInfo[]>("/api/mcp/servers"),
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
    request<{ id: string; name: string; connected: boolean }>("/api/mcp/servers", {
      method: "POST",
      body: JSON.stringify(data),
    }),
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
    request<{ id: string; connected: boolean }>(`/api/mcp/servers/${id}/connect`, {
      method: "POST",
    }),
  updateMcpServer: (id: string, data: { require_approval?: boolean; enabled?: boolean }) =>
    request<{ id: string; require_approval: boolean; enabled: boolean; connected: boolean }>(
      `/api/mcp/servers/${id}`,
      { method: "PATCH", body: JSON.stringify(data) },
    ),
  storeMcpCredential: (serverId: string, data: {
    credential_type: string;
    value: string | Record<string, unknown>;
    label?: string;
  }) =>
    request<{ id: string; credential_type: string; label: string | null; connected: boolean }>(
      `/api/mcp/servers/${serverId}/credentials`,
      { method: "POST", body: JSON.stringify(data) },
    ),
  listMcpCredentials: (serverId: string) =>
    request<{ id: string; credential_type: string; label: string | null; created_at: string }[]>(
      `/api/mcp/servers/${serverId}/credentials`,
    ),
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
    return request<McpCatalogEntry[]>(
      `/api/mcp/catalog${qs ? "?" + qs : ""}`,
    );
  },
  listMcpCatalogCategories: () =>
    request<{ name: string; count: number }[]>("/api/mcp/catalog/categories"),
  installFromCatalog: (name: string) =>
    request<{ id: string; name: string; connected: boolean; auth_type: string; message: string | null }>(
      "/api/mcp/catalog/install",
      { method: "POST", body: JSON.stringify({ name, enabled: true }) },
    ),

  // Channels (external messaging — Telegram, Discord, Zalo, ...)
  listChannels: () =>
    request<ChannelInfo[]>("/api/channels"),
  createChannel: (data: { platform: string; agent_id: string; bot_token: string; webhook_secret?: string; mode?: string }) =>
    request<ChannelInfo>("/api/channels", { method: "POST", body: JSON.stringify(data) }),
  updateChannel: (id: string, data: { bot_token?: string; webhook_secret?: string; enabled?: boolean; mode?: string }) =>
    request<ChannelInfo>(`/api/channels/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteChannel: (id: string) =>
    request<{ status: string }>(`/api/channels/${id}`, { method: "DELETE" }),
  testChannel: (id: string, chat_id: string) =>
    request<{ success: boolean; error: string | null }>(`/api/channels/${id}/test`, {
      method: "POST",
      body: JSON.stringify({ chat_id }),
    }),
};
