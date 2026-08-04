// API client — the only way the frontend talks to the backend (D33)

import type { Agent, AgentVersion, Approval, CapabilityGrant, HeartbeatConfig, Limits, Message, ModelInfo, Operator, Provider, SessionInfo, Skill, WorkspaceEntry } from "./types";

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
  listSkills: (id: string) =>
    request<Skill[]>(`/api/agents/${id}/skills`),
  createSkill: (id: string, name: string, content?: string) =>
    request<{ name: string; path: string }>(`/api/agents/${id}/skills`, {
      method: "POST",
      body: JSON.stringify({ name, content: content || "" }),
    }),
  deleteSkill: (id: string, skillName: string) =>
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
    modelOverride?: { provider_id: string; name: string },
    sessionId?: string,
    attachments?: { type: string; mime_type: string; data: string; filename: string }[],
    newSession = false,
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
        }),
      },
    ),

  // Stream run events via SSE (reconnectable with Last-Event-ID)
  streamRunEvents: async function* (
    agentId: string,
    runId: string,
    lastEventId = 0,
  ): AsyncGenerator<{ event: string; data: any; id: number }> {
    const resp = await fetch(
      `${BASE}/api/chat/${agentId}/runs/${runId}/events`,
      {
        credentials: "include",
        headers: lastEventId > 0 ? { "Last-Event-ID": String(lastEventId) } : {},
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
  approveCall: (id: string, remember = false) =>
    request<{ status: string }>(`/api/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ remember }),
    }),
  rejectCall: (id: string) =>
    request<{ status: string }>(`/api/approvals/${id}/reject`, { method: "POST" }),

  // Elicitation
  respondToElicitation: (id: string, response: string) =>
    request<{ status: string }>(`/api/elicitation/${id}/respond`, {
      method: "POST",
      body: JSON.stringify({ response }),
    }),
};
