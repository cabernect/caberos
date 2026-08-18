# 11 — Memory & Skills

## Goal

Build the three-layer memory architecture plus agent skills (Decisions 7, 11b, 11c, 34, 35). Memory is what makes the agent personal — it remembers preferences, facts, and past context across sessions. Skills are markdown instruction files that inject context when triggered. Agent identity (`soul`, `persona`, `task`) is stored as versioned config fields on `AgentConfig` (D35); MEMORY.md is an agent-owned file in the agent home dir (D34).

## Spec references

- **D7** — Three-layer memory architecture (working memory, MEMORY.md, knowledge graph, semantic recall)
- **D11b** — Agent skills are markdown instruction files, injected on trigger match
- **D11c** — Skills don't add capabilities — they're instructions only
- **D34** — Three-layer memory: working memory, MEMORY.md (file in agent home dir), knowledge graph. FTS5 default, embeddings configurable
- **D35** — Agent identity (`soul`, `persona`, `task`) are versioned config fields on `AgentConfig`, not workspace files
- **D30** — Memory is a per-Contact store, subject-injected
- **D10** — The syscall layer injects the subject; the agent cannot name it
- **I3** — The subject is never model-supplied
- **Stories 25-27** — remember facts, browse memory, clear memory
- **Stories 60-61** — user wants agent to remember preferences and past requests

## Dependencies

- [01-database-layer.md](01-database-layer.md) — needs MemoryEntry, memory_triples, memory_embeddings tables
- [02-agent-config.md](02-agent-config.md) — `soul`, `persona`, `task` are config fields on `AgentConfig` (D35); MEMORY.md is separate
- [03-harness.md](03-harness.md) — context assembly loads soul, persona, task (from config), MEMORY.md (from agent home dir), and skills
- [04-syscall-layer.md](04-syscall-layer.md) — memory capabilities are invoked through the syscall layer
- [05-capabilities.md](05-capabilities.md) — memory and recall are capability kinds
- [07-pipeline.md](07-pipeline.md) — the execution pipeline assembles context including memory layers

## Architecture

### Layer 1 — Working memory (session context)

Already handled by the harness ([03-harness.md](03-harness.md)). No new work in this plan.

### Layer 2 — MEMORY.md (agent-curated notebook)

- A markdown file at `~/agentos/agents/{agent_id}/MEMORY.md` (the agent home dir — not the workspace, not the DB)
- The harness reads it at context assembly (plan 03) — always loaded
- The agent updates it via `file.write` scoped to the agent home dir (audited syscall) — or a dedicated `memory.update` capability if we want it clearly separated from workspace file writes
- Prompt instruction: "When you learn something important about the user, update MEMORY.md"
- The user can also edit it directly via the dashboard (transparent, builds trust)
- Not versioned with `AgentVersion` — it's a living document the agent updates freely during runs
- Belongs to the agent, so private per-agent even in shared workspaces (D37)

### Layer 3 — Knowledge graph (structured facts)

- SQLite table `memory_triples`: `(id, contact_id, agent_id, subject, predicate, object, source_run_id, created_at)`
- Capabilities: `memory.remember_fact(subject, predicate, object)` and `memory.query_facts(subject?, predicate?, object?)`
- Both are subject-scoped (resolve Contact from session)
- $0 cost, SQL queries, exact match

### Layer 4 — Semantic recall (configurable)

- Default: SQLite FTS5 on raw conversation snippets (keyword search, $0)
- Configurable: if user sets embedding provider in settings (via LiteLLM — OpenAI text-embedding-3-small or local Ollama nomic-embed-text), recall uses embeddings + cosine similarity
- `MemoryConfig` in settings: `embedding_provider` (str, optional), `embedding_model` (str, optional)
- `RecallBackend` interface with two implementations: `FTSBackend` and `EmbeddingBackend`
- Embeddings stored as JSON arrays in a sidecar table `memory_embeddings`: `(id, memory_entry_id, embedding (JSON), model, created_at)`
- The `recall` capability checks config at runtime and routes accordingly
- Only used as fallback when MEMORY.md and graph don't have the answer

### Agent Skills (Decision 11b, 11c, D36)

- Self-contained directories that inject instructions into the agent's context when triggered
- Each skill is a directory: `skills/{skill-name}/`
  - `SKILL.md` — YAML frontmatter (name, description, triggers) + markdown body with instructions
  - `assets/` — optional supporting files (templates, checklists, examples, reference docs) that the skill body references
  - Any other files the skill needs (data files, reference material)
- Two locations: system-level `skills/` directory (shared, ship defaults, agent-read-only) and per-agent `workspace/skills/{agent_id}/` (agent-specific, lives in the workspace — D36). The agent can create and update skills in its per-agent directory during a run via `file.write`; system-level skills are read-only for the agent.
- Loading: at context assembly, scan skill directories, read each `SKILL.md`, match triggers against user message, inject matching skill body into context
- Agent-created skills: when the agent discovers a workflow worth repeating, it writes a `SKILL.md` (and optional `assets/`) to `workspace/skills/{agent_id}/{skill-name}/`. The skill is picked up on the next context assembly. This is the agent taking notes for itself — transparent (the user can read what it wrote), auditable (it's a file write syscall), and reversible (the user can delete it).
- Asset access: when a skill is triggered, its `assets/` directory is made readable to the agent for the duration of the run. The skill body can reference assets by relative path (e.g. "Use the template in `assets/email-template.md`"). Asset reads are scoped to the triggered skill's directory — the agent cannot read another skill's assets.
- Skills don't add capabilities — they're instructions only. A "research" skill that says "search the web" only works if the agent already has a `web.search` capability.
- $0 cost, file reads only
- This is the same model as Devin/Claude Code skills and the agentskills.io open standard

### Agent identity — soul, persona, task (Decision 35)

Agent identity is stored as **versioned config fields** on `AgentConfig` (see [02-agent-config.md](02-agent-config.md)), not as workspace files:

- `AgentConfig.soul` — agent identity (user-edited, "who I am")
- `AgentConfig.persona` — agent personality/style (user-edited, "how I talk")
- `AgentConfig.task` — task instructions (user-edited, "what I do")

These are loaded at context assembly (plan 03), always, in that order. The agent does NOT modify them — they're the user's instructions about who the agent is. Editing any of them creates a new `AgentVersion` row (diff and rollback on identity changes, not just task changes).

MEMORY.md (Layer 2 above) is the exception: it's agent-managed and lives as a file in the agent home dir (`~/agentos/agents/{agent_id}/MEMORY.md`), not versioned with config saves.

## Tasks

### 1. Implement semantic recall store

`backend/src/agentos/memory/store.py`:
- FTS5 backend: index raw conversation snippets, keyword search
- Embedding backend: store embeddings, cosine similarity search
- Both backends implement the `RecallBackend` interface

`backend/src/agentos/memory/recall.py`:
- `RecallBackend` interface with two implementations: `FTSBackend` and `EmbeddingBackend`
- `FTSBackend` — SQLite FTS5 on conversation snippets, keyword search, $0 cost
- `EmbeddingBackend` — uses LiteLLM to generate embeddings (OpenAI text-embedding-3-small or local Ollama nomic-embed-text), cosine similarity over stored embeddings
- Sidecar table `memory_embeddings`: `(id, memory_entry_id, embedding (JSON), model, created_at)`
- Runtime config check: `MemoryConfig` in settings (`embedding_provider`, `embedding_model` — both optional)
- Routes to FTS by default, switches to embeddings when provider is configured

### 2. Implement knowledge graph (triples)

`backend/src/agentos/memory/triples.py`:
- SQLite table `memory_triples`: `(id, contact_id, agent_id, subject, predicate, object, source_run_id, created_at)`
- `remember_fact(contact_id, agent_id, subject, predicate, object, source_run_id) -> triple_id`
- `query_facts(contact_id, agent_id, subject?, predicate?, object?) -> list[Triple]`
- Subject-scoped: contact_id resolved from session, never model-supplied (D10)
- $0 cost, SQL queries, exact match

### 3. Implement MEMORY.md file access

`backend/src/agentos/memory/notebook.py`:
- `read_memory(agent_id) -> str` — reads `~/agentos/agents/{agent_id}/MEMORY.md`, returns empty string if file doesn't exist yet
- `write_memory(agent_id, content) -> None` — writes `~/agentos/agents/{agent_id}/MEMORY.md`, creates the dir if needed
- The agent home dir (`~/agentos/agents/{agent_id}/`) is created on agent creation (plan 02)
- Not versioned — direct file read/write, living document

### 4. Implement skill loading

`backend/src/agentos/memory/skills.py`:
- Scan system-level `skills/` directory and per-agent `workspace/skills/{agent_id}/`
- Each skill is a directory: `skills/{skill-name}/` containing `SKILL.md` + optional `assets/` + other files
- Parse `SKILL.md` files: YAML frontmatter (name, description, triggers) + markdown body
- Trigger matching: match triggers against user message at context assembly
- Return matching skill bodies for injection into context
- Asset handling: when a skill is triggered, register its directory as readable for the duration of the run. The skill body can reference assets by relative path (e.g. `assets/template.md`). Asset reads are scoped to the triggered skill's directory.
- $0 cost, file reads only

Example skill directory structure:
```
skills/                           # system-level (shared, agent-read-only)
  research/
    SKILL.md                      # frontmatter + instructions
    assets/
      search-template.md          # template the skill body references
      sources-checklist.md
  summarize-email/
    SKILL.md
    assets/
      summary-format.md

workspace/skills/{agent_id}/      # per-agent (agent can create/update)
  weekly-report/
    SKILL.md                      # agent wrote this after learning the workflow
    assets/
      report-template.md          # agent created this template
```

### 4a. Agent-created skills

The agent can create skills in its per-agent workspace during a run:
- The agent uses `file.write` to create `workspace/skills/{agent_id}/{skill-name}/SKILL.md` (and optional `assets/`)
- This is a normal file write syscall — audited, scoped to the workspace, no special permission needed
- The skill is picked up on the next context assembly (next run)
- System-level `skills/` directory is agent-read-only — the agent cannot modify shared defaults
- The user can read, edit, or delete agent-created skills at any time (they're just files)
- Prompt instruction in `task`: "When you discover a workflow worth repeating, write a skill to your workspace so you remember it next time."

### 5. Register memory capabilities

In the capability registry:
- `memory.recall(query: str)` — kind: `memory`, subject-scoped: true, egress: false
  - Schema: `{ "query": { "type": "string" } }` — no subject parameter (D10)
  - Execute: routes to FTS or Embedding backend based on `MemoryConfig`
- `memory.remember_fact(subject: str, predicate: str, object: str)` — kind: `memory`, subject-scoped: true
  - Schema: `{ "subject": ..., "predicate": ..., "object": ... }` — no contact_id parameter
  - Execute: `TriplesStore.remember_fact(contact_id, agent_id, ...)`
- `memory.query_facts(subject?, predicate?, object?)` — kind: `memory`, subject-scoped: true
  - Schema: `{ "subject": ..., "predicate": ..., "object": ... }` — all optional, no contact_id parameter
  - Execute: `TriplesStore.query_facts(contact_id, agent_id, ...)`
- `memory.update(content: str)` — kind: `memory`, subject-scoped: false (agent-scoped, not contact-scoped)
  - Schema: `{ "content": { "type": "string" } }`
  - Execute: `write_memory(agent_id, content)` — writes MEMORY.md in the agent home dir (D34)
  - Audited like all syscalls, but not contact-scoped — it's the agent's general notebook

### 6. Wire through the syscall layer

- `memory.recall()` → syscall resolves `contact_id` from session → calls `RecallBackend`
- `memory.remember_fact()` → syscall resolves `contact_id` from session → calls `TriplesStore.remember_fact()`
- `memory.query_facts()` → syscall resolves `contact_id` from session → calls `TriplesStore.query_facts()`
- `memory.update()` → syscall resolves `agent_id` from session → calls `write_memory(agent_id, content)`
- All write audit records (who stored/recalled what, for whom)
- Cross-contact access is impossible — the subject comes from the session, not the model

### 7. Create API routes

`backend/src/agentos/api/memory.py`:
- `GET /api/agents/{agent_id}/contacts/{contact_id}/memory` — list per-contact memory entries
- `DELETE /api/agents/{agent_id}/contacts/{contact_id}/memory` — clear per-contact memory
- `GET /api/agents/{agent_id}/memory/triples` — list knowledge graph triples
- `DELETE /api/agents/{agent_id}/memory/triples` — clear triples
- `GET /api/agents/{agent_id}/memory` — read MEMORY.md (D34, file in agent home dir)
- `PUT /api/agents/{agent_id}/memory` — update MEMORY.md (user edit; agent updates go through `memory.update` syscall)
- `GET /api/agents/{agent_id}/skills` — list skills
- `POST /api/agents/{agent_id}/skills` — create/upload skill
- `DELETE /api/agents/{agent_id}/skills/{name}` — delete skill

Note: `soul`, `persona`, and `task` are config fields on `AgentConfig`, so they are read/written via the standard agent config API (`GET/PUT /api/agents/{id}`, see [02-agent-config.md](02-agent-config.md)). They do not have separate routes — editing them creates a new `AgentVersion`.

## Files to create

- `backend/src/agentos/memory/__init__.py`
- `backend/src/agentos/memory/store.py` — FTS5 + embedding backends
- `backend/src/agentos/memory/triples.py` — knowledge graph
- `backend/src/agentos/memory/recall.py` — RecallBackend interface + FTS/Embedding implementations
- `backend/src/agentos/memory/notebook.py` — MEMORY.md file access (D34, agent home dir)
- `backend/src/agentos/memory/skills.py` — skill loading and trigger matching
- `backend/src/agentos/api/memory.py`
- `backend/tests/test_memory.py`

## Verification

- `memory.store` + `memory.recall` round-trip
- `memory.remember_fact` + `memory.query_facts` round-trip
- `memory.update` + context assembly round-trip (agent writes MEMORY.md → next run loads it)
- Cross-contact access impossible (Contact A stores → Contact B queries → gets nothing)
- MEMORY.md appears in context assembly
- `soul`, `persona`, `task` (config fields) appear in context assembly, in that order, before MEMORY.md
- Skill with trigger "research" → user says "research X" → skill body injected into context
- Skill without matching capability → skill instructions present but agent can't act on them
- FTS5 recall works by default (no embedding provider configured)
- Configure embedding provider in settings → recall switches to embeddings
- User edits `soul` via agent config API → new AgentVersion created → next run reflects changes
- User edits MEMORY.md via `PUT /api/agents/{id}/memory` → next run reflects changes (no new version)
- Audit record written for all memory operations (including `memory.update`)
- Model passes `memory.recall(contact_id="someone_else")` → denied (no contact_id parameter in schema)
- `uv run pytest tests/test_memory.py` passes
