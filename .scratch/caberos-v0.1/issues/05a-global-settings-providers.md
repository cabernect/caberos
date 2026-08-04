# 05a — Global settings & provider management

**What to build:** A dedicated Settings page accessible from the dashboard sidebar (`/settings`). This is the global "management" surface for things that are NOT per-agent — primarily model providers. The operator can add/edit/delete providers (OpenAI, Anthropic, Ollama, etc.), rotate API keys without restart, discover available models, and test connections. This is separate from the per-agent settings overlay (ticket 05) which configures soul/persona/task/model/capabilities for a specific agent.

**Blocked by:** 02 — Dashboard chat with real model (needs the frontend scaffold, auth, sidebar, and provider API to exist).

**Status:** ready-for-agent

- [ ] Settings page at `/settings` — accessible from the dashboard sidebar "Settings" nav item. Uses the same `DashboardSidebar` layout as the agents page.
- [ ] Provider list — cards for each provider showing name, type (openai/anthropic/ollama/etc), key status (set/not set), base URL. Edit and delete buttons per card.
- [ ] Add provider form — inline form with: name (free text), type (dropdown: openai, anthropic, gemini, google, ollama, azure, mistral, cohere), API key (password field), base URL (optional, for Ollama or custom endpoints), org ID (optional).
- [ ] Edit provider — inline form on the card. API key field shows "leave blank to keep current" when a key is already set. Can update name, base URL, org ID, and rotate key.
- [ ] Delete provider — confirmation dialog. Backend should reject if an agent references the provider (D39).
- [ ] Discover models — button on each provider card to fetch available models via `GET /api/providers/{id}/models`. Shows discovered models as chips/badges. Dynamic discovery for OpenAI/Google/Ollama, free-text fallback for Anthropic (D40).
- [ ] Key rotation — updating the API key doesn't require a server restart. The LiteLLM adapter loads provider config at call time from the DB (D39).
- [ ] Route: `/settings` in the frontend router. Sidebar "Settings" nav item navigates there. Back to `/agents` via the sidebar.
