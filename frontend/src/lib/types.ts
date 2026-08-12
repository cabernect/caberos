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
  supports_vision?: boolean;
  supports_thinking?: boolean;
  thinking_efforts?: string[];
  max_context_tokens?: number | null;
  max_output_tokens?: number | null;
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
  compaction?: CompactionConfig;
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

export interface CompactionConfig {
  auto_compaction: boolean;
  threshold: number;
  protect_first_n: number;
  protect_last_n: number;
  tail_budget_fraction: number;
  prune_tool_results_over: number;
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

export interface SkillInfo {
  name: string;
  description: string;
  source: string;
  path: string;
  resource_count: number;
  license?: string;
  compatibility?: string;
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
  attachments?: string | null;
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
  session_id?: string;
  status: string;
  total_cost?: number;
  total_turns?: number;
  error?: string;
  context_tokens?: number;
  max_context_tokens?: number;
  compacted?: boolean;
  context_breakdown?: {
    system_prompt: number;
    conversation: number;
    tools: number;
  };
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

export interface HeartbeatStatus {
  agent_id: string;
  agent_name: string;
  enabled: boolean;
  interval_minutes: number;
  task_prompt: string;
  max_cost_per_heartbeat: number;
  consecutive_failure_threshold: number;
  last_fired: string | null;
  last_status: string | null;
  last_error: string | null;
  consecutive_failures: number;
  next_fire: string | null;
}

export interface SchedulerAlert {
  agent_id: string;
  agent_name: string;
  consecutive_failures: number;
  threshold: number;
  last_error: string | null;
  timestamp: string;
}

export interface McpServerInfo {
  id: string;
  name: string;
  transport: string;
  command: string | null;
  args: string[] | null;
  url: string | null;
  enabled: boolean;
  connected: boolean;
  tool_count: number;
  tool_filter: string[] | null;
  require_approval: boolean;
  env_template: Record<string, string> | null;
  oauth_config: { scope?: string; redirect_uri?: string } | null;
  auth_type: "api_key" | "oauth" | "none";
  has_credentials: boolean;
  created_at: string | null;
}

export interface McpToolInfo {
  id: string;
  tool_name: string;
  capability_name: string;
  description: string;
  parameters_schema: Record<string, unknown>;
  egress: boolean;
  require_approval: boolean;
  subject_scoped: boolean;
}

export interface McpCatalogEntry {
  name: string;
  category: string;
  description: string;
  transport: string;
  command: string | null;
  args: string[] | null;
  url: string | null;
  auth_type: string; // "none", "api_key", "oauth"
  env_template: Record<string, string> | null;
  vendor: string;
  homepage: string;
}

export interface ChannelInfo {
  id: string;
  platform: string;
  agent_id: string;
  enabled: boolean;
  mode: string; // "polling" or "webhook"
  webhook_secret: string;
  webhook_url: string;
  has_token: boolean;
  extra_config: Record<string, unknown> | null;
}

// Observability (Ticket 09)

export interface RunSummary {
  id: string;
  agent_id: string;
  agent_name: string | null;
  session_id: string;
  status: string;
  trigger: string;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  latency_ms: number;
  is_test: boolean;
  started_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface MessageOut {
  id: string;
  run_id: string;
  role: string;
  content: string;
  seq: number;
  created_at: string;
  subagent_id: string | null;
}

export interface AuditOut {
  id: string;
  run_id: string;
  agent_id: string;
  capability_name: string;
  allowed: boolean;
  denied_reason: string | null;
  cost: number;
  latency_ms: number;
  args: string;
  result: string | null;
  created_at: string | null;
}

export interface RunDetail {
  id: string;
  agent_id: string;
  agent_name: string | null;
  session_id: string;
  status: string;
  trigger: string;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  latency_ms: number;
  is_test: boolean;
  started_at: string;
  completed_at: string | null;
  error: string | null;
  messages: MessageOut[];
  audit_records: AuditOut[];
}

export interface SpendBreakdown {
  agent_id: string;
  agent_name: string | null;
  total_cost: number;
  run_count: number;
  tokens_in: number;
  tokens_out: number;
}

export interface SpendSummary {
  total_cost: number;
  total_runs: number;
  total_tokens_in: number;
  total_tokens_out: number;
  by_agent: SpendBreakdown[];
  by_trigger: Record<string, number>;
}

export interface OperatorAuditOut {
  id: string;
  operator_id: string;
  action: string;
  target: string;
  created_at: string;
}

export interface HealthStatus {
  status: string;
  database: string;
  providers: number;
  agents: number;
  active_runs: number;
  timestamp: string;
}
