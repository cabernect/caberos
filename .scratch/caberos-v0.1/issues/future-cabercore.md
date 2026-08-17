# Future — CaberCore and entrypoint seam

**What to build:** Make CaberCore independently usable without a browser, FastAPI, Tauri, or any other user interface. CaberCore is the source of truth for agent execution, context assembly, memory, syscall mediation, approvals, persistence, scheduling, MCP, channels, and observability. FastAPI/REST/SSE, Tauri, CLI, and future integrations must be adapters or entry points over CaberCore rather than owners of its behavior.

**Status:** deferred until a non-HTTP entry point requires the seam

- [ ] CaberCore interface: define a small application-facing interface for starting CaberCore, submitting inbound events, receiving streaming events/results, and shutting down cleanly.
- [ ] Startup ownership: move transport-independent initialization out of FastAPI-specific wiring into a reusable CaberCore bootstrap. Preserve database initialization, capability registration, stuck-run recovery, session sweeping, heartbeat scheduling, MCP connections, and enabled external channels.
- [ ] Event model: define transport-independent inbound events for user messages, heartbeats, and external-channel messages, including agent, contact, session, attachments, and trigger metadata.
- [ ] Execution seam: make the existing pipeline callable through the CaberCore interface without importing FastAPI, React, browser code, or Tauri code.
- [ ] Policy preservation: approvals, guardrails, subject scoping, credential custody, syscall auditing, cost limits, turn limits, and error handling must remain enforced regardless of the entry point.
- [ ] FastAPI adapter: refactor REST/SSE routes to delegate to the CaberCore interface. Keep HTTP serialization, authentication, pagination, and SSE formatting in the adapter layer.
- [ ] Non-HTTP adapter proof: add a small scripted or CLI-style adapter test that submits an event directly through the CaberCore interface and receives the same pipeline result and audit records.
- [ ] Lifecycle: define ownership for CaberCore startup, shutdown, background tasks, active runs, crash recovery, and reconnect when multiple adapters use CaberCore.
- [ ] Data ownership: keep database, memory files, workspaces, credentials, and audit records behind CaberCore services; adapters must not access storage directly.
- [ ] Documentation: document the CaberCore/adapter seam, supported entry points, event contracts, lifecycle rules, and the transport choices available to Tauri and CLI.

**Out of scope:** Building the Tauri desktop shell, building the CLI, changing the agent pipeline's product behavior, replacing FastAPI/REST/SSE, or adding a second agent execution implementation.
