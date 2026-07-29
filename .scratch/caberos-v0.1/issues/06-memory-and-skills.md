# 06 — Memory + skills

**What to build:** The agent remembers you across sessions. It has a curated notebook (MEMORY.md, in the agent home dir) that it updates when it learns something important, a knowledge graph of structured facts (triples), and semantic recall (FTS5 by default) for raw conversation snippets it didn't curate. The full context assembly is now complete: soul, persona, task, MEMORY.md, skills, knowledge graph facts, recent turns, semantic recall. Skills are markdown instruction files that inject into context when triggered — the user can add a "research" skill that tells the agent how to approach research tasks, and it only fires when the user's message matches the trigger.

**Blocked by:** 02 — Dashboard chat with real model (needs the harness, pipeline, and chat to exist so memory can be loaded into context and skills can inject).

**Status:** ready-for-agent

- [ ] MEMORY.md: file at `~/agentos/agents/{agent_id}/MEMORY.md` (agent home dir, not workspace, not DB). Harness reads it at context assembly — always loaded. Agent updates it via `memory.update(content)` capability (audited syscall). User can edit it via `GET/PUT /api/agents/{id}/memory` (from ticket 05's UI). Not versioned with AgentVersion — living document.
- [ ] Knowledge graph: `memory_triples` table (subject, predicate, object, contact_id, agent_id). Capabilities: `memory.remember_fact(subject, predicate, object)` and `memory.query_facts(subject?, predicate?, object?)`. Both subject-scoped (contact resolved from session, never model-supplied — D10).
- [ ] Semantic recall: SQLite FTS5 on raw conversation snippets (default, $0). Configurable: if operator sets an embedding provider in settings, recall uses embeddings + cosine similarity. `RecallBackend` interface with `FTSBackend` and `EmbeddingBackend`. `memory.recall(query)` routes to the configured backend. Bounded token budget per call — agent receives a summary, not the raw store.
- [ ] Memory capabilities registered: `memory.recall`, `memory.store`, `memory.remember_fact`, `memory.query_facts`, `memory.update`. All subject-scoped (except `memory.update` which is agent-scoped). All audited.
- [ ] Full context assembly (D35 order): soul → persona → task → MEMORY.md → relevant skills → KG facts → recent turns → semantic recall (fallback). This replaces the partial assembly from earlier tickets.
- [ ] Skills: markdown files (`SKILL.md`) with YAML frontmatter (name, description, triggers) + markdown body. Two locations: system-level `skills/` (shared, ships defaults) and per-agent `workspace/skills/{agent_id}/`. Harness scans skills at context assembly, matches triggers against user message, injects matching skill bodies. Skills don't add capabilities — they're instructions only. $0 cost, file reads.
- [ ] Cross-contact memory isolation: Contact A's memory is invisible to Contact B. The subject comes from the session, not the model. Tested as a security property.
- [ ] Clear memory: `DELETE /api/agents/{agent_id}/contacts/{contact_id}/memory` — clears per-contact memory. `DELETE /api/agents/{agent_id}/memory/triples` — clears triples.
