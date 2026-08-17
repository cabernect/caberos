# 10 — Tauri desktop app

**What to build:** Package the existing CaberOS React dashboard as a native desktop application using Tauri. Tauri should use the existing FastAPI REST/SSE gateway exactly as the browser dashboard does. This ticket focuses on desktop packaging, gateway lifecycle, secure permissions, and desktop UX; it does not refactor the existing pipeline or introduce CaberCore yet.

**Blocked by:** 09 — Observability + spend (the desktop shell should expose the completed dashboard, including observability views).

**Status:** in-progress

- [x] Tauri foundation: add the Tauri application configuration, Rust shell, development commands, and production build commands without breaking the existing Vite browser workflow.
- [x] Gateway connection: configure the API base URL, authentication, REST requests, SSE streaming, health check, connection state, retry behavior, and clear error UI when the FastAPI gateway is unavailable.
- [x] Managed gateway option: for the packaged app, launch or attach to a local FastAPI process without requiring the user to start Uvicorn manually. Development startup and the bundled PyInstaller gateway are wired; the packaged app starts the gateway, waits for `/health`, and terminates the owned gateway process group on quit.
- [x] Startup readiness: wait for the gateway health/readiness response before enabling the dashboard; show actionable progress or failure states instead of a blank UI.
- [ ] Desktop window lifecycle: support launch, close, minimize, restore, and relaunch without interrupting active runs or losing streamed conversation state.
- [x] Secure boundary: keep agent execution, credentials, database access, and capability mediation in the FastAPI backend. Use the minimum Tauri permissions and disable unnecessary filesystem, shell, and remote-content access.
- [x] Native distribution: produce a signed or signable development artifact for the primary development platform and document packaging prerequisites for other supported platforms. The macOS `.app` bundle and `.dmg` package build successfully.
- [x] Desktop UX: provide native application metadata (name, icon, version), a sensible window size, and diagnostics/reconnect controls.
- [ ] Data lifecycle: store user data separately from the application bundle; uninstall preserves data, while an explicit “Delete all data” action removes the database, encryption key, workspaces, attachments, and agent memories after confirmation.
- [ ] Verification: launch the installed app without a manually started backend and verify login, chat streaming, tool-call visibility, approvals, memory, external-channel status, and Ticket 9 observability views. Bundled gateway startup, `/health` readiness, and shutdown/port release are verified; full feature-by-feature native verification remains.
- [x] Documentation: document local development, gateway lifecycle, build/package commands, permissions, supported platforms, data locations, uninstall behavior, and known limitations.

**Out of scope:** Extracting CaberCore, rewriting the React dashboard, moving the Python runtime into Rust, direct frontend access to the database, replacing the browser dashboard, or adding unrelated platform-specific integrations.
