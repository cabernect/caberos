# CaberOS — Product

*What this is, who it's for, and where it sits. For the pitch see [../README.md](../README.md); for the internals see [TECHNICAL.md](TECHNICAL.md).*

---

## Vision

**Personal AI agents you can actually run your life on — because you can see, control, and trust what they do.**

Every agent product promises autonomy. Almost none of them let you answer basic questions afterwards: *what did it do, what did it read, what did it send, what did it cost, and could it have done worse?* CaberOS is built so those answers exist — in an audit trail, a trace, a receipt — not in a blog post.

The machine it runs on is yours. The model providers are swappable transports. Data stays local except the inputs you choose to send — remote models and services receive exactly what your configured permission policy allows.

## The problem

Personal agents today come in three flavors, and each trades away a different piece:

1. **Chat products with agent features.** Sessions evaporate, memory is opaque, permissions are a shrug, and "show me what it did" is unanswerable. Your data is the product's substrate.
2. **Agent frameworks.** Full control on paper — but you rebuild identity, permissions, memory, scheduling, observability, and a UI before your first useful run.
3. **Assistant gateways** (the post-2025 wave of self-hosted connectors). Genuinely good at *reach* — every chat app, every model — but built wide rather than governed; mediation and audit are typically bolted on per-server rather than built into the runtime.

CaberOS is the fourth option: an **operating system** for agents. Identity, permissions, memory, mediated resource access, and audit are OS services — every agent inherits them by construction. An agent is configuration; the OS is the law.

## Who it's for

- **The privacy-minded professional** who wants a real assistant — email summaries, research, documents, scheduled briefings — without handing a vendor their files, keys, and habits.
- **The self-hoster** who wants one daemon, their own database, and no SaaS in the middle.
- **The small-team operator** who needs agents that do scheduled, repeatable work — reports, digests, monitoring — with a paper trail they can defend.
- **The agent builder or researcher** who wants an inspectable platform: every model call ledgered, every tool call audited, skills versioned — a lab for agent behavior, not just a product.
- **The developer** who wants the OS layer done: gateway, sandbox, memory, observability — so the interesting part is the agent, not the plumbing.

Day-to-day use is deliberately non-technical — the desktop app installs like any app, and chat/approvals/notifications need no terminal time.

First run starts with sign-in using the seeded credentials, followed by optional credential setup. You can skip and keep the default login; once you set credentials, onboarding drops its password step. Onboarding checks the browser, sandbox, Node.js, uv, and Git before welcoming you to **Today** — the operator home with Needs-you items, recent activity, and an ask-your-agent entry. The optional spotlight tour introduces the interface; it does not probe runtimes.

Settings → General → Sign-in manages credentials. General → Product tour replays the tour; General → Appearance restores page hints. You still bring a provider API key or connect a local model endpoint. Ollama's onboarding link is guidance, not an installation check. Multi-user administration remains a roadmap item.

## What it does (v0.2.0)

- **Agents as configuration** — personality, model, tools, and limits are versioned config you can inspect, diff, roll back, and share. Multiple agents, concurrent sessions.
- **An operator home** — Today surfaces what needs you (approvals, elicitations), recent activity, and a direct ask-your-agent entry; notifications deep-link into the right trace.
- **Everywhere you talk** — the built-in dashboard, plus Telegram, Discord, and Zalo channels running the same governed pipeline.
- **Real work, not just chat** — read/write files, run sandboxed shell commands, search and fetch the web, drive a managed browser (watch it, or take the wheel), delegate to sub-agents.
- **Deliverables with a paper trail** — polished DOCX/XLSX/PPTX/PDF documents as immutable, versioned artifacts with in-app preview. "Show me every version of that report" is a real button.
- **Memory that closes the loop** — agents keep a bounded living memory, write session summaries, learn durable facts, and can *revise their own skills* from what actually happened — under version control, deduplicated, inspectable.
- **A private knowledge vault** — your documents become citable evidence. Local search by default; remote embeddings only with explicit consent. Retrieval returns source citations you can inspect.
- **Scheduling that survives reality** — one-shot, interval, or cron in real timezones with proper DST behavior, missed-run recovery, retries, and the classic per-agent heartbeat.
- **An audit habit baked in** — every run, tool call, model call, approval, and dollar is recorded. Traces show recorded truth, never a reconstruction; unknown cost is labeled unknown, never silently zero.

## The landscape

| | CaberOS — local governed workbench | Hosted assistants | Agent frameworks | Assistant gateways |
|---|---|---|---|---|
| **Shape** | Agent OS: governed runtime + dashboard | SaaS assistants | Libraries you assemble | Connectors between chat apps and agents |
| **Runs where** | Your machine / your server | Vendor cloud | Wherever you deploy | Your machine / server |
| **Permissions** | Every action crosses one mediated boundary; approvals + remembered scopes | Vendor-managed | You build it | Per-server policy, varies by project |
| **Memory/learning** | Bounded core + session summaries + skill reflection, all inspectable | Vendor-dependent | DIY | Persistent memory, some self-modifying |
| **Deliverables** | Versioned Office/PDF artifacts + previews | Polished but hosted | DIY | Chat- and file-oriented |
| **Observability** | First-class ledger: runs, traces, per-call cost, citations — local | Partial dashboards | DIY | Gateway logs |
| **Model freedom** | Any provider incl. local; catalog + pricing honesty | Vendor's models | Any | Any incl. local |
| **Trust model** | Assume compromise; local storage; approvals as architecture | Vendor trust model | Inherits yours | Varies; review each project |
**Honest read:** hosted assistants win on zero-effort onboarding; gateways win on channel breadth and install friction; frameworks win on flexibility for developers. CaberOS's lane: **agents you can govern and audit like real software** — where "what did it do, what did it cost, and why was that allowed" have recorded answers.

## Security & trust

Personal agents are a new attack surface — they hold credentials, act autonomously, and read untrusted content (web pages, messages, documents) that can try to steer them. So we state our posture plainly:

**What CaberOS does by construction:**
- **Egress capabilities cross an approval boundary.** Web fetch, browser navigation, shell commands, and remote embeddings ask before acting — per the capability's declared effects. "Never ask again" is a remembered scope the operator owns — not a default.
- **Sandboxed execution** — OS-level isolation (seatbelt/bwrap/MXC, Docker fallback), workspace-scoped file access with canonical path containment.
- **Encrypted credential custody** — provider keys and connector tokens are encrypted at rest, injected at execution time, never into prompts; guardrails redact secrets on output, and audit/log payloads are redacted and bounded (not a tamper-proof guarantee).
- **Blast radius is bounded** — capability ceilings are config, and nothing below the model (memory writes, elicitation, reflection) can widen them.
- **Receipts for everything** — the audit log and call ledger record what crossed the boundary, so actions leave inspectable records.

**What remains hard — and we say so:**
- **Prompt injection is industry-unsolved.** We mitigate (approval gates, sandboxing, domain leash, injection detection, recommend strong models) — we do not claim immunity.
- **A local OS still needs sane defaults.** `YOLO` mode skips approvals for trusted environments; it's opt-in and labeled. We won't ship "convenient but unsafe" as the default.
- **Self-hosted means self-operated** — exposure is the operator's choice; the default bind is localhost.

## Business posture

- **Open source (MIT).** The repo is the product. Local runtime does not require a hosted CaberOS account; configured remote services and optional update/catalog refresh contact external endpoints under your configured policy.
- **Distribution** — signed desktop app (macOS today, Windows beta), Docker for servers, source for developers; bilingual public site (EN/VI).
- **Honest economics** — the spend ledger surfaces real provider costs per call. Trust-through-transparency is a feature that follows from owning the full runtime.
- **Future surface (uncommitted)** — a sync/control-plane layer, hosted runtime, or team features could become a paid tier. The local OS stays whole without it; nothing in the design depends on a cloud service existing.

## Roadmap

| Release | Theme | In one line |
|---|---|---|
| v0.1.x (shipped) | Prove the OS | Chat, tools, approvals, memory, skills, MCP, channels, scheduler, observability, desktop. |
| **v0.2.0** (integrated, release prep) | **Agent Workbench** | Artifacts + previews, browser automation, governed evolving skills, Vault RAG, durable schedules, ledgered observability. |
| v0.2.1 | Connected Knowledge | Cloud-drive sources, read-only OAuth, pluggable retrieval backends, structured/tabular data done right. |
| v0.2.2 | Tasks & Events | Durable tasks with dependencies and evidence; event triggers; approvals inside the chat channel. |
| Later | Missions & marketplace | Multi-agent missions, plugin SDK, more platforms — shipped only when verified. |

## Success looks like

- An operator runs an agent for a month: **spend matches the ledger**, approvals fired exactly when expected, nothing touched the network unapproved.
- A session closes and the next one quietly knows more — the improved skill shows a revision diff you can read.
- A 3am scheduled job fails: the notification deep-links to a trace showing the *recorded* failure, not a guess.
- Someone audits a run top to bottom — model request, tool calls, cost — and finds nothing reconstructed.
