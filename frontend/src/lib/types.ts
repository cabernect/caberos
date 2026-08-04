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
  custom_models: string[];
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
  capabilities?: CapabilityGrant[] | null;
  limits?: Limits;
  heartbeat?: HeartbeatConfig;
  workspace?: string;
  sandbox_mode?: "strict" | "open";
}

export interface CapabilityGrant {
  name: string;
  subject: "self" | "any" | "none";
  require_approval: boolean;
}

export interface Limits {
  max_turns_per_run: number;
  max_cost_per_run: number;
  session_idle_timeout_min: number;
  max_context_tokens: number;
}

export interface HeartbeatConfig {
  enabled: boolean;
  interval_minutes: number;
  task_prompt: string;
  max_cost_per_heartbeat: number;
  consecutive_failure_threshold: number;
}

export interface AgentVersion {
  id: string;
  version_number: number;
  is_active: boolean;
  created_at: string;
}

export interface Skill {
  name: string;
  type: "directory" | "file";
  description: string;
}

export interface WorkspaceEntry {
  name: string;
  type: "dir" | "file";
  size: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system" | "tool" | "tool_call" | "thinking" | "heartbeat";
  content: string;
  created_at: string;
  run_id: string;
  run_status?: string;
  tokens_in?: number;
  tokens_out?: number;
  cost?: number;
  subagent_id?: string | null;
}

export interface SessionInfo {
  id: string;
  title: string;
  status: string;
  started_at: string;
  last_activity_at: string;
  message_count: number;
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
  status: "pending" | "pending_approval" | "running" | "complete" | "denied";
  result?: unknown;
  approval_id?: string;
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

export interface Approval {
  id: string;
  run_id: string;
  agent_id: string;
  capability_name: string;
  args: Record<string, unknown>;
  status: string;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
}
