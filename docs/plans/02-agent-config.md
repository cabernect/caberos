# 02 — Agent Configuration

## Goal

Define the Pydantic models that validate agent configurations, implement YAML import/export, and build the versioning system (immutable version rows, active pointer, diff, rollback). This is what makes an agent a config row, not a program (D1, D25).

## Spec references

- **D1** — Agents are configuration, not code
- **D25** — Agent configuration lives in the database (version rows, active_version pointer, YAML for import/export)
- **D8** — Contact has optional binding to an internal record
- **D9** — One capability concept, five kinds (v0.1: tool, sub_agent, memory, connector_action)
- **D12** — Sub-agents: no channel, no session, no min_role fields
- **Stories 1-11** — create, task, capabilities, scope, model, limits, versioning, diff, rollback, disable
- **Stories 31-32** — duplicate agent, export/import

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs Agent and AgentVersion tables

## Tasks

### 1. Define Pydantic config models

`backend/src/agentos/config_schema.py`:

```python
class ChannelBinding(BaseModel):
    type: Literal["dashboard_chat"]  # extensible
    # channel-specific fields added later

class ModelConfig(BaseModel):
    provider_id: str  # references a ProviderConfig (Decision 17) — not a raw provider string
    name: str         # model name: "gpt-4o", "claude-3-5-sonnet", "llama3.1:70b"
    temperature: float = 0.3
    max_tokens: int | None = None
    # Agents reference a configured provider by id. The provider holds the
    # encrypted key, base_url, org_id, etc. LiteLLM is the transport (Decision 17).

class CapabilityGrant(BaseModel):
    name: str  # e.g. "email.read", "shell.run"
    subject: Literal["self", "any", "none"] = "none"
    require_approval: bool = False

class Limits(BaseModel):
    max_turns_per_run: int = 12
    max_cost_per_run: float = 500
    session_idle_timeout_min: int = 60
    max_context_tokens: int = 24000

class Fallback(BaseModel):
    on_unsupported_message: str = "Sorry, I can't handle that yet..."
    on_limit_exceeded: Literal["tell_user_and_stop", "handoff_to_human"] = "tell_user_and_stop"

class HeartbeatConfig(BaseModel):
    enabled: bool = False
    interval_minutes: int = 60
    task_prompt: str = ""
    max_cost_per_heartbeat: float = 0.50
    consecutive_failure_threshold: int = 3  # Decision 14

class AgentConfig(BaseModel):
    id: str
    name: str
    channels: list[ChannelBinding]
    workspace: str  # path to workspace directory (working files only — D37)
    model: ModelConfig
    soul: str       # agent identity: who the agent is, values, principles (D35). Versioned config field.
    persona: str    # agent personality: tone, voice, style (D35). Versioned config field.
    task: str       # task instructions: what the agent does (D35). Versioned config field.
    capabilities: list[CapabilityGrant]
    limits: Limits
    fallback: Fallback
    heartbeat: HeartbeatConfig = HeartbeatConfig()  # D31

class SubAgentConfig(BaseModel):
    id: str
    name: str
    task: str       # sub-agent task instructions (D35)
    capabilities: list[str]  # capability names
    model: ModelConfig | None = None
    # Validator: reject if channels, workspace, or session fields present (D12)
```

### 1b. Agent memory (note — not part of AgentConfig)

MEMORY.md is a separate store, NOT part of `AgentConfig`. It's a markdown file in the agent home dir (`~/agentos/agents/{agent_id}/MEMORY.md`), not in the DB and not in the workspace:

- **`MEMORY.md`** — curated memory (agent-managed). The agent's curated knowledge about the user, updated over time. A living document — not versioned with `AgentVersion` saves, because the agent updates it freely during runs. Belongs to the agent, so private per-agent even when workspaces are shared (D37).

`AgentConfig` does not store MEMORY.md — it is loaded at runtime by the harness (see plan 03, context assembly) as a file read. The dashboard surfaces it for editing via a dedicated memory API (see plan 11).

### 1c. Provider configuration (Decision 17, 18)

Providers are first-class, stored in the DB with encrypted keys. Agents reference a provider by id (`ModelConfig.provider_id`). LiteLLM is the transport — we manage the key/config per call.

```python
class ProviderConfig(BaseModel):
    id: str
    name: str                       # "my-openai-personal", "local-ollama", "work-anthropic"
    type: str                       # "openai", "anthropic", "google", "ollama", "azure", ...
    api_key: str | None = None      # encrypted in DB (Fernet, plan 10 secret store); None for local
    base_url: str | None = None     # for Ollama (http://localhost:11434), Azure, custom endpoints
    org_id: str | None = None       # OpenAI/Anthropic org
    extra_params: dict = {}         # provider-specific: project_id, api_version, etc.
```

- Multiple providers of the same `type` are allowed (personal vs work OpenAI key).
- `api_key` is encrypted at rest via the same Fernet secret store used for connectors (plan 10). Never returned to the dashboard or logs in plaintext.
- Local providers (Ollama) have no `api_key`, just a `base_url`.

**Model discovery (Decision 18):** dynamic where available, free-text fallback, always allow override.

```python
class ProviderConfig(BaseModel):
    ...
    async def list_models(self) -> list[str] | None:
        """Return available models, or None if the provider has no list endpoint."""
        # openai:  GET /v1/models
        # google:  GET /v1/models
        # ollama:  GET /api/tags   (lists locally pulled models)
        # azure:   GET /openai/deployments
        # anthropic: None (no list endpoint) → free-text
```

- When the user configures a provider, try `list_models()`. If it returns a list → dropdown. If `None` or the call fails → free-text input.
- Always show a "type your own" override, even when a list is available (for brand-new models not yet in the API's list).
- **Validation at save time:** when an agent is saved, do a cheap 1-token completion against the chosen `provider_id` + `model.name`. Typos fail at config time, not at 3am during a heartbeat run.

### 2. Implement config validation

- On save: validate `AgentConfig` against Pydantic model
- Check all granted capabilities exist in the capability registry
- Check `model.provider_id` references an existing `ProviderConfig`
- Validate the model string with a cheap 1-token completion (Decision 18)
- Check workspace path is valid and creatable
- Check sub-agent configs don't carry channel/session fields (D12 rule 1)
- Return clear, field-level error messages for the dashboard

### 3. Implement versioning

`backend/src/agentos/agent_service.py`:
- `save_agent(config: AgentConfig)` → creates new AgentVersion row, advances `active_version` pointer
- `get_agent(id)` → returns active version's config
- `list_versions(agent_id)` → returns all versions ordered by number
- `diff_versions(v1_id, v2_id)` → returns structured diff of config fields
- `rollback_to(agent_id, version_id)` → sets `active_version` to the specified version (creates a new version row that copies the old config, so history is linear)
- `disable_agent(agent_id)` → sets `enabled = false` on the Agent row
- `duplicate_agent(agent_id, new_id)` → copies active config to a new agent
- `export_agent(agent_id)` → returns YAML string
- `import_agent(yaml_str)` → validates and saves

### 4. Implement YAML import/export

- Use `pyyaml` for serialization
- Export: `AgentConfig` → dict → YAML (matches the format in D25)
- Import: YAML → dict → `AgentConfig` (validated) → save
- Round-trip safe: export then import produces identical config

### 5. Create API routes (control plane)

`backend/src/agentos/api/agents.py`:
- `POST /api/agents` — create agent from config
- `GET /api/agents` — list all agents (id, name, enabled, active_version, today's spend)
- `GET /api/agents/{id}` — get agent detail (active config)
- `PUT /api/agents/{id}` — save new version
- `GET /api/agents/{id}/versions` — list versions
- `GET /api/agents/{id}/versions/{v1}/diff/{v2}` — diff
- `POST /api/agents/{id}/rollback/{version_id}` — rollback
- `POST /api/agents/{id}/disable` — disable
- `POST /api/agents/{id}/duplicate` — duplicate
- `GET /api/agents/{id}/export` — export YAML
- `POST /api/agents/import` — import YAML

`backend/src/agentos/api/providers.py` (Decision 17, 18):
- `POST /api/providers` — create a provider config (key encrypted on write)
- `GET /api/providers` — list providers (name, type, base_url — never the key)
- `GET /api/providers/{id}` — get provider detail (key redacted)
- `PUT /api/providers/{id}` — update provider (rotate key, change base_url — no restart)
- `DELETE /api/providers/{id}` — delete provider (reject if an agent references it)
- `GET /api/providers/{id}/models` — discover models. Returns `{ "models": [...], "discovery": "dynamic" | "unavailable" }`
- `POST /api/providers/{id}/test` — cheap 1-token completion to validate the key + base_url

## Files to create

- `backend/src/agentos/config_schema.py`
- `backend/src/agentos/provider_service.py` — provider CRUD, model discovery, LiteLLM config assembly
- `backend/src/agentos/agent_service.py`
- `backend/src/agentos/api/agents.py`
- `backend/src/agentos/api/providers.py`
- `backend/tests/test_agent_config.py`
- `backend/tests/test_providers.py`

## Verification

- Load the sample YAML from D25 → validates successfully
- Save an agent → creates version 1, active_version points to it
- Save again with modified task → creates version 2, active_version advances
- Diff versions 1 and 2 → shows task changed
- Rollback to version 1 → active_version points to v1, new version 3 created with v1's config
- Export to YAML → import → produces identical config
- Sub-agent config with `channels` field → validation error
- Capability grant referencing non-existent capability → validation error
- Create a provider with an API key → key encrypted in DB, redacted in API responses
- Create two OpenAI providers (personal + work) → both usable, agents reference by id
- Ollama provider (no key, base_url set) → `GET /api/providers/{id}/models` lists locally pulled models
- Anthropic provider → `GET /api/providers/{id}/models` returns `discovery: "unavailable"` → free-text
- Agent referencing a non-existent `provider_id` → validation error
- Agent with a typo'd model name → save fails with a clear error (1-token validation)
- `uv run pytest tests/test_agent_config.py tests/test_providers.py` passes

## Cross-references

- Plan 07 — Pipeline (new)
- Plan 10 — Connectors (was plan 07)
- Plan 11 — Memory (was plan 08)
