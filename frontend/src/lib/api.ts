// API client — the only way the frontend talks to the backend (D33)

import type { Agent, Message, ModelInfo, Operator, Provider } from "./types";

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

  // Chat
  sendMessage: (agentId: string, text: string, isTest = false) =>
    request<{ message_id: string; status: string }>(
      `/api/chat/${agentId}/message`,
      { method: "POST", body: JSON.stringify({ text, is_test: isTest }) },
    ),
  getHistory: (agentId: string, limit = 50) =>
    request<Message[]>(`/api/chat/${agentId}/history?limit=${limit}`),

  // Providers
  listProviders: () => request<Provider[]>("/api/providers"),
  createProvider: (data: Partial<Provider> & { api_key?: string }) =>
    request<Provider>("/api/providers", { method: "POST", body: JSON.stringify(data) }),
  deleteProvider: (id: string) =>
    request<{ status: string }>(`/api/providers/${id}`, { method: "DELETE" }),
  listModels: (id: string) =>
    request<{ discovery: string; models: ModelInfo[] }>(`/api/providers/${id}/models`),
};

// SSE helper — returns an EventSource for the agent stream
export function openStream(agentId: string): EventSource {
  return new EventSource(`${BASE}/api/chat/${agentId}/stream`, {
    withCredentials: true,
  });
}
