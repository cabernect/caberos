"""Tests for the memory system (ticket 06 — D34, D10, D11b).

Covers:
- MEMORY.md read/write (notebook)
- Knowledge graph triples (remember_fact, query_facts)
- Semantic recall (FTS5 store + recall)
- Cross-contact isolation (security property — D10)
- Skills loading + trigger matching
- Context assembly includes MEMORY.md
"""

import pytest

from agentos.capabilities.builtin import register_builtin_capabilities
from agentos.capabilities.registry import registry
from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
from agentos.syscall.mediator import SyscallHandler
from agentos.syscall.protocol import ToolCall


@pytest.fixture(autouse=True)
def _setup_caps():
    registry._caps.clear()
    register_builtin_capabilities()
    yield
    registry._caps.clear()


def _make_agent_config(caps: list[str] | None = None) -> AgentConfig:
    if caps is None:
        # All tools enabled by default (capabilities=None)
        return AgentConfig(
            id="test-agent",
            name="Test Agent",
            model=ModelConfig(provider_id="test-provider", name="test-model"),
        )
    return AgentConfig(
        id="test-agent",
        name="Test Agent",
        model=ModelConfig(provider_id="test-provider", name="test-model"),
        capabilities=[CapabilityGrant(name=c) for c in caps],
    )


def _make_session(contact_id: str):
    from types import SimpleNamespace

    return SimpleNamespace(contact_id=contact_id, id="test-session-id")


async def _create_contact(db, contact_id: str, agent_id: str = "test-agent"):
    """Create a Contact row in the DB for subject-scoped cap tests."""
    from agentos.models.contact import Contact

    contact = Contact(
        id=contact_id,
        channel="dashboard_chat",
        bot_id=agent_id,
        external_user_id=contact_id,
        display_name="Test Contact",
    )
    db.add(contact)
    await db.flush()
    return contact


class TestNotebook:
    """MEMORY.md read/write (D34)."""

    def test_read_empty_when_no_file(self, tmp_path, monkeypatch):
        from agentos.memory.notebook import read_memory

        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)
        assert read_memory("test-agent") == ""

    def test_write_then_read(self, tmp_path, monkeypatch):
        from agentos.memory.notebook import read_memory, write_memory

        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)
        write_memory("test-agent", "# Memory\n\nUser likes dark mode.")
        assert "dark mode" in read_memory("test-agent")


class TestTriples:
    """Knowledge graph — remember_fact + query_facts (D34, D10)."""

    async def test_remember_and_query_fact(self, db):
        from agentos.memory.triples import query_facts, remember_fact

        await _create_contact(db, "contact-1")
        await remember_fact(
            db,
            "contact-1",
            "test-agent",
            subject="user",
            predicate="prefers",
            object="dark mode",
        )
        await db.commit()

        facts = await query_facts(db, "contact-1", "test-agent", subject="user")
        assert len(facts) == 1
        assert facts[0]["object"] == "dark mode"

    async def test_cross_contact_isolation(self, db):
        """Contact A's facts are invisible to Contact B (D10)."""
        from agentos.memory.triples import query_facts, remember_fact

        await _create_contact(db, "contact-a")
        await _create_contact(db, "contact-b")

        await remember_fact(
            db,
            "contact-a",
            "test-agent",
            subject="user",
            predicate="name",
            object="Alice",
        )
        await db.commit()

        # Contact B queries — gets nothing
        facts = await query_facts(db, "contact-b", "test-agent", subject="user")
        assert facts == []

        # Contact A queries — gets the fact
        facts = await query_facts(db, "contact-a", "test-agent", subject="user")
        assert len(facts) == 1

    async def test_query_with_filters(self, db):
        from agentos.memory.triples import query_facts, remember_fact

        await _create_contact(db, "contact-1")
        await remember_fact(db, "contact-1", "test-agent", "user", "likes", "pizza")
        await remember_fact(db, "contact-1", "test-agent", "user", "likes", "sushi")
        await remember_fact(db, "contact-1", "test-agent", "user", "dislikes", "cilantro")
        await db.commit()

        likes = await query_facts(db, "contact-1", "test-agent", predicate="likes")
        assert len(likes) == 2

        all_facts = await query_facts(db, "contact-1", "test-agent")
        assert len(all_facts) == 3


class TestRecall:
    """Semantic recall — FTS5 store + recall (D34)."""

    async def test_store_and_recall(self, db):
        from agentos.memory.recall import recall_snippets, store_snippet

        await _create_contact(db, "contact-1")
        await store_snippet(
            db, "contact-1", "test-agent", "preference", "User prefers dark mode in the IDE"
        )
        await store_snippet(db, "contact-1", "test-agent", "note", "The meeting is on Tuesday")
        await db.commit()

        results = await recall_snippets(db, "contact-1", "test-agent", "dark mode")
        assert len(results) >= 1
        assert "dark mode" in results[0]["value"]

    async def test_cross_contact_recall_isolation(self, db):
        """Contact A's snippets are invisible to Contact B (D10)."""
        from agentos.memory.recall import recall_snippets, store_snippet

        await _create_contact(db, "contact-a")
        await _create_contact(db, "contact-b")

        await store_snippet(
            db, "contact-a", "test-agent", "secret", "Alice's secret password is 1234"
        )
        await db.commit()

        # Contact B searches — gets nothing
        results = await recall_snippets(db, "contact-b", "test-agent", "secret password")
        assert results == []


class TestSkills:
    """Skill loading — list (menu) + load (full content) (D11b, D11c, Agent Skills spec)."""

    def test_parse_frontmatter(self):
        from agentos.skills.loader import _parse_frontmatter

        content = (
            "---\nname: pdf\ndescription: PDF processing skill\n"
            "license: Apache-2.0\n---\n\nDo PDF things."
        )
        fm, body = _parse_frontmatter(content)
        assert fm["name"] == "pdf"
        assert fm["description"] == "PDF processing skill"
        assert fm["license"] == "Apache-2.0"
        assert body == "Do PDF things."

    def test_list_skills_returns_menu_only(self, tmp_path, monkeypatch):
        """list_skills returns name + description, NOT the body."""
        from agentos.skills.loader import list_skills

        skill_dir = tmp_path / "skills" / "research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: research\ndescription: Research skill\n---\n\nSecret instructions."
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        skills = list_skills("test-agent")
        assert len(skills) == 1
        assert skills[0]["name"] == "research"
        assert skills[0]["description"] == "Research skill"
        # Body should NOT be in the list result
        assert "body" not in skills[0]
        assert "Secret instructions" not in str(skills[0])

    def test_load_skill_returns_full_content(self, tmp_path, monkeypatch):
        """load_skill returns the full body + resource listing."""
        from agentos.skills.loader import load_skill

        skill_dir = tmp_path / "skills" / "research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: research\ndescription: Research skill\n---\n\nDo research thoroughly."
        )
        # Add a resource file
        (skill_dir / "template.md").write_text("# Template\n\nUse this.")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        skill = load_skill("test-agent", "research")
        assert skill is not None
        assert skill["name"] == "research"
        assert "thorough" in skill["body"]
        # Resources should list template.md
        resource_names = [r["name"] for r in skill["resources"]]
        assert "template.md" in resource_names

    def test_load_skill_with_spec_fields(self, tmp_path, monkeypatch):
        """load_skill includes optional spec fields (license, compatibility, allowed_tools)."""
        from agentos.skills.loader import load_skill

        skill_dir = tmp_path / "skills" / "pdf"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: pdf\ndescription: PDF processing\n"
            "license: Apache-2.0\ncompatibility: Requires Python 3.12+\n"
            'allowed-tools: read_file write_file terminal\n---\n\nBody.'
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        skill = load_skill("test-agent", "pdf")
        assert skill is not None
        assert skill["license"] == "Apache-2.0"
        assert "Python 3.12" in skill["compatibility"]
        assert "read_file" in skill["allowed_tools"]

    def test_load_skill_with_subdirectories(self, tmp_path, monkeypatch):
        """load_skill lists subdirectories (scripts/, references/, assets/)."""
        from agentos.skills.loader import load_skill

        skill_dir = tmp_path / "skills" / "pdf"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: pdf\ndescription: PDF\n---\n\nBody.")
        (skill_dir / "scripts").mkdir()
        (skill_dir / "scripts" / "extract.py").write_text("# extract")
        (skill_dir / "references").mkdir()
        (skill_dir / "references" / "reference.md").write_text("# Reference")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        skill = load_skill("test-agent", "pdf")
        resource_names = [r["name"] for r in skill["resources"]]
        assert "scripts" in resource_names
        assert "references" in resource_names

    def test_load_nonexistent_skill_returns_none(self, tmp_path, monkeypatch):
        from agentos.skills.loader import load_skill

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        skill = load_skill("test-agent", "nonexistent")
        assert skill is None

    def test_format_skill_menu(self, tmp_path, monkeypatch):
        """format_skill_menu produces a lightweight menu for the system prompt."""
        from agentos.skills.loader import format_skill_menu

        skill_dir = tmp_path / "skills" / "research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: research\ndescription: Research skill\n---\n\nSecret body."
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        menu = format_skill_menu("test-agent")
        assert "research" in menu
        assert "Research skill" in menu
        # Body should NOT be in the menu
        assert "Secret body" not in menu

    def test_empty_skill_menu(self, tmp_path, monkeypatch):
        from agentos.skills.loader import format_skill_menu

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        menu = format_skill_menu("test-agent")
        assert menu == ""


class TestContextAssembly:
    """Context assembly includes MEMORY.md (D35)."""

    def test_memory_md_in_system_prompt(self, tmp_path, monkeypatch):
        from agentos.harness.context import assemble_system_prompt
        from agentos.memory.notebook import write_memory

        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)
        write_memory("test-agent", "# Memory\n\nUser likes dark mode.")

        agent = _make_agent_config()
        prompt = assemble_system_prompt(agent, "hello")
        assert "MEMORY.md" in prompt
        assert "dark mode" in prompt

    def test_no_memory_md_when_empty(self, tmp_path, monkeypatch):
        from agentos.harness.context import assemble_system_prompt

        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)

        agent = _make_agent_config()
        prompt = assemble_system_prompt(agent, "hello")
        # The base prompt mentions MEMORY.md as a concept, but the actual
        # section header "## MEMORY.md" only appears when content is loaded
        assert "## MEMORY.md" not in prompt

    def test_kg_facts_in_system_prompt(self, tmp_path, monkeypatch):
        from agentos.harness.context import assemble_system_prompt

        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)

        agent = _make_agent_config()
        facts = [
            {"subject": "user", "predicate": "prefers", "object": "dark mode"},
            {"subject": "user", "predicate": "likes", "object": "pizza"},
        ]
        prompt = assemble_system_prompt(agent, "hello", kg_facts=facts)
        assert "Known Facts" in prompt
        assert "dark mode" in prompt
        assert "pizza" in prompt

    def test_recall_snippets_in_system_prompt(self, tmp_path, monkeypatch):
        from agentos.harness.context import assemble_system_prompt

        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)

        agent = _make_agent_config()
        snippets = [
            {"key": "preference", "value": "User likes dark mode in the IDE"},
        ]
        prompt = assemble_system_prompt(agent, "hello", recall_snippets=snippets)
        assert "Relevant Past Context" in prompt
        assert "dark mode" in prompt

    def test_forced_skill_in_system_prompt(self, tmp_path, monkeypatch):
        """Slash command /skillname injects the skill body into context."""
        from agentos.harness.context import assemble_system_prompt

        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)

        # Create a system-level skill
        skill_dir = tmp_path / "skills" / "pdf"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: pdf\ndescription: PDF processing\n---\n\n# PDF Guide\n\nExtract text with pypdf."
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")
        agent = _make_agent_config()
        prompt = assemble_system_prompt(agent, "extract text", forced_skill="pdf")
        assert "Active Skill: pdf" in prompt
        assert "PDF Guide" in prompt
        assert "pypdf" in prompt


class TestMemoryCapabilities:
    """Memory capabilities through the syscall layer (D10, D34)."""

    async def test_memory_remember_fact_via_syscall(self, db, workspace):
        await _create_contact(db, "contact-1")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(
                id="1",
                name="memory_remember_fact",
                args={"entity": "user", "predicate": "likes", "object": "pizza"},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["remembered"] is True
        assert result.output["object"] == "pizza"

    async def test_memory_query_facts_via_syscall(self, db, workspace):
        await _create_contact(db, "contact-1")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        # Store a fact first
        await handler.mediate(
            call=ToolCall(
                id="1",
                name="memory_remember_fact",
                args={"entity": "user", "predicate": "likes", "object": "pizza"},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        # Query it
        result = await handler.mediate(
            call=ToolCall(
                id="2",
                name="memory_query_facts",
                args={"entity": "user"},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["count"] == 1
        assert result.output["facts"][0]["object"] == "pizza"

    async def test_cross_contact_isolation_via_syscall(self, db, workspace):
        """Contact A stores a fact, Contact B can't see it (D10)."""
        await _create_contact(db, "contact-a")
        await _create_contact(db, "contact-b")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()

        # Contact A stores
        await handler.mediate(
            call=ToolCall(
                id="1",
                name="memory_remember_fact",
                args={"entity": "user", "predicate": "name", "object": "Alice"},
            ),
            session=_make_session("contact-a"),
            agent_config=agent_config,
            run_id="run-1",
        )

        # Contact B queries
        result = await handler.mediate(
            call=ToolCall(
                id="2",
                name="memory_query_facts",
                args={"entity": "user"},
            ),
            session=_make_session("contact-b"),
            agent_config=agent_config,
            run_id="run-2",
        )

        assert result.allowed is True
        assert result.output["count"] == 0

    async def test_memory_update_via_syscall(self, db, workspace, tmp_path, monkeypatch):
        """memory_update writes MEMORY.md (agent-scoped, not contact-scoped)."""
        monkeypatch.setattr("agentos.memory.notebook.settings.agent_home_root", tmp_path)

        await _create_contact(db, "contact-1")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(
                id="1",
                name="memory_update",
                args={"content": "# Memory\n\nUser likes dark mode."},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["updated"] is True

        # Verify the file was written
        from agentos.memory.notebook import read_memory

        assert "dark mode" in read_memory("test-agent")

    async def test_memory_capability_requires_contact(self, db, workspace):
        """Subject-scoped memory caps fail if no Contact exists for the session."""
        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("nonexistent-contact")

        result = await handler.mediate(
            call=ToolCall(
                id="1",
                name="memory_remember_fact",
                args={"entity": "user", "predicate": "likes", "object": "pizza"},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is False
        assert "no subject binding" in (result.denied_reason or "")


class TestSkillCapabilities:
    """Skill capabilities through the syscall layer (D11b, D11c)."""

    async def test_skills_list_via_syscall(self, db, workspace, tmp_path, monkeypatch):
        """skills_list returns the menu (name + description, no body)."""
        # Create a system-level skill
        skill_dir = tmp_path / "skills" / "research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: research\ndescription: Research skill\n---\n\nSecret instructions."
        )

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="skills_list", args={}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["count"] == 1
        assert result.output["skills"][0]["name"] == "research"
        # Body should NOT be in the list result
        assert "body" not in result.output["skills"][0]
        assert "Secret instructions" not in str(result.output["skills"])

    async def test_skills_load_via_syscall(self, db, workspace, tmp_path, monkeypatch):
        """skills_load returns the full body + resources."""
        skill_dir = tmp_path / "skills" / "research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: research\ndescription: Research skill\n---\n\nDo research thoroughly."
        )
        (skill_dir / "checklist.md").write_text("# Checklist\n\n- Step 1")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="skills_load", args={"name": "research"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["name"] == "research"
        assert "thorough" in result.output["body"]
        # Resources should list checklist.md
        resource_names = [r["name"] for r in result.output["resources"]]
        assert "checklist.md" in resource_names

    async def test_skills_load_nonexistent(self, db, workspace, tmp_path, monkeypatch):
        """skills_load on a nonexistent skill returns an error."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(id="1", name="skills_load", args={"name": "nonexistent"}),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert "error" in result.output

    async def test_skills_read_resource_via_syscall(self, db, workspace, tmp_path, monkeypatch):
        """skills_read_resource reads a resource file from a skill directory."""
        skill_dir = tmp_path / "skills" / "research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: research\ndescription: Research skill\n---\n\nFollow the checklist."
        )
        (skill_dir / "checklist.md").write_text("# Research Checklist\n\n- [ ] Define scope\n- [ ] Search")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(
                id="1",
                name="skills_read_resource",
                args={"skill": "research", "resource": "checklist.md"},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert result.output["skill"] == "research"
        assert result.output["resource"] == "checklist.md"
        assert "Research Checklist" in result.output["content"]

    async def test_skills_read_resource_path_escape_blocked(self, db, workspace, tmp_path, monkeypatch):
        """skills_read_resource blocks path traversal outside the skill dir."""
        skill_dir = tmp_path / "skills" / "research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: research\n---\n\nBody.")

        (tmp_path / "secret.txt").write_text("passwords")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("agentos.config.settings.skills_dir", tmp_path / "skills")

        handler = SyscallHandler(db=db, workspace_path=workspace)
        agent_config = _make_agent_config()
        session = _make_session("contact-1")

        result = await handler.mediate(
            call=ToolCall(
                id="1",
                name="skills_read_resource",
                args={"skill": "research", "resource": "../../secret.txt"},
            ),
            session=session,
            agent_config=agent_config,
            run_id="run-1",
        )

        assert result.allowed is True
        assert "error" in result.output
        assert "escapes" in result.output["error"]
