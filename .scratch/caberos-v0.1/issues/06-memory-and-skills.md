# 06 — Memory + skills

**What to build:** The agent remembers you across sessions. It has a curated notebook (MEMORY.md, in the agent home dir) that it updates when it learns something important, a knowledge graph of structured facts (triples), and semantic recall (FTS5 by default) for raw conversation snippets it didn't curate. The full context assembly is now complete: soul, persona, task, MEMORY.md, skills, knowledge graph facts, recent turns, semantic recall. Skills are markdown instruction files that inject into context when triggered — the user can add a "research" skill that tells the agent how to approach research tasks, and it only fires when the user's message matches the trigger.

**Blocked by:** 02 — Dashboard chat with real model (needs the harness, pipeline, and chat to exist so memory can be loaded into context and skills can inject).

**Status:** implemented

- [x] MEMORY.md: file at `~/agentos/agents/{agent_id}/MEMORY.md` (agent home dir, not workspace, not DB). Harness reads it at context assembly — always loaded. Agent updates it via `memory_update(content)` capability (audited syscall). User can edit it via `GET/PUT /api/agents/{id}/memory` (from ticket 05's UI). Not versioned with AgentVersion — living document.
- [x] Knowledge graph: `memory_triples` table (subject, predicate, object, contact_id, agent_id). Capabilities: `memory_remember_fact(entity, predicate, object)` and `memory_query_facts(entity?, predicate?, object?)`. Both subject-scoped (contact resolved from session, never model-supplied — D10). Note: the triple's "subject" field is exposed as `entity` in the capability schema to avoid colliding with D10's reserved `subject` parameter name.
- [x] Semantic recall: SQLite FTS5 on raw conversation snippets (default, $0). `memory_recall(query)` and `memory_store(text, key?, tags?)` route to FTS5. Postgres tsvector supported via the pluggable DB backend. EmbeddingBackend (configurable via embedding provider) is deferred — the RecallBackend interface is not yet abstracted; FTS5/tsvector is the only implementation.
- [x] Memory capabilities registered: `memory_recall`, `memory_store`, `memory_remember_fact`, `memory_query_facts`, `memory_update`. All subject-scoped (except `memory_update` which is agent-scoped). All audited.
- [x] Full context assembly (D35 order): soul → persona → task → MEMORY.md → relevant skills → KG facts → recall snippets (fallback). The harness loads KG facts and recall snippets from the DB before assembling the system prompt.
- [x] Skills: markdown files (`SKILL.md`) with YAML frontmatter (name, description, triggers) + markdown body + optional resource files (templates, checklists, data). Two locations: system-level `skills/` (shared, ships defaults) and per-agent `workspace/skills/{agent_id}/`. Skills are NOT auto-injected — the harness injects only a *menu* (names + descriptions) into the system prompt. The agent calls `skills_list` to discover skills, and `skills_load(name)` to load the full content + resource listing when it decides to use one (or when the user tells it to). Skills don't add capabilities — they're instructions + resources. $0 cost, file reads.
- [x] Cross-contact memory isolation: Contact A's memory is invisible to Contact B. The subject comes from the session, not the model. Tested as a security property (3 tests: triples, recall, syscall-level).
- [x] Clear memory: `DELETE /api/agents/{agent_id}/contacts/{contact_id}/memory` — clears per-contact memory (triples + entries). `DELETE /api/agents/{agent_id}/memory/triples` — clears triples (optional `contact_id` query param to scope).

## Deferred

- [ ] EmbeddingBackend: when the operator configures an embedding provider in settings, recall switches to embeddings + cosine similarity. The `RecallBackend` interface with `FTSBackend` and `EmbeddingBackend` is not yet abstracted — FTS5/tsvector is the only implementation. This is a future enhancement, not a blocker for v0.1.
- [ ] Bounded token budget for recall: currently returns top 3 snippets. A token-budget-based truncation is a future refinement.
