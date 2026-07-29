# Agent OS — Spec v0.1

> Status: Ready for implementation
> Supersedes: `raw_spec_need_to_be_refine.md` (retained as source material only)

---

## The model

**Agent = LLM + Harness.**

The model supplies reasoning. The harness supplies everything else: what the agent can call, what it remembers, what it may not do, how much it may spend. Change the harness and you change what the agent *is*, far more than swapping the model does.

**Agent OS ships the harness.** That is the whole idea. Because the OS supplies half of every agent, an agent becomes a configuration rather than a program, and the OS can enforce guarantees that a prompt cannot.

### Four nouns

| Noun | What it is |
|---|---|
| **Agent** | A prompt + the capabilities it may call + limits + its channel bindings + its workspace + its heartbeat config. A config row. |
| **Capability** | Anything an agent can call. One concept, several kinds. |
| **Channel** | How an agent is reached. Dashboard chat, later others. |
| **Connector** | A configured external integration: one stored credential plus the capabilities it exposes. |

Plus **Contact** for who is calling, **Session** and **Run** for what happened, and **Heartbeat** for when the agent acts on its own.

### One chokepoint, five kinds of capability

| Kind | Example | Implemented by | In v0.1 |
|---|---|---|---|
| Tool | `file.read`, `shell.run` | your code | Yes |
| Sub-agent | `research.summarize` | a model loop, pooled and shared | Yes |
| Memory | `memory.recall` | the memory store | Yes |
| Connector action | `email.read`, `calendar.create` | an external SaaS via connector | Yes |
| MCP tool | whatever the server exposes | an MCP server | v0.3 |

They differ in *implementation*, never in *treatment*. Every one is invoked through the same boundary — the **syscall layer** — which resolves who the caller is, checks permission, injects credentials, executes, and writes an audit record.

That is why the list can grow forever without the design changing. Adding Notion is a new capability, not a new subsystem. It is also why the dashboard can answer "what can any of my agents do?" on one screen.

### Why "OS", not "platform"

*Platform* implies cloud, a vendor account, and someone else's servers. This runs on your machine, and the data never leaves it.

*OS* is earned by the syscall boundary. An operating system's job is identity, permissions, resource accounting, mediated access to resources, and audit — for processes. Agent OS does the same job for agents. The name is a description, not a metaphor.

---

## Problem Statement

You want an agent that works for you — one that reads your email, manages your calendar, works with your files, and can run things on your machine. Not a chatbot that answers questions. An assistant that does work on your behalf, with your data, on your computer.

Today you have two bad options.

**Option one: a cloud assistant.** Your email, calendar, files, and conversation history leave your machine and sit on someone else's servers. The assistant can't touch your local files or run anything on your machine. It's a chat window, not an assistant. Costs are denominated in USD and unpredictable — nobody can answer "what will this cost next month?" before the invoice arrives.

**Option two: build it yourself.** You wire an LLM to your email API and a shell. It works in the demo. Then the real problems arrive, and none of them are AI problems:

- A prompt-injected email makes the agent run `rm -rf` in your home directory, because nothing stood between the model and your shell.
- The agent reads the wrong mailbox because you pasted a different account's credentials into the wrong config file.
- The agent forgets what you asked it to do five minutes ago, because nothing persists context between turns.
- The agent loops for twenty minutes running shell commands before you notice, because nothing capped the turns or the cost.
- Nobody can answer "what did my agent do yesterday, and what did it cost."
- Every new capability means another script, another copy of the API key, another thing to break.

That last one compounds. The first capability is a project. The fifth is an operations problem: five scripts in five places, five copies of the credentials, five things to look at when something breaks, and no single answer to "what is my agent allowed to do?"

None of these are agent-intelligence failures. They are **harness failures** — and a harness is exactly what nobody wants to write twice.

## Solution

**Agent OS** is a local-first, open-source daemon plus a dashboard. It hosts your personal agent on your Mac, connects it to your services (email, calendar), gives it a workspace on your filesystem, and lets it run shell commands in a sandbox. The OS supplies the harness, mediates every capability call, and gives you one dashboard to manage your agent(s).

Because the OS owns the harness, it can guarantee things no prompt can:

1. **Every caller is identified before the model runs.** Each inbound message resolves to a `Contact` — a stable identity — before a single token is spent, so a subject-scoped syscall always has someone to resolve to.
2. **The agent never names the subject of a data request.** It calls `email.read()` with no arguments. The syscall layer resolves *whose* mailbox from the session's Contact. There is no parameter through which the agent can ask for someone else's data, so prompt injection cannot produce one.
3. **Authority only ever narrows.** Agent ceiling ∩ sub-agent ceiling, evaluated per call. Nothing in the chain can widen it.
4. **Every effect is recorded.** Each inbound message becomes a `Run` carrying its syscalls, tokens, cost, and outcome.
5. **Shell runs in a sandbox.** The agent can execute commands, but only inside a sandbox bounded to its workspace — not your home directory, not your system.

---

## Architecture

### Layers

```
            ┌──────────────────────────────────────────┐
            │  DASHBOARD                               │
            │  agent list → conversation view          │
            └──────────────────────────────────────────┘
                              │  control plane socket (loopback)
┌───────────────────────────────────────────────────────────────────┐
│  GATEWAY  — the always-on daemon                                  │
│                                                                   │
│   Channels ──► Contact / Session resolution                       │
│   (dashboard chat)                                  │              │
│                                              ┌────────▼────────┐  │
│   Heartbeat ──► scheduled trigger ──────►    │  HARNESS        │  │
│   (per-agent loop)                           │  context ∙ loop │  │
│                                              │  limits         │  │
│                                              └────────┬────────┘  │
│                                                       │ syscall   │
│                                              ┌────────▼────────┐  │
│                                              │  SYSCALL LAYER  │  │
│                                              │  subject ∙ scope│  │
│                                              │  creds ∙ audit  │  │
│                                              └────────┬────────┘  │
│           ┌──────────────────────────────────────────┴────────┐  │
│           │              │              │           │          │  │
│      tools ∙ sub-agents ∙ memory ∙ connectors        │          │  │
│                                                        │          │  │
│                                              ┌─────────▼────────┐ │
│                                              │  SANDBOX         │ │
│                                              │  shell ∙ files   │ │
│                                              │  (workspace-     │ │
│                                              │   scoped)        │ │
│                                              └──────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

| Layer | Responsibility |
|---|---|
| **Channel** | Where messages enter and leave. Normalises a platform payload into an inbound message; delivers the reply under that platform's constraints. |
| **Gateway** | The always-on daemon. Hosts channels, agents, connectors, the work queue, the heartbeat scheduler, the control plane, and the dashboard. |
| **Heartbeat** | Per-agent periodic scheduler. Triggers Runs without a user message, on a configured interval. Bounded by its own cost budget. |
| **Harness** | The OS-owned execution envelope for one agent turn: context assembly, compaction, the model loop, turn and cost limits. |
| **Syscall layer** | The one boundary every capability call crosses. Resolves subject, narrows scope, authorises, injects credentials, executes, audits. |
| **Capability** | A named operation, of one of five kinds. Reachable only as a syscall. |
| **Sandbox** | Executes shell and filesystem capabilities in an isolated process, bounded to the agent's workspace. Uses the OS's native sandboxing primitive (sandbox-exec on macOS, bwrap on Linux). |
| **Provider / Model** | Where tokens come from. |

### Invariants

These hold in every version. Breaking one is a different product, not a new release.

- **I1 — Identity precedes inference.** Every caller resolves to a Contact before any model is invoked, so a subject-scoped syscall always has someone to resolve to.
- **I2 — Every effect is a syscall.** No agent-reachable path touches a resource except through the syscall layer. No privileged side door, no "internal" bypass.
- **I3 — The subject is never model-supplied.** For any scoped syscall the subject comes from the session's Contact. The agent has no parameter through which to name it.
- **I4 — Authority narrows monotonically.** `min(agent ceiling, sub-agent ceiling)`, evaluated per call. No step in a call chain can widen authority.
- **I5 — One session, one contact, one agent.** The session boundary and the security boundary are the same line.
- **I6 — Every run is accounted.** Tokens, cost, latency, syscalls, and outcome, recorded whether the run succeeded or failed.
- **I7 — Control plane and data plane never share a socket.**
- **I8 — Agents are configuration.** The OS supplies the harness. No user-supplied code executes.
- **I9 — Shell and filesystem are sandboxed.** The agent can run commands and touch files, but only inside a sandbox bounded to its workspace. No agent-reachable path escapes the sandbox to the host filesystem.

### v0.1 bindings

Everything below is a *choice for this release*, replaceable without touching an invariant. This table is the line between the architecture and the case study.

| Slot | v0.1 binding | Replaceable by |
|---|---|---|
| Channels | Dashboard chat | Zalo Bot, Telegram, web widget, email |
| Capability kinds | Tool, sub-agent, memory, MCP tool | Native connectors |
| Harness | One conversational harness (Pydantic AI) | A scheduled or batch harness |
| Store | SQLite (WAL) via SQLAlchemy | Postgres |
| Model access | LiteLLM via Pydantic AI adapter | A direct SDK, a native Pydantic AI model |
| Providers | First-class configs, encrypted keys, dynamic model discovery (D39, D40) | Env-var keys, hardcoded model lists |
| Scope vocabulary | `self`, `any` | `team`, record-level scopes |
| Dashboard | Conversation-first (agent list → full conversation view), single operator (React + Vite) | Multi-operator, remote, SSO, Canvas/A2UI |
| Clients | React dashboard (v0.1). API is client-agnostic (D33). `scripts/smoke.py` dev tool for pipeline testing. | CLI/TUI (`caber`), native macOS app, mobile app (v0.2+) |
| Sandbox | Process-level: sandbox-exec (macOS), bwrap (Linux), clean env | Docker, Podman, OpenSandbox |
| Connectors | MCP servers (email, Notion, GitHub, …), loopback OAuth redirect, encrypted credential custody | Native connectors (removed — see D13) |
| Heartbeat | Per-agent asyncio scheduler, dashboard channel delivery, consecutive-failure alert | Cron, external schedulers, multi-agent coordination |
| Frontend protocol | REST + per-conversation SSE (client-agnostic, D33) | WebSocket |
| Memory | Three-layer: working memory, MEMORY.md (agent home dir), knowledge graph. FTS5 default, embeddings configurable (D34) | Vector DB, external memory services |
| Agent identity | `soul`, `persona`, `task` — versioned config fields (D35). MEMORY.md is an agent-owned file, agent-managed (D34) | Hardcoded identity, model fine-tuning |
| Skills | Markdown prompt injection, system + per-agent (D36) | Executable plugins, MCP tools (v0.2) |
| Workspace | Shared workspace for working files only (D37). Identity is in the DB; MEMORY.md lives in the agent home dir, not the workspace. | Isolated workspaces only |
| Capabilities | `tool`, `sub_agent`, `memory`, `mcp_tool` (D38) | `connector_action` (removed) |

### Vocabulary notes

**"Harness" has three definitions in the wild.** OpenClaw's SDK uses it narrowly, for a swappable low-level turn executor (`codex`, `claude-cli`). OpenClaw's own documentation also uses it broadly, for the whole operator-controlled layer. Pydantic AI uses it for the capability library bundled around a loop. This spec uses the broad sense — everything that is not the model — and says so wherever it matters.

**"Gateway" follows OpenClaw:** the always-on daemon. The source document used it for the mediation boundary; that is now the **syscall layer**.

**Removed from the source document:** `Agent Instance`, `Workspace` (renamed — see D29), `Runtime Adapter`, `Runtime Manager`, `Plugin`, `Agent Package`, `System Agent`. Each was a noun with no behaviour attached.

### Tech stack

| Layer | Choice | Decision |
|---|---|---|
| Language | Python 3.12 | D3 |
| Package manager | uv | — |
| Web framework | FastAPI | D3 |
| ORM | SQLAlchemy 2.0 (ORM style, async) | D5 |
| DB driver | aiosqlite | D5 |
| Migrations | Alembic | D5 |
| Validation | Pydantic v2 (API, config, DTOs) | — |
| Agent harness | Pydantic AI | D2 |
| Model access | LiteLLM via Pydantic AI adapter | D6 |
| Sandbox | Process-level: sandbox-exec / bwrap (D28) | Docker, Podman, OpenSandbox |
| Testing | pytest + pytest-asyncio + httpx | — |
| Linting / types | ruff + Pyright | — |
| Logging | stdlib logging + JSON formatter | — |
| Control-plane auth | Session + cookie (bcrypt) | D4 |
| Secret encryption | cryptography (Fernet) | D13 |
| Frontend | React 19 + Vite (conversation-first, D32). One client of the API (D33). | — |
| UI library | shadcn/ui + Tailwind | — |
| Data fetching | TanStack Query + SSE for streaming | — |
| Heartbeat scheduler | asyncio task per agent (D31) | — |
| Repo structure | Monorepo (`/backend`, `/frontend`, `/docs`, `/sandbox`, `/scripts`) | — |
| Dev mode | uv + Vite dev server | — |
| Prod mode | Docker Compose | — |
| Deployment | dev script + dev Compose + prod Compose | — |

*Principle:* productivity first. Each choice is the most productive, well-supported option for its layer. Dependencies are isolated behind the OS's own interfaces (harness, sandbox, model access) so they can be replaced without a rewrite.

---

## Domain Model

Normative. These are the only nouns the implementation may use for these concepts.

| Term | Definition |
|---|---|
| **Agent** | A declarative configuration: soul, persona, task, capabilities, limits, channel bindings, workspace, heartbeat config. Not a process. |
| **Capability** | A named, permission-checked operation an agent may call. Kinds: `tool`, `sub_agent`, `memory`, `mcp_tool`. (D9, D38.) |
| **Sub-agent** | A capability whose implementation is a model loop. Lives in a shared pool, callable by many agents. Owns no Session, Contact, or channel binding. Invisible to the end user. |
| **Connector** | A configured external integration: one stored credential plus the set of capabilities it exposes. Shared across agents. |
| **Provider** | A configured model provider: type, encrypted key, optional base_url. Agents reference one by id. Shared across agents (D39). |
| **Channel** | A source of inbound messages and sink for replies. Declares its own output constraints. v0.1: dashboard chat. |
| **Gateway** | The always-on daemon hosting channels, agents, connectors, the queue, the heartbeat scheduler, the control plane, and the dashboard. |
| **Heartbeat** | A per-agent periodic scheduler that triggers Runs without a user message. Configured by interval, task prompt, and cost budget. |
| **Harness** | The OS-owned execution envelope for one agent turn: context assembly, compaction, the model loop, turn and cost limits. |
| **Syscall** | One capability invocation. |
| **Syscall layer** | The boundary every syscall crosses: resolve subject, narrow scope, authorise, inject credentials, execute, record. |
| **Contact** | A person, keyed by `(channel, bot_id, external_user_id)`. Permanent. Holds identity, an optional binding to an internal record (e.g. an email mailbox), and the message archive. |
| **Session** | One bounded conversation between a Contact and a *single* Agent. Holds working context, cost, handover state. Ends on idle timeout or resolution. |
| **Run** | One inbound message (or heartbeat trigger) → N harness iterations → one reply. The atomic unit of audit, cost, latency, and retry. Records its trigger: `user_message` or `heartbeat`. |
| **Workspace** | A filesystem directory where an agent's file and shell capabilities operate. Can be shared between agents (D37). Holds working files only — agent identity lives in the DB (D35), and MEMORY.md lives in the agent home dir (D34), neither in the workspace. Bounded by the sandbox (I9). |
| **Sandbox** | The isolated execution environment for shell and filesystem capabilities. Process-level: uses the OS's native sandboxing primitive (sandbox-exec on macOS, bwrap on Linux). Bounded to the workspace, no host network by default, no host secrets, clean env (D28). |
| **Memory** | Three layers (D34): working memory (session context), MEMORY.md (agent-curated notebook, a file in the agent home dir at `~/agentos/agents/{agent_id}/MEMORY.md`), knowledge graph (structured triples). Subject-injected: `memory.recall()` resolves whose memory from the session. Semantic recall configurable (FTS5 default, embeddings opt-in). |
| **Approval Request** | A pending human decision on a syscall marked `require_approval`. |
| **Audit Record** | An immutable row per syscall: who, as whom, what, on whose data, allowed or denied, why. Rendered in the dashboard as the syscall log. |

---

## User Stories

### Managing your agent

1. As an operator, I want to create a personal agent by filling in a form, so that I do not need to write code to launch one.
2. As an operator, I want to write the agent's system prompt in a large text field, so that I can shape its tone and behaviour.
3. As an operator, I want to tick which capabilities an agent may call from one list covering tools, sub-agents, memory, and connectors, so that its powers are explicit in one place.
4. As an operator, I want to set a subject scope (`self`, `any`) per capability, so that I control the agent's data ceiling.
5. As an operator, I want to choose the model provider and model per agent, so that I can use a cheap local model where quality allows.
6. As an operator, I want to set a maximum cost per run, so that a runaway conversation cannot generate a large bill.
7. As an operator, I want to set a maximum number of harness turns per run, so that the agent cannot loop indefinitely.
8. As an operator, I want every save to create a new version, so that I can see what changed and when.
9. As an operator, I want to see a diff between two versions, so that I can understand what someone changed.
10. As an operator, I want to roll back to a previous version with one click, so that a bad prompt change can be undone in seconds.
11. As an operator, I want to disable an agent without deleting it, so that I can take a misbehaving agent offline immediately.

### Testing your agent

12. As an operator, I want to chat with my agent directly in the dashboard, so that I can test it before connecting any external service.
13. As an operator, I want the test chat to show each syscall, its result, and its cost inline, so that I can see why the agent answered as it did.
14. As an operator, I want test conversations kept separate from real ones, so that they do not pollute history or spend reports.

### Connectors (MCP)

15. As an operator, I want to connect my Outlook or Gmail account once via an MCP server and have its tools become available to any agent, so that I do not store the same credential twice.
16. As an operator, I want the OAuth token stored encrypted and never displayed again after saving, so that a screen-share does not leak it.
17. As an operator, I want to see which agents use a given MCP server, so that I know the blast radius before revoking it.
18. As an operator, I want to revoke an MCP server in one place, so that every agent loses that access at once.

### Workspace and shell

19. As an operator, I want to set a workspace directory for the agent, so that its file and shell capabilities are bounded to one place.
20. As an operator, I want the agent to read and write files inside its workspace, so that it can work with my documents.
21. As an operator, I want the agent to run shell commands inside the sandbox, so that it can execute scripts and tools on my machine.
22. As an operator, I want dangerous shell commands to require my approval before running, so that a prompt-injected email cannot silently run `rm -rf`.
23. As an operator, I want to see which files the agent touched during a run, so that I can audit what it did.
24. As an operator, I want to see every shell command the agent ran and its output, so that I can debug or investigate.

### Memory

25. As an operator, I want the agent to remember facts across conversations, so that I do not repeat myself each session.
26. As an operator, I want to browse what the agent has stored in memory, so that I can verify it remembers the right things.
27. As an operator, I want to clear the agent's memory, so that stale or wrong facts do not persist.

### Running a fleet

28. As an operator, I want one list of every agent with its status, model, and today's spend, so that I can see the fleet without opening each one.
29. As an operator, I want to answer "what is any of my agents allowed to do?" from one screen, so that a permission audit is not five files.
30. As an operator, I want to change a model or a cost cap across several agents at once, so that a price change is one action.
31. As an operator, I want to duplicate an existing agent as a starting point, so that a second agent is faster to create than the first.
32. As an operator, I want to export an agent as a file and import it elsewhere, so that a working configuration can be shared or moved.
33. As an operator, I want to see total spend today, this week, and this month, broken down per agent, so that I can budget.

### Sub-agents

34. As an operator, I want to create a sub-agent once and let several agents call it, so that shared expertise is written in one place.
35. As an operator, I want to see which agents call a given sub-agent, so that I know what I am affecting when I edit it.
36. As an operator, I want a warning when an agent grants a sub-agent that needs capabilities the agent itself cannot grant, so that I understand why it may fail at runtime.
37. As an operator, I want the syscall log to show which sub-agent made a call, so that I can attribute behaviour precisely.

### Investigating

38. As an operator, I want to browse recent conversations, so that I can check answer quality.
39. As an operator, I want to open a conversation and see every message with timestamps, so that I can investigate a complaint.
40. As an operator, I want to see which syscalls ran during a run and what they returned, so that I can debug a wrong answer.
41. As an operator, I want to see denied syscalls and the reason, so that I can tell a misconfiguration from a bug.
42. As an operator, I want one syscall log across all agents, filterable by agent, capability, contact, and outcome, so that an incident is one query.
43. As an operator, I want everything about one run — messages, syscalls, model calls, errors — linked by a single run id, so that I do not join records by hand.
44. As an operator, I want to see how long the agent took to reply, so that I can answer "why is it slow".

### Approvals

45. As an operator, I want to approve or reject a pending syscall, so that risky actions require a human.
46. As an operator, I want to see a queue of pending approvals with the command, the agent, and the context, so that I can decide quickly.

### Keeping it running

47. As an operator, I want installation to be a small number of documented steps, so that I can do it without a systems engineer.
48. As an operator, I want all state in a single database file, so that backup is copying one file.
49. As an operator, I want messages to survive a restart, so that a crash does not lose my question.
50. As an operator, I want in-flight runs recovered or failed cleanly on startup, so that nothing hangs forever.
51. As an operator, I want to be told when something is broken rather than having to look, so that I do not discover it mid-task.
52. As an operator, I want an unreachable model provider to produce an apology to the user and a visible error, so that failure is graceful and known.

### Using your personal agent

53. As a user, I want to ask my agent to read my latest emails and summarise them, so that I can catch up quickly.
54. As a user, I want to ask my agent to draft a reply to an email, so that I do not start from a blank page.
55. As a user, I want to ask my agent to check my calendar for tomorrow, so that I know what is scheduled.
56. As a user, I want to ask my agent to create a calendar event, so that I do not switch apps.
57. As a user, I want to ask my agent to find a file in my workspace, so that I do not dig through folders.
58. As a user, I want to ask my agent to run a script in my workspace, so that it can automate a task for me.
59. As a user, I want to approve a dangerous shell command before it runs, so that I stay in control of my machine.
60. As a user, I want the agent to remember my preferences across conversations, so that I do not re-explain them.
61. As a user, I want the agent to remember what I asked it to do earlier today, so that I can refer back.
62. As a user, I want the agent to be unable to access files outside my workspace, so that my system files are safe.
63. As a user, I want the agent to be unable to send email without my approval if I configured it that way, so that it cannot act on my behalf without permission.

### Heartbeat — your agent acts on its own

64. As an operator, I want to enable a heartbeat on my agent so that it can check my email every morning without me asking.
65. As an operator, I want to set the heartbeat interval (e.g. every 30 minutes, every 2 hours) so that I control how often it runs.
66. As an operator, I want to set a cost budget per heartbeat run so that an autonomous loop cannot drain my API credits.
67. As an operator, I want heartbeat-triggered messages to appear in the conversation, tagged as heartbeat, so that I can distinguish them from my own requests.
68. As an operator, I want to disable the heartbeat temporarily so that it stops when I do not need it.
69. As an operator, I want to see heartbeat runs in the run history, filtered by trigger, so that I can audit what the agent did on its own.
70. As a user, I want my agent to proactively tell me when it finds something important during a heartbeat (e.g. an urgent email), so that I do not have to ask.

---

## Implementation Decisions

### Foundations

#### D1 — The OS ships the harness

Agent = LLM + harness. Agent OS supplies the harness, so an agent is configuration, not code.

*Why it must be owned rather than pluggable:* the guarantees in I2–I4 require the OS to construct the tool call itself. If something else builds the call, the syscall layer is advisory and every security claim degrades to "assuming the other thing behaves". A form also cannot edit a state machine, and the dashboard is the product.

*Consequence:* the source document's "Runtime Agnostic" principle is withdrawn. Model agnosticism (D6) is retained. A second harness *kind* (scheduled, batch) may be added later as an OS-owned implementation; that is not the same as a plugin point.

#### D2 — Pydantic AI is the harness implementation

Pydantic AI provides the model loop, tool-call parsing, context management, compaction, guardrails, and tool-output reduction. The OS wraps it and owns the syscall layer — subject injection, scope narrowing, credential injection, approval gating, and audit happen in the OS's code, not in Pydantic AI's.

*Rationale:* this revises the original D2, which rejected all frameworks. The context has changed: the product is a personal agent on your Mac, not a security-critical enterprise system that runs untouched for years. Productivity is the priority. Pydantic AI's `RunContext` dependency injection maps almost exactly onto I3 (subject injection), and it ships the features the spec needs (D17 compaction, D18 result reduction, D30 memory). Pydantic AI reached v2.0 in June 2026, so the 0.x versioning risk that motivated the original D2 is no longer a concern. The dependency is isolated behind the OS's harness interface, so it can be replaced without a rewrite.

*What the OS still owns:* the syscall layer constructs the actual capability calls. Pydantic AI handles the model interaction and tool-call parsing; the OS intercepts each tool call, resolves the subject, narrows scope, injects credentials, checks approval, executes, and writes the audit record. Pydantic AI never touches credentials, never resolves subjects, and never writes audit records. The security boundary is in the OS, not in the framework.

*What this replaces:* D17 (compaction) and D18 (result reduction) are now implemented via Pydantic AI's built-in features, configured through the OS's agent config. D30 (memory) uses Pydantic AI's memory primitives, wrapped in the OS's subject-injected syscall interface.

#### D3 — Python and FastAPI, one daemon

The Gateway is a single process. FastAPI serves the control plane; an in-process asyncio worker pool executes runs. One process, one binary.

Webhook handlers (when a second channel is added) verify, deduplicate, persist, and return `200`. They never execute a run. Blocking calls go to a threadpool.

*Consequence:* no horizontal scaling in v0.1. Accepted: one machine serving one operator.

#### D4 — Two planes, two sockets

| Plane | Binds to | Exposed | Carries |
|---|---|---|---|
| **Data plane** | `0.0.0.0:8080` | Yes — via outbound tunnel (when external channels are added) | Channel webhooks only |
| **Control plane** | `127.0.0.1:8081` | **Never tunnelled** | Dashboard, admin API |

In v0.1 the only channel is dashboard chat, which runs on the control plane, so the data plane socket is provisioned but idle. It exists so that adding an external channel (appendix: Zalo) is a configuration change, not an architectural one.

*Rationale:* with one socket, a tunnel that lets an external channel reach the webhook also publishes the agent-configuration API to the internet, protected by nothing but path routing. Path-based protection fails **open** under any routing mistake, framework upgrade, or added middleware. A separate listener fails **closed** — no request arrives to be misrouted.

Authentication on the control plane is required regardless: a bound socket is not an authorisation model. Operator login, operator identity on every mutating call, and an operator audit trail kept separate from the agent syscall log.

#### D5 — SQLite (WAL) is the single source of truth

All state — agents, versions, contacts, sessions, runs, messages, audit records, connectors, secrets, memory, and the work queue — lives in one SQLite database, accessed through SQLAlchemy so a move to Postgres is a configuration change.

*Rationale:* backup is copying one file, which is the entire disaster-recovery story a single operator will actually execute.

*Migration trigger:* sustained write contention, or more than one application node.

#### D6 — LiteLLM for provider access, via a Pydantic AI adapter

LiteLLM handles OpenAI, Anthropic, Gemini, Azure, OpenRouter, and Ollama behind one interface, including tool-call normalisation and token accounting.

Pydantic AI (D2) has its own model abstraction, but LiteLLM is retained for its broader provider coverage and cost accounting. A thin adapter wraps LiteLLM as a Pydantic AI `Model`, so the agent loop uses Pydantic AI's interface while the actual API call and token accounting go through LiteLLM.

Agent OS owns: the adapter, per-agent model selection, cost conversion and capping, retry and fallback, and the audit record. Every call funnels through the adapter, so LiteLLM can be replaced (or Pydantic AI's native models used directly) without a search-and-replace.

Provider credentials and endpoints are not env vars — they are first-class `Provider` entities with encrypted keys (D39). The adapter loads the agent's `provider_id`, decrypts the key, and feeds LiteLLM the right config per call.

### Identity and authority

#### D7 — Contact is identity, not authorization

A `Contact` is keyed by `(channel, bot_id, external_user_id)` and is permanent. It holds a display identity, the message archive, and an optional binding to an internal record (see D8). It carries **no role**.

There is no access ladder and no `min_role` in v0.1. Who can reach an agent is a property of the *channel*, not the agent: dashboard chat is local-only, so the operator decides who uses it. When external channels are added (appendix: Zalo), the channel's own privacy model (private bots, group membership) enforces reachability.

*Consequence:* the OS knows *who* is calling (needed for D10) but does not rank callers. Where a capability must behave differently for different people, that difference lives in the capability's subject scope (D10–D11) and in which agent the person is talking to — not in a role.

*Deferred, not denied:* role-based access, verification flows, and approval queues return when a real deployment needs them (Roadmap).

#### D8 — Subject binding

Subject-scoped capabilities (D10) resolve *whose* data to touch from the Session's Contact. That requires the Contact to be linked to an internal record — an email mailbox for `email.read()`, a calendar for `calendar.create()`. An operator makes that link by connecting a service (stories 15–16); it is plain configuration, not an approval ceremony.

- A Contact **with** a binding resolves normally.
- A Contact **without** a binding has nothing for a subject-scoped syscall to resolve to, so that syscall **fails closed** with a denied audit record. Unscoped capabilities are unaffected.

*Consequence:* the sensitive path (your email, your calendar) is safe by default — it is unreachable until an operator has deliberately bound the Contact.

#### D9 — One capability concept, four kinds

Everything an agent can call is a `Capability` with a `kind`: `tool`, `sub_agent`, `memory`, `mcp_tool`. v0.1 implements all four.

Kinds differ only in how the call is executed. Registration, permission checking, subject injection, credential injection, approval, auditing, and cost accounting are identical for all of them.

*Rationale:* this is the decision that keeps the system small as it grows. A new integration is an MCP server config plus a row in the capability registry, not a new subsystem, a new permission model, or a new place to look during an incident.

*Revision note:* the original spec had `connector_action` as a kind and deferred `mcp_tool` to v0.2. The MCP ecosystem matured (32,600+ servers, 8+ production Outlook servers) and both OpenClaw and Hermes Agent ship MCP as their sole integration path. `connector_action` is removed; `mcp_tool` is in v0.1. See D13 and D38.

#### D10 — The syscall layer injects the subject; the agent cannot name it

Subject-scoped capabilities take **no subject parameter**. The agent issues `email.read()`. The syscall layer resolves the mailbox from the Session's Contact (D8).

*Rationale:* if the agent can pass a mailbox identifier, prompt injection can change it. Removing the parameter removes the vulnerability class instead of defending against it. This is the POSIX uid rule: the caller does not assert who it is.

*Enforcement:* a subject-scoped capability whose schema exposes a subject parameter is a startup error, not a code-review convention.

#### D11 — Authority narrows monotonically

```
effective_scope = min(agent_ceiling, sub_agent_ceiling)
```

Evaluated per call, never cached. Every step in a call chain can only narrow. Scope vocabulary is closed: `self` and `any` in v0.1.

*Rationale:* an operator must be able to read a screen and understand what an agent can do. A general policy language (Rego, Cedar) fails that test — configured once by a consultant, never audited again. A closed vocabulary is also what makes story 29 renderable at all.

#### D12 — Sub-agents are pooled capabilities

A sub-agent is a `Capability` of kind `sub_agent`, defined once in a shared pool and callable by any agent granted it. It has an id, a name, a prompt, its own capability list, and optionally its own model. It has **no** channel binding and no Session.

Rules:

1. **Not an Agent.** Config load rejects a sub-agent carrying channel or session fields. Reusing the Agent entity would eventually let an operator bind a bot to one, which would break I5.
2. **Narrowing, not subsetting.** A sub-agent's grants are intersected with the calling agent's at runtime (D11). No cross-parent subset constraint, so narrowing one agent never silently breaks another. The dashboard warns at save time when a granted sub-agent may call something the agent cannot grant (story 36).
3. **Fresh context.** The sub-agent receives its own prompt plus an explicit task composed by the caller — not the raw transcript. A narrower trust boundary that inherits the wider one's context is not a boundary.
4. **Own model allowed.** Defaults to the caller's. A narrow task is a good place for a cheap model.
5. **Accounting rolls up.** Turns and tokens count against the calling Run's `max_turns_per_run` and `max_cost_per_run`. One Run, one bill.
6. **Depth capped at 2.** Narrowing makes deep nesting safe for authority but not for cost or latency.
7. **Output is data, never instructions.** The returned text enters the caller's context as an untrusted result, treated exactly like any other capability result. A pooled sub-agent reachable from many agents is a high-value injection target precisely because it is shared.
8. **Audit records carry both** `agent_id` and `sub_agent_id`.

#### D13 — CaberOS owns credential custody; MCP servers receive credentials at runtime

An MCP server is a configured integration: a process (stdio) or endpoint (HTTP) that exposes tools. CaberOS owns the credentials — OAuth tokens, API keys — encrypted in the DB (Fernet). At call time, the syscall layer decrypts the credential and injects it as an env var or header into the MCP server. The MCP server holds the credential in memory for the call; CaberOS owns it at rest.

Configuration holds `secret://` references. Values live encrypted, are decrypted only at call time inside the syscall layer, and are never returned to the dashboard, written to logs, or placed in model context.

- **OAuth flow:** CaberOS runs the loopback redirect itself (`http://localhost:8081/api/mcp/oauth/callback`), exchanges the auth code, stores the token encrypted. The MCP server never sees the OAuth flow.
- **Token refresh:** CaberOS refreshes expired tokens using the stored refresh token, updates the encrypted value, and injects the fresh token on the next call.
- **One credential backs many agents.** Connecting Outlook once makes its tools grantable to any agent. Revocation is one edit. The dashboard shows blast radius before revoking (stories 17–18).

*Revision note:* the original spec had a native `Connector` abstraction that held credentials and executed API calls directly. This is replaced by MCP servers — CaberOS owns credential custody, the MCP server handles the external API. See plan 10 for the full rationale.

### Sandbox and workspace

#### D14 — The agent has real authority, bounded by a sandbox

This inverts the original "no ambient authority" position. A personal agent that cannot touch your files or run commands on your machine is a chat window, not an assistant. The agent **does** have filesystem and shell access — but bounded:

- **Filesystem** is scoped to the agent's workspace directory (D29). The agent can read and write files inside it. It cannot name paths outside it.
- **Shell** runs inside a sandbox (D28): a restricted process that sees only the workspace, has no host network by default, and is bounded by a timeout. Uses the OS's native sandboxing primitive (sandbox-exec on macOS, bwrap on Linux) — no container runtime required.
- **Every call is still a syscall.** Mediated, audited, and subject to approval. Dangerous commands (`rm`, `curl`, `chmod`) can be marked `require_approval` per-agent or per-capability.
- **Prompt injection is the central threat.** The agent can do real damage on your machine. The sandbox, the workspace boundary, and the approval gate are the defense — not a prompt.

*What this does not change:* I2 still holds. The agent has no path to a resource that does not cross the syscall layer. The sandbox is a capability implementation, not a side door.

*Tripwire:* a capability that accepts free-form input from the model and executes it without scoping — `http.fetch(arbitrary_url)`, `sql.query(text)` against a non-workspace database — requires the same scrutiny as `shell.run`. The sandbox bounds the blast radius; it does not make arbitrary execution safe by default.

#### D28 — Shell execution is sandboxed at the process level

Shell and filesystem capabilities run inside a process-level sandbox, using the OS's native sandboxing primitive — no container runtime required. This is the same approach used by Claude Code and Codex.

- **macOS: `sandbox-exec` (Seatbelt).** Built into macOS at `/usr/bin/sandbox-exec`. Zero install. The OS generates a Seatbelt profile (SBPL) that denies all filesystem and network access by default, then allows only the workspace directory. Marked "deprecated" by Apple but relied on in production by Bazel, Nix, Homebrew, Anthropic, and OpenAI.
- **Linux/WSL2: `bubblewrap` (bwrap).** Uses Linux kernel namespaces (mount, user, PID, IPC) to create an isolated process. Available in every Linux distribution's package manager. The workspace is bind-mounted; everything else is hidden.
- **Native Windows: not supported in v0.1.** Windows users run inside WSL2, where bwrap works. This is the same constraint Claude Code and Codex impose.

Properties enforced by both backends:

- **Workspace-only filesystem.** The sandbox sees only the agent's workspace directory (D29), read-write. Nothing else from the host filesystem is visible.
- **No host network by default.** Network access is denied unless explicitly granted per-capability.
- **No host secrets.** The sandbox sees no host environment variables, no SSH keys, no OAuth tokens. Credentials are injected by the syscall layer only when a connector capability is called — not into the shell environment.
- **Process timeout.** Seatbelt and bwrap do not provide CPU/memory cgroups. A runaway process is bounded by a timeout (D18), not by resource limits. This is acceptable for a personal agent; container-based backends with cgroups are a later option (see below).

*Why process-level instead of containers:* a personal agent on a Mac does not need container isolation or resource quotas. Process-level sandboxing is instant (subprocess fork, no container startup), has zero install on macOS, and near-zero concurrency overhead. Most users will never use `shell.run` — they use MCP tools (email, calendar, Notion). The sandbox is a power-user capability, not a core dependency.

*Why not OpenSandbox:* OpenSandbox is a full platform — a separate server process, an HTTP API, an in-sandbox daemon, egress sidecars, and Kubernetes support. It solves container lifecycle at scale, which is a problem v0.1 does not have. It would add a server process and four network hops for what is a subprocess call.

*Upgrade path:* the sandbox is abstracted behind a `Sandbox` interface. If a later version needs container isolation (multi-user, untrusted code, resource quotas), a container-based backend (Docker, Podman, OpenSandbox) is plugged in as an alternative implementation — a config change, not a rewrite. This is a sandbox connector, not a core architectural change.

*Dependency:* none on macOS (`sandbox-exec` is built in). On Linux/WSL2: `bubblewrap` (`apt install bubblewrap` or equivalent). The installer checks for the platform-appropriate tool and fails with a clear message if absent.

#### D29 — Workspace is a filesystem directory (can be shared, D37)

Each agent has a workspace directory (default: `~/agentos/workspaces/{agent_id}/`). File capabilities (`file.read`, `file.write`, `file.list`) resolve paths relative to this root. A path that escapes the root (`../etc/passwd`, an absolute path) is rejected by the syscall layer before the sandbox sees it.

- The workspace is created on agent creation and removed on agent deletion (with confirmation).
- The operator can point an agent at an existing directory, so the agent can work with files the operator already has.
- Workspaces can be shared between agents (D37). The workspace holds only working files — agent identity (`soul`, `persona`, `task`) lives in the DB (D35), and MEMORY.md lives in the agent home dir (`~/agentos/agents/{agent_id}/`, D34), so both are private per-agent regardless of which workspace is shared.
- Sub-agents share the calling agent's workspace for the duration of a call; they do not get their own.

*Rationale:* the workspace is the filesystem security boundary. The agent can do anything inside it — create, edit, delete, run scripts — and nothing outside it. This is the principle that makes shell safe enough to grant: the blast radius is one directory.

### Execution

#### D15 — Session boundary equals agent boundary

A Session belongs to exactly one Contact and one Agent. Sub-agents run inside a Run and never create Sessions. Two agents means two Sessions with no shared context.

*Consequence:* the security boundary and the session boundary are the same line, which makes both checkable.

#### D16 — A fleet, not a swarm

Each agent owns its own channel binding and workspace. You choose an agent by choosing which one to talk to in the dashboard. Agents do not call each other, hand off, or share memory.

*Consequence:* **no router agent, no intent classifier, no topic-switch detection, no inter-agent protocol in v0.1.** An agent asked something outside its domain refers the user to the right agent.

*Rationale:* platform routing is free, exact, and costs no tokens. A router agent is paid, fallible, and becomes a privilege-escalation path — anything that can move a conversation between agents can move it from a read-only research agent to one with shell access.

#### D17 — Session context is compacted, with warning

A Run is bounded by `max_turns_per_run`. A **Session is not bounded at all**, and that is a defect the first talkative user will find: context grows monotonically, every run re-sends the whole history, and cost per message climbs all afternoon.

Policy: keep the last N turns verbatim; summarise everything older into a rolling summary; cap total context tokens per agent. Compaction events are recorded on the Run, and the dashboard **warns before the ceiling is reached**, not only when it is hit — quality degrades quietly otherwise.

*Implementation:* Pydantic AI (D2) provides compaction primitives; the OS configures them per-agent and records compaction events on the Run.

#### D18 — Execution limits

- **Capability timeout.** A hanging capability holds the per-Contact lock and the run never ends.
- **Result reduction at production.** An oversized capability result is truncated or summarised **when it is returned**, before it enters history. Reducing only at storage time still pays for the oversized version on every subsequent turn of the session. *Implemented via Pydantic AI's tool-output reduction (D2).*
- **Declared egress.** Each capability declares whether it leaves the machine, so the dashboard can show which ones do.

#### D19 — Execution pipeline

Every inbound message — whether from a user (via a channel) or from the heartbeat scheduler (D31) — follows exactly one path:

1. **Receive** — control-plane socket; resolve the agent from the session; parse; authenticate the operator.
2. **Deduplicate** — reject a known `message_id`.
3. **Persist and acknowledge** — store the message; return `200`; send typing indicator.
4. **Resolve Contact** — look up or create by `(channel, bot_id, external_user_id)`.
5. **Resolve Session** — resume the live session or open one.
6. **Serialise** — acquire the per-Contact lock, or queue.
7. **Assemble context** — system prompt, recent turns, rolling summary, capability schemas. Compact if needed (D17).
8. **Reason** — call the model through the owned completion function.
9. **Mediate** — for each syscall: resolve subject (D8), narrow scope (D11), authorise, request human approval if required, inject credentials, execute (sandbox for shell/files, connector for external), reduce oversized results, write audit record.
10. **Check limits** — turns and accumulated cost. On breach: fallback behaviour.
11. **Iterate** — return to step 8 until a final answer.
12. **Deliver** — enforce the channel's output constraints; send.
13. **Record** — close the Run with tokens, cost, latency, and outcome.

Steps 1–3 and 12 are channel-specific. Steps 4–11 are not, and must contain no channel-specific vocabulary.

#### D31 — Heartbeat: agents act autonomously on a schedule

An agent is not only reactive. Each agent can have a heartbeat — a periodic task loop that triggers a Run without a user message. This is what makes the system an operating system, not a chatbot: processes run continuously, not just on request.

- **Per-agent schedule.** Each agent has an optional heartbeat config: an interval (e.g. every 30 minutes, every 2 hours), a task prompt, and a budget (max cost per heartbeat run). Default: no heartbeat.
- **Trigger field on Run.** Every Run records its trigger: `user_message` or `heartbeat`. Heartbeat runs follow the same execution pipeline (D19, steps 4–13) — they are not a separate code path, just a different entry point.
- **Heartbeat prompt.** When the heartbeat fires, the harness assembles context (system prompt, recent turns, memory) and injects the heartbeat task prompt as the user message. The agent decides what to do — check email, summarise news, clean files, or nothing.
- **Budget enforcement.** Heartbeat runs are bounded by `max_cost_per_heartbeat` (separate from `max_cost_per_run`). A heartbeat that exceeds its budget is stopped, same as a user-triggered run (D18).
- **Output.** If the heartbeat run produces a result worth surfacing, it is delivered to the operator via the dashboard channel (a message appears in the conversation, tagged as heartbeat-triggered). If it produces nothing of note, it is recorded silently in the audit log.
- **Operator control.** The operator can enable/disable heartbeat per agent, change the interval, and see heartbeat runs in the run history (filtered by trigger). The heartbeat config is part of the agent's configuration (D25).

*Rationale:* a personal agent that only acts when you ask is a search bar with extra steps. An agent that checks your email every morning, notices an urgent message, and tells you about it — that is an assistant. Heartbeat is the mechanism for proactive behaviour, bounded by the same limits, audit, and approval gates as user-triggered runs.

*Implementation:* a single asyncio task per agent with a heartbeat, started when the Gateway boots and managed alongside the agent's session. The scheduler is a Gateway component, not a separate process. Heartbeat config is stored in the agent's DB record.

### Memory

#### D30 — Memory is a per-Contact store, subject-injected

Memory is a capability (`memory.recall`, `memory.store`, `memory.remember_fact`, `memory.query_facts`), therefore a syscall, therefore subject-injected and audited. `memory.recall(query)` takes no contact parameter; the syscall layer resolves whose memory from the session's Contact. Cross-contact memory leakage is then structurally the same bug as cross-contact email leakage, prevented by the same mechanism (D10).

- **Three layers (D34):** working memory (session context), MEMORY.md (agent-curated notebook, a file in the agent home dir), knowledge graph (structured triples). Semantic recall is configurable (FTS5 default, embeddings opt-in).
- **Storage:** key-value entries in SQLite (FTS5 or embeddings), namespaced per Contact. Knowledge graph triples in `memory_triples` table. MEMORY.md as a markdown file at `~/agentos/agents/{agent_id}/MEMORY.md` (agent home dir, not the workspace, not the DB).
- **Recall:** semantic search over stored entries, returned under a bounded token budget per call. The agent receives a summary, not the raw store.
- **Store:** the agent can save facts, preferences, and task context. Each store is an audited syscall visible in the dashboard (story 26).
- **Clear:** the operator can clear memory per-agent or per-Contact (story 27).

*Rationale:* memory is what makes the agent personal. Without it, every conversation starts from zero. With it as a syscall, the operator can see and control what the agent remembers — which is the difference between an assistant and a surveillance device.

*Implementation:* Pydantic AI (D2) provides memory primitives; the OS wraps them in the subject-injected syscall interface so `memory.recall()` resolves whose memory from the session's Contact, not from a model-supplied parameter.

### Channels

#### D20 — The Channel port, proven by two implementations

A Channel normalises inbound payloads, delivers replies, and declares its own output constraints (maximum length, supported formatting, whether typing indicators exist).

v0.1 ships one: **dashboard chat**. Dashboard chat is not a convenience — it is the primary channel for a personal agent. You talk to your agent in the dashboard, it does work on your machine, and the results come back in the same conversation. Test sessions are flagged and excluded from spend reports.

A second channel (Zalo Bot) is documented in the appendix and implemented when an external conversational surface is needed. Its inclusion is what proves steps 4–11 contain no channel-specific vocabulary.

### Operations

#### D25 — Agent configuration lives in the database

Agents are rows. Each save writes an immutable version row and advances an `active_version` pointer, giving diff, audit, and one-click rollback. YAML exists only for import and export (story 32), so there is never a second writer.

Sub-agents and connectors are separate rows with their own versions, because they are shared. Rolling back an agent does not roll back a shared sub-agent — the same way it does not roll back `file.read`.

An agent version, as YAML for readability:

```yaml
id: personal-assistant
name: "My Assistant"
channels:
  - type: dashboard_chat
workspace: ~/agentos/workspaces/personal-assistant
model:
  provider_id: my-openai-personal   # references a configured Provider (D39)
  name: gpt-4o-mini
  temperature: 0.3
soul: |
  I am a careful assistant. I verify before acting.
  I ask for approval on irreversible actions.
  I protect the user's time and attention.
persona: |
  I'm concise and direct. I use analogies.
  I'm friendly but not chatty.
task: |
  You are my personal assistant. You can read my email,
  manage my calendar, work with files in my workspace,
  and run shell commands when I ask...
capabilities:
  - name: mcp.outlook.email_read    # kind: mcp_tool (Outlook MCP server)
    subject: self
  - name: mcp.outlook.email_send    # kind: mcp_tool
    subject: self
    require_approval: true
  - name: mcp.outlook.calendar_read  # kind: mcp_tool
    subject: self
  - name: mcp.outlook.calendar_create # kind: mcp_tool
    subject: self
  - name: file.read             # kind: tool
    scope: workspace
  - name: file.write            # kind: tool
    scope: workspace
  - name: shell.run             # kind: tool
    scope: workspace
    require_approval: true      # dangerous commands need my OK
  - name: memory.recall         # kind: memory
    subject: self
  - name: memory.store          # kind: memory
    subject: self
  - name: research.summarize    # kind: sub_agent, from the pool
limits:
  max_turns_per_run: 12
  max_cost_per_run: 500
  session_idle_timeout_min: 60
  max_context_tokens: 24000
fallback:
  on_unsupported_message: "Sorry, I can't handle that yet..."
  on_limit_exceeded: tell_user_and_stop
```

A pooled sub-agent:

```yaml
id: research.summarize
name: "Research Summarizer"
task: "Read the provided content and return a concise summary..."
capabilities: [file.read, memory.recall]
# no channels, no session — rejected at config load
```

*Trade-off accepted:* configuration is not in git, so prompt changes get no pull-request review. The version table supplies the history and rollback that git would have, for the non-developer who is the actual user.

#### D26 — Observability is a feature, not logging

- **Correlation.** One `run_id` threads messages, syscalls, model calls, and errors. Investigating a complaint must never require joining records by hand.
- **Latency.** Time-to-first-reply recorded on every Run. It is what the user experiences and the first thing you will be asked about.
- **Failures surfaced.** Model errors, provider fallbacks, retries, and denied syscalls appear in the dashboard, not only in a log file.
- **Push, not only pull.** Every other observability story is "I want to see"; an operator does not watch a dashboard. At least one push path for hard failures.
- **Shell audit.** Every shell command and its output is recorded on the Run, visible in the dashboard (story 24). This is the record that answers "what did my agent do to my machine."

#### D27 — Build order: vertical slice before the rest of the dashboard

The first milestone is one agent, seeded from a configuration file, reachable through **dashboard chat**, with a real model, a real workspace, a real shell call into the sandbox, and a real audit record. The heartbeat scheduler is built alongside the harness (D31), but the first milestone does not require it — heartbeat is validated once the harness is proven. The rest of the dashboard is built second, against a schema real traffic has validated.

*This is a build order, not a statement of priority.* The dashboard is the product; it is second because the unvalidated assumptions are sandbox isolation on a real Mac, tool-calling reliability in the chosen model, and whether the workspace boundary holds under a real shell session. None are discovered by building forms, and all change what the forms must contain.

*Constraint that keeps it honest:* the slice must write every row the dashboard will read — runs, syscalls, audit records, costs, sessions, latency, shell logs, memory. If a screen would have nothing to render, the slice is incomplete.

#### D32 — Conversation-first frontend

The dashboard is not a management console with a chat widget. It is a two-level navigation:

1. **Agent list** (landing page) — the operator sees their fleet of agents. Create, configure, delete, view run history. This is the management layer.
2. **Conversation view** (click an agent) — a full-screen conversation with the selected agent. This is not a widget embedded in a dashboard. It is the primary interaction surface, taking over the viewport.

- **Real-time streaming.** The conversation view streams model tokens, tool calls, and tool results via SSE as they happen. The operator sees the agent thinking, calling tools, and producing output — not just the final reply.
- **Tool call visibility.** When the agent calls a tool (shell.run, file.read, email.read), the tool call and its result appear inline in the conversation, formatted as a collapsible block. The operator can expand to see the full command/output.
- **Heartbeat messages.** Runs triggered by heartbeat (D31) appear in the conversation, tagged as heartbeat-triggered. They are visually distinct from user messages.
- **Management is secondary.** Agent settings, capability configuration, memory browser, audit log — all accessible from the conversation view via a sidebar or menu, not as the main view.
- **No Canvas/A2UI in v0.1.** The agent replies with text and markdown only. Rich UI generation (agent-emitted components) is a v0.2 feature.

*Rationale:* the operator's primary relationship with the agent is conversation, not configuration. A widget communicates "the agent is a feature of the dashboard." A full-screen conversation communicates "the agent is the app, and the dashboard is how you switch between agents." This is the UX shift that makes the product feel AI-native without the complexity of agent-generated UI.

*Implementation:* React 19 + Vite. The conversation view is a full-page route (`/agents/{id}/chat`), not a component embedded in a dashboard. SSE endpoint streams events. TanStack Query manages the agent list and run history.

#### D33 — The Gateway is a headless daemon; the frontend is one client of many

The Gateway (D3) is a headless daemon with a well-defined HTTP + SSE API. The React dashboard (D32) is one client of that API. It is not the only possible client.

- **The API is the contract.** Everything the dashboard does — list agents, send a message, stream a response, approve a syscall, configure heartbeat, browse workspace — is an HTTP endpoint. The dashboard is a thin client over that API.
- **Future clients consume the same API.** A CLI (`caber chat <agent> "check my email"`), a TUI (terminal chat), a native macOS app (SwiftUI over HTTP), a mobile app — all talk to the same control plane on `127.0.0.1:8081`. No special protocol, no embedded SDK, just HTTP + SSE.
- **The dashboard is not special.** It has no privileged access, no back-channel, no direct database reads. It authenticates the same way any client does (session cookie, D4). If the dashboard can do it, a CLI can do it.
- **SSE for streaming.** Model tokens, tool calls, and tool results are streamed via Server-Sent Events. Any HTTP client can consume SSE — `curl`, a CLI, a TUI, a native app. No WebSocket required (D32).
- **The daemon runs without a frontend.** `caber serve` starts the Gateway. It works headlessly — heartbeat runs fire, connectors poll, audit records write — with no dashboard connected. A CLI can send messages and read replies. The frontend is a convenience, not a dependency.

*Why this matters:* the value of CaberOS is the agent runtime — the harness, the syscall layer, the sandbox, the connectors, the heartbeat. The frontend is how you interact with it today. If the API is clean and client-agnostic, swapping the frontend is a config change, not a re-architecture. A developer who prefers a CLI over a web dashboard should have the same experience.

*What this constrains:* the API must be complete. No "this only works in the dashboard" shortcuts. Every dashboard feature has an API endpoint. The dashboard is a reference client, not a special one.

*Implementation:* FastAPI serves the control plane API (REST + SSE). The React frontend is a separate package that consumes that API. A future CLI (`caber`) is another package that consumes the same API. Both are thin clients; the daemon does all the work.

#### D34 — Three-layer memory + configurable semantic recall

Memory is not one thing. It is three layers, each with a different mechanism and cost:

1. **Working memory** — session context (last N turns + rolling summary). Ephemeral, dies when the session closes. Already handled by the harness (D17). $0.
2. **MEMORY.md** — a markdown file at `~/agentos/agents/{agent_id}/MEMORY.md` (the agent home dir, not the workspace, not the DB), curated by the agent itself. Always loaded into context at the start of every run. The agent is prompted: "When you learn something important about the user, update MEMORY.md." The user can also edit it directly (transparent, builds trust). $0 — file I/O. Belongs to the agent, so it's private per-agent even when workspaces are shared (D37).
3. **Knowledge graph** — structured facts in a SQLite table (`memory_triples`: subject, predicate, object). Capabilities: `memory.remember_fact(subject, predicate, object)` and `memory.query_facts(subject?, predicate?, object?)`. Both are subject-scoped. $0 — SQL queries.

**Semantic recall** (Layer 4, fallback only) — for raw conversation snippets the agent didn't curate. Default: SQLite FTS5 (keyword search, $0). Configurable: if the operator sets an embedding provider in settings (via LiteLLM — OpenAI `text-embedding-3-small` or local Ollama `nomic-embed-text`), recall uses embeddings + cosine similarity. The `recall` capability checks config at runtime and routes accordingly.

*Why three layers:* the agent's own intelligence (which you're already paying for via model calls) does the semantic matching at *curation time* — it decides what to write to MEMORY.md and what triples to store. Embeddings are only needed for things the agent didn't think to curate. Most recall is satisfied by MEMORY.md (always loaded) and the graph (structured queries). FTS5 catches the rest for $0. Embeddings are opt-in for users who want maximum recall fidelity.

*Cost:* effectively $0 without embeddings. With embeddings: ~$0.0001 per recall (one embedding call). Negligible.

#### D35 — Agent identity: soul, persona, and task (versioned config fields)

An agent's context is assembled from three separate concerns, all three are **versioned config fields** on `AgentConfig` — editing any of them creates a new `AgentVersion` row, giving diff and rollback on identity changes, not just on task changes:

- **`soul`** — the agent's identity, values, decision-making principles. "I am a careful assistant. I verify before acting. I ask for approval on irreversible actions." **User-edited.** The user shapes who the agent is. Always loaded first in context.
- **`persona`** — the agent's personality, tone, communication style. "I'm concise and direct. I use analogies. I'm friendly but not chatty." **User-edited.** Always loaded second in context.
- **`task`** — the task description / instructions. "You are a personal assistant. Check email every morning, summarize important messages, manage my calendar." **User-edited.** Loaded third in context.

*Why the split:* identity (who), personality (how), and task (what) are separate concerns that the user edits at different times. Splitting them gives the dashboard three distinct editing surfaces instead of one giant text blob, and lets the user reason about each independently.

*Why all three are versioned config fields (not workspace files):* they belong to the agent, not to the workspace. A workspace is a shared directory for working files (D37); identity is not a working file. Storing them as config fields means every edit — including soul and persona tweaks — is diffable and rollback-able via `AgentVersion`, and YAML export/import carries the full agent identity in one artifact. MEMORY.md (D34) is the exception: it's agent-managed and changes constantly, so it lives as a file in the agent home dir (`~/agentos/agents/{agent_id}/MEMORY.md`), not versioned with config saves.

*Per-agent even in shared workspaces:* identity is stored in the DB keyed by agent id, and MEMORY.md lives in the agent home dir (not the workspace), so two agents sharing a workspace directory keep private identities and private memory. The workspace holds only working files.

#### D36 — Agent Skills (markdown prompt injection)

Skills are self-contained directories that inject instructions into the agent's context when triggered. No code, no new capabilities, no security surface. Pure prompt enrichment.

- **Format:** each skill is a directory `skills/{skill-name}/` containing:
  - `SKILL.md` — YAML frontmatter (`name`, `description`, `triggers`) + markdown body with instructions
  - `assets/` — optional supporting files the skill body references (templates, checklists, examples, reference docs)
  - Any other files the skill needs (data files, reference material)
- **Two locations:** system-level `skills/` directory (shared, ships defaults like `research`, `summarize`, `code-review`) and per-agent `workspace/skills/{agent_id}/` (agent-specific, lives in the workspace since skills are working artifacts, not identity).
- **Loading:** at context assembly, the harness scans skill directories, reads each `SKILL.md`, matches `triggers` against the user's message (keyword match or model decision), and injects matching skill bodies into context.
- **Asset access:** when a skill is triggered, its `assets/` directory is made readable to the agent for the duration of the run. The skill body can reference assets by relative path (e.g. "Use the template in `assets/email-template.md`"). Asset reads are scoped to the triggered skill's directory — the agent cannot read another skill's assets.
- **Skills don't add capabilities.** A `research` skill that says "search the web" only works if the agent already has a `web.search` capability granted. The skill is instructions; the capability is permission. Separate concerns.
- **$0 cost** — file reads only. No API calls, no code execution.
- **User-editable** — the user can read, write, and tweak skills directly. Transparent.
- **Agent-editable** — the agent can create and update skills in its per-agent workspace (`workspace/skills/{agent_id}/`) during a run, using `file.write`. This is how the agent learns reusable instructions: when it discovers a workflow worth repeating, it writes a `SKILL.md` to its workspace. The skill is picked up on the next context assembly. System-level skills (`skills/`) are agent-read-only — the agent cannot modify shared defaults, only its own per-agent skills. Agent-created skills are still just prompt fragments — no new capabilities, no security surface.

*Why:* this is the same model as Devin/Claude Code skills (and the agentskills.io open standard), adapted for a personal agent. It lets both the user and the agent customize behavior without code, without new capabilities, and without security review. A skill is a prompt fragment plus its supporting files. The agent creating a skill is the agent taking notes for itself — transparent, auditable (it's a file write), and reversible (the user can read and delete what the agent wrote).

#### D37 — Shared workspaces (working files only)

Agents can share a workspace directory for working files (scripts, notes, downloads). This enables collaboration: agent A writes `research_findings.md`, agent B reads it and summarizes.

The workspace holds only working files. Agent identity (`soul`, `persona`, `task`) lives in the DB (D35), and MEMORY.md lives in the agent home dir (`~/agentos/agents/{agent_id}/`, D34) — neither in the workspace, so both are private per-agent regardless of which workspace is shared:
- `soul`, `persona`, `task` — per-agent identity, versioned config fields in the DB (D35)
- `MEMORY.md` — per-agent curated memory, file in the agent home dir (D34)
- `skills/{agent_id}/` — per-agent skills, lives in the workspace since skills are working artifacts (D36)

**Cross-agent contamination risk:** if agent A writes a malicious script to the shared workspace and agent B has `shell.run` granted, agent B could execute it. This is mitigated by:
1. `shell.run` requires approval by default (the operator approves before execution).
2. The audit trail records both: agent A wrote the file, agent B executed it. Blast radius is traceable.
3. The operator controls both agents and granted both their capabilities.

*Why shared workspaces:* a personal agent ecosystem is more useful when agents can collaborate on files. The risk is accepted for v0.1's single-user model and mitigated by approval gates and audit trails.

#### D38 — MCP tools in v0.1; CLI/TUI moved to v0.2

1. **MCP tools.** The `mcp_tool` capability kind is in v0.1. v0.1 ships with four capability kinds: `tool`, `sub_agent`, `memory`, `mcp_tool`. MCP (Model Context Protocol) tool support — connecting external MCP servers, discovering their tools, and registering them as capabilities — is the integration layer for v0.1. The native `connector_action` kind from the original spec is removed; MCP replaces it.

   *Revision note:* the original spec deferred MCP to v0.2 and shipped native connectors. The MCP ecosystem matured (32,600+ servers, 8+ production Outlook servers as of mid-2026) and both OpenClaw and Hermes Agent ship MCP as their sole integration path. Native connectors would be a parallel abstraction for a problem the ecosystem already solves. See plan 10 for the full design.

2. **CLI/TUI (`caber`).** v0.1 ships the React dashboard as the only client. The `caber` CLI/TUI — a terminal interface for chatting with agents, managing config, and approving syscalls — is v0.2. The API is client-agnostic (D33), so the CLI will consume the same HTTP + SSE endpoints as the dashboard. v0.1 includes only `scripts/smoke.py`, a development tool for testing the pipeline end-to-end before the frontend exists (not a product CLI).

#### D39 — Providers are first-class, keys encrypted, LiteLLM is transport

Model access is not just "throw an API key at LiteLLM." A `Provider` is a first-class configured entity, stored in the DB with its key encrypted (same Fernet secret store as connectors, D13).

- **A `Provider` has:** name, type (`openai`, `anthropic`, `google`, `ollama`, `azure`, ...), encrypted API key (null for local providers), optional `base_url` (for Ollama, Azure, custom endpoints), optional `org_id`, and provider-specific `extra_params`.
- **Agents reference a provider by id:** `model: { provider_id: "my-openai-personal", name: "gpt-4o" }`. Not a raw provider string, not an env var.
- **Multiple providers of the same type** are allowed — a personal OpenAI key and a work OpenAI key coexist as two providers.
- **Keys are encrypted at rest**, never returned to the dashboard or logs in plaintext, and can be rotated via the API without restarting the daemon.
- **Local providers (Ollama) need no key** — just a `base_url`.
- **LiteLLM remains the transport.** At call time, the harness loads the `ProviderConfig`, decrypts the key, and passes `api_key`, `base_url`, `org_id`, `extra_params` to LiteLLM's `completion()`. LiteLLM handles the provider-specific API format; the OS owns key management, per-agent provider selection, and cost accounting.

*Why:* env-var keys don't scale past one provider, can't be rotated without a restart, sit in plaintext, and can't express "personal vs work." First-class providers make model access configurable, encrypted, and per-agent — the same rigour applied to connector credentials.

#### D40 — Model discovery: dynamic where available, free-text everywhere

When configuring an agent's model, the operator picks from a live list where the provider supports it, and types the name where it doesn't.

- **Dynamic discovery** — providers with a list-models endpoint are queried live: OpenAI (`GET /v1/models`), Google (`GET /v1/models`), Ollama (`GET /api/tags` — lists locally pulled models), Azure (deployments). The dashboard shows a dropdown.
- **Free-text fallback** — providers without a list endpoint (Anthropic) get a free-text input.
- **Always an override** — even when a list is available, a "type your own" option covers brand-new models not yet in the API's list. The system is never blocked waiting for us to update a hardcoded list.
- **Validation at save time** — when an agent is saved, a cheap 1-token completion validates the `provider_id` + model string. Typos fail at config time, not at 3am during a heartbeat run.

*Why:* hardcoded model lists go stale within weeks. Pure free-text has no discovery and fails on typos. Discovery + free-text override + save-time validation gives accuracy (live lists, especially Ollama's local models), freshness (override for new models), and safety (no runtime surprises).

### What makes a good test here

A good test drives the system at its outermost boundary — an inbound message — and asserts on observable outcomes: messages sent back, audit records written, cost recorded, session state, files touched, shell commands run. It never asserts on internal call sequences, prompt strings, or the harness's intermediate structure, because those change while behaviour stays correct.

Security properties are asserted as behaviour: *a shell call that tries to read `/etc/passwd` is rejected with a denied audit record, because the path escapes the workspace.* Not: *`check_workspace_scope` was called with these arguments.*

### Seams

Two doubles, everything else real. Both stand in for things that are non-deterministic, cost money, or cannot run in CI.

1. **Channel transport (primary seam).** Inject a normalised inbound message; assert the outbound messages handed to a recording transport. This one seam exercises deduplication, ordering, contact resolution, the harness, syscall mediation, compaction, cost caps, and audit — with no network.
2. **Model client.** A scripted stand-in returning predetermined syscalls and final text, making runs deterministic and free.
3. **Capabilities, sandbox, and database are real.** Real SQLite with seeded fixtures. Real process-level sandbox (sandbox-exec on macOS, bwrap on Linux) with a test workspace. Real filesystem assertions.

### Coverage priorities

- **Workspace containment** — highest value. A file read/write that tries to escape the workspace (`../`, absolute paths, symlinks) is rejected; a shell command that tries to read outside the workspace is rejected by the sandbox. This is the security boundary that makes shell grantable at all.
- **Subject injection** — the agent cannot pass a subject parameter; `email.read()` resolves to the session Contact's bound mailbox; a model attempting to pass an explicit subject produces a denied audit record.
- **Scope narrowing** — narrowing across every combination of agent ceiling and sub-agent ceiling.
- **Sub-agent containment** — an agent granted a sub-agent whose capabilities exceed its own cannot reach them through it.
- **Plane isolation** — a control-plane route is not served on the data-plane socket. Asserted as a test, because this failure is invisible until exploited.
- **Delivery integrity** — duplicate `message_id` produces exactly one reply; two concurrent messages from one Contact produce ordered replies; a crash mid-run leaves recoverable state.
- **Compaction** — a long session stays under the token cap; compaction is recorded; the warning fires before the ceiling.
- **Cost control** — a run exceeding its cost cap stops and applies its fallback; recorded cost matches the sum of its calls, including sub-agent turns.
- **Memory** — store and recall round-trip; recall is bounded by token budget; memory is namespaced per Contact (one Contact cannot recall another's entries).
- **Approval gate** — a `require_approval` syscall does not execute until approved; a denied approval produces a denied audit record and the run continues.

### Tests that use real infrastructure

- **Sandbox isolation:** a few tests against the real process-level sandbox (sandbox-exec on macOS, bwrap on Linux), verifying that filesystem escapes and network egress are blocked. Non-deterministic (depends on the platform sandbox tool); excluded from the default suite.
- **Tool-calling reliability:** a few tests against a local Ollama model, verifying that a small model reliably emits well-formed syscalls. Non-deterministic; excluded from the default suite.
- **Release smoke test:** one manual end-to-end pass against a real model and a real sandbox before each release — dashboard chat, shell command, file read/write, email read via a real connector.

---

## Roadmap

Direction, not commitment. Each item names what it needs.

**v0.1 — The personal agent.** This document. Dashboard chat, four capability kinds (tool, sub-agent, memory, connector action), two scopes, a local dashboard, a workspace, a sandbox, and real connectors (Outlook/email/calendar). No role ladder, no access gate — the agent is yours, on your machine.

**v0.2 — A second channel and more connectors.** A second channel (Zalo Bot — see appendix) to keep the port honest and prove the channel abstraction. More connectors (Gmail, Notion, GitHub). RAG over workspace documents, because an agent that can read your files but not search them is half an assistant.

**v0.3 — Reach and insight.** Guardrails on both edges — validate input before a run, validate output after, block **or redact**. Metrics, alerting, and quality sampling, because browsing conversations by hand stops working past a few dozen a day. MCP, once native capabilities are proven and D14's tripwire has an answer for arbitrary MCP tools.

**v0.4 — Remote operator access and roles.** Real operator identity, sessions, and roles on the control plane, so the dashboard can be reached from outside the machine without weakening D4. This is also where a role ladder on *callers* returns if a real deployment needs it — not as a v0.1 retrofit, but as a deliberate addition with the data to justify it.

**v0.5 — Non-conversational harnesses.** A scheduled harness, possibly a batch harness. This is where "harness" becomes plural in this codebase — OS-owned implementations behind one selection point, still not a plugin surface.

**Later, and only with a real customer's real data:**

- The `team` scope, which needs a trustworthy org chart.
- Cross-agent handoff, which reopens I5 and needs a design for how authority does *not* travel with the conversation.
- Multi-tenancy, which is a different product and should be recognised as one before it is started.

---

## Out of Scope

**Cut from the source document entirely:**

- Runtime adapters for DeepAgents, LangGraph, OpenAI Agents SDK, Pydantic AI — superseded by D1 and D2.
- The plugin system, manifest, SDK, and repository.
- The package manager, package signing, sources, and repository.
- The Agent Development Kit.
- Built-in system agents (Personal Assistant, Agent Builder, Package Manager, System Administrator, Workspace Manager, Knowledge Manager).
- Process sandboxing via seccomp or container isolation as a *general* mechanism — superseded by D14/D28, which sandbox specifically shell and filesystem, not the whole agent.
- A general policy engine — superseded by D11's closed vocabulary.
- Service registry, dependency injection, and event bus as user-facing architecture.

**Deferred product scope:**

- External channels (Zalo, Telegram, web widget, email). *v0.2. See appendix.*
- Inter-agent communication of any kind: routing, handoff, shared memory, delegation between top-level agents. Pooled sub-agents inside a Run are the only composition.
- More connectors (Gmail, Notion, GitHub). *v0.2.*
- RAG over workspace documents. *v0.2.*
- Guardrails, metrics, alerting, MCP. *v0.3.*
- The `team` subject scope. *Returns with a real customer's real org data.*
- A role ladder on callers, `min_role` gating, verification flows, and approval queues. *Returns at v0.4, or sooner if a real deployment needs it.*
- Voice and image handling beyond acknowledgement.
- Multi-tenancy, horizontal scaling, distributed queues, Postgres.
- Streaming responses. Dashboard chat delivers complete messages.

---

## Further Notes

### Risks

- **Sandbox escape.** The workspace boundary (D29) and the process-level sandbox (D28) are the only things between a prompt-injected agent and your home directory. Test containment ruthlessly (see Testing). If the platform sandbox tool is not available, shell capabilities must be disabled, not downgraded to unsandboxed execution.
- **Tool-calling reliability in small models.** If a cheap local model cannot reliably emit well-formed syscalls, the cost model changes materially. Measure early; cheap to test, expensive to discover late.
- **Prompt quality is the ceiling.** Under D1 the harness's answer quality is not defensible by architecture. There is no abstraction to hide behind — deliberately.
- **The fleet is hypothetical until it exists.** Stories 28–37 describe managing many agents; v0.1 ships with one. The second and third agent are what test whether the control plane earns its name. Build them before declaring the design validated.
- **Connector OAuth is a maintenance burden.** OAuth tokens expire, scopes change, APIs deprecate. v0.1 ships with Outlook/email/calendar; expect to maintain the connector layer continually.

### Notes on the source document

`raw_spec_need_to_be_refine.md` remains as source material. It contains no implementable content: 5,458 lines with no type, schema, wire format, or function signature; 177 code fences containing only ASCII diagrams and identifier lists. Its Domain Model chapter omits both "Agent Harness" and "Runtime" despite those being the two most-referenced concepts in the document.

It should not be edited or extended. This specification replaces it.

---

## Appendix: Zalo Bot Channel Integration

Zalo Bot is a second channel, documented here for implementation when an external conversational surface is needed (v0.2). The decisions below were validated against the Zalo Bot Platform documentation and are retained as reference; they are not part of v0.1 core.

#### D21 — Webhook in production, polling in development

Zalo's documentation states `getUpdates` is for local development only and that production should use webhooks **to avoid missing events**. `getUpdates` accepts only a `timeout` parameter — no offset, no acknowledgement cursor — so delivery is at-most-once and a crash loses messages. The modes are mutually exclusive.

Production therefore needs a public HTTPS endpoint. The installer provisions an outbound tunnel (Cloudflare Tunnel or equivalent) pointed at the **data-plane port only**: no port forwarding, no static IP, no certificates. Message data still terminates on the operator's machine.

**One webhook path per agent:** `/webhooks/zalo/{agent_id}/{random}`, verified against that agent's own secret. A shared path with a shared secret would let any bot's token authenticate a message claiming to come from another bot.

#### D22 — Zalo Bot integration constraints

Verified against the platform documentation:

- **Auth:** one static bot token per bot, format `12345689:abc-xyz`, no expiry until manually reset. No refresh job.
- **Webhook auth:** shared secret in `X-Bot-Api-Secret-Token`. Constant-time comparison. A static token, not a signature — therefore replayable, which makes deduplication a security control, not only a UX one.
- **Inbound:** `result.message` carries `from.id`, `from.display_name`, `chat.id`, `chat.chat_type`, `text`, `message_id`, `date`. In private chats `from.id` equals `chat.id`.
- **Events:** `message.text.received`, `.image.`, `.sticker.`, `.voice.`, `.unsupported.`
- **Outbound:** `sendMessage(chat_id, text)`, text **1–2000 characters**, optional `parse_mode` of `markdown` or `html`. Also `sendPhoto`, `sendSticker`, `sendVoice`.
- **Typing:** `sendChatAction(chat_id, "typing")`.

#### D23 — Protected-user handling is a legal requirement

Zalo delivers `message.unsupported.received` **without content** when the sender belongs to a protected group (the documentation cites children, people with disabilities, and illiterate people).

The agent cannot read these messages at all. On this event the OS sends the configured fallback and raises a human-handoff signal.

#### D24 — Delivery integrity

- **Deduplication:** `message_id` recorded on receipt; repeats acknowledged and dropped before work is queued.
- **Ordering:** at most one Run per Contact at a time; concurrent arrivals queue.
- **Durability:** persisted before `200` is returned. Once acknowledged, the OS owns it.
- **Recovery:** on startup, in-flight runs are requeued or failed with an apology.
- **Latency masking:** typing indicator sent immediately on acceptance.

### Open question: `from.id` scoping

**Is `from.id` scoped per bot or per Zalo account?** The sample payload shows an opaque hex identifier, and in private chats `from.id` equals `chat.id`. Zalo OA user IDs are OA-scoped, so per-bot scoping is likely but unconfirmed.

If per-bot: a person bound on one bot is a stranger to another, and the operator binds the same person once per agent. At five agents that is five bindings per person — a fleet problem, so it lands on the dashboard.

**Resolution:** create two test bots and message both from one Zalo account. Compare the identifiers. Five minutes; no amount of reasoning substitutes for it. If they differ, add a person-level identity above Contact, bound once by a short code the person gives to each bot.
