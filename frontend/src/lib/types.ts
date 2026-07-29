// TypeScript types matching backend Pydantic models

export interface Operator {
  id: string;
  username: string;
  must_change_password: boolean;
}

export interface Provider {
  id: string;
  name: string;
  type: string;
  has_key: boolean;
  base_url: string | null;
  org_id: string | null;
  extra_params: Record<string, unknown>;
}

export interface ModelInfo {
  id: string;
  name: string;
}

export interface Agent {
  id: string;
  name: string;
  enabled: boolean;
  model: string | null;
  provider_id: string | null;
  soul: string;
  persona: string;
  task: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system" | "tool" | "heartbeat";
  content: string;
  created_at: string;
  run_id: string;
}

// SSE event payloads
export interface TypingEvent {
  // empty
}

export interface ThinkingEvent {
  content: string;
}

export interface TokenEvent {
  content: string;
}

export interface ToolCallEvent {
  id: string;
  capability: string;
  args: Record<string, unknown>;
  status: "pending" | "running" | "complete" | "denied";
  result?: unknown;
}

export interface TurnCompleteEvent {
  turn_number: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
}

export interface MessageCompleteEvent {
  run_id: string;
  status: string;
  total_cost?: number;
  total_turns?: number;
  error?: string;
}
