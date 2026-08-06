"""Skills module — agent-loadable instruction bundles (D11b, D11c, D36).

Skills are NOT auto-injected into context. Instead:
1. The harness injects a *menu* of available skills (name + description) into
   the system prompt — lightweight, just lets the agent know what exists.
2. The agent calls `skills_list` to get the menu programmatically, or
   `skills_load(name)` to load a specific skill's full content + resources.
3. The user can also tell the agent to use a skill ("use the research skill").

Each skill is a directory: skills/{skill-name}/ containing:
- SKILL.md — YAML frontmatter (name, description, triggers) + markdown body
- Any other files (templates, checklists, data) — these are "resources" the
  skill body references. skills_load returns the SKILL.md + a file listing.

Two locations:
- System-level: skills/ (shared, agent-read-only, ships defaults)
- Per-agent: workspace/skills/{agent_id}/ (agent can create/update via file.write)
"""
