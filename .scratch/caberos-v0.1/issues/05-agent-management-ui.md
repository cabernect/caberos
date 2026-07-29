# 05 — Agent management UI

**What to build:** The operator can create a new agent from the dashboard, configure everything about it (soul, persona, task, model, capabilities, limits, fallback, heartbeat), save it, see version history, diff two versions, rollback, duplicate, export to YAML, and import from YAML. Provider management (add OpenAI key, add Ollama base_url, rotate keys) is also here. This is the "management" surface — the conversation view (ticket 02) is the "use" surface. Both are accessible from the agent list.

**Blocked by:** 02 — Dashboard chat with real model (needs the frontend scaffold, auth, and API to exist).

**Status:** ready-for-agent

- [ ] Agent list page: cards for each agent (name, enabled status, active version, today's spend). "Create agent" button. Click an agent → conversation view. Settings icon → settings sidebar.
- [ ] Agent settings sidebar (right slide-in overlay): form with soul (markdown editor), persona (markdown editor), task (markdown editor), model config, capabilities (checkbox list grouped by kind), limits, fallback, heartbeat config. Save → new AgentVersion created. Diff visible.
- [ ] Model selector: provider dropdown (from configured providers) + model selector. Dynamic discovery where available (dropdown), free-text fallback, "type your own" override. Save validates with 1-token completion.
- [ ] Provider management: Settings page for providers. Create (name, type, API key, base_url, org_id), list (key redacted), update (rotate key — no restart), delete (reject if an agent references it). Test connection button.
- [ ] Version history: list of versions, diff view between two versions (structured diff of config fields), rollback button (creates a new version row copying the old config — history is linear).
- [ ] Duplicate agent: copies active config to a new agent id.
- [ ] YAML export/import: `GET /api/agents/{id}/export` → YAML string. `POST /api/agents/import` → validates and saves. Round-trip safe.
- [ ] Disable agent: `POST /api/agents/{id}/disable` → sets `enabled=false`. Disabled agents don't appear in the chat list.
- [ ] MEMORY.md editor: separate markdown editor in the settings sidebar, read/written via `GET/PUT /api/agents/{id}/memory`. NOT a config field — editing it does not create a new version. It's the agent's living notebook (file in agent home dir).
- [ ] Skills manager: list skills, create/upload a skill, delete a skill. Skills are workspace files (`workspace/skills/{agent_id}/`).
- [ ] Workspace browser: file browser tab in settings sidebar for the agent's workspace.
