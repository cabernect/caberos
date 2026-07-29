# 02 — Dashboard chat with real model

**What to build:** The first real user-facing experience. Open a browser, see the agent list, click an agent, type a message, and watch the response stream in character-by-character. The agent uses a real LLM (via LiteLLM + a configured provider with an encrypted API key) instead of the scripted double from ticket 01. The conversation view shows streaming text, typing indicator, and the agent's reply. No tool calls yet (the agent just talks), no approval flow, no memory, no heartbeat — just chat.

**Blocked by:** 01 — Smoke test vertical slice (needs the scaffold, DB, harness, pipeline, and agent config from the tracer bullet).

**Status:** ready-for-agent

- [ ] LiteLLM adapter: loads ProviderConfig from DB, decrypts API key via Fernet secret store, passes api_key/base_url/org_id/extra_params to LiteLLM's `completion()`. Supports OpenAI, Anthropic, Google, Ollama. Token usage and cost extracted from response.
- [ ] Provider management: `POST/GET/PUT/DELETE /api/providers` — create/list/update/delete providers. Keys encrypted at rest, never returned in plaintext. `GET /api/providers/{id}/models` — dynamic model discovery where available (OpenAI, Google, Ollama), free-text fallback (Anthropic), always allow override.
- [ ] Model validation at save time: cheap 1-token completion against provider_id + model name. Typos fail at config time.
- [ ] Dashboard chat channel: `POST /api/chat/{agent_id}/message` — send message. `GET /api/chat/{agent_id}/stream` — per-conversation SSE stream (stays open). SSE events: `typing`, `token`, `message_complete`. `GET /api/chat/{agent_id}/history` — conversation history.
- [ ] Frontend: React 19 + Vite + shadcn/ui + Tailwind. Agent list page (landing) → click agent → full-screen conversation view. Dark-only (D8). Ambient AI messages (no bubble), user messages right-aligned. Token streaming character-by-character. Typing indicator (3-dot pulse). Streaming cursor (blinking bar). Auto-scroll with "jump to latest" button. Chat input (sticky bottom, Enter to send, Shift+Enter for newline).
- [ ] Operator auth: session + cookie (bcrypt). Login page. Default operator seeded (admin/admin, force password change on first login).
- [ ] Contact resolution: inbound message from dashboard chat resolves to operator's contact. Session created/resumed per (contact, agent).
- [ ] `scripts/smoke.py` still works (now against the real API via HTTP, or directly through the pipeline).
