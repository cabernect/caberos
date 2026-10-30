"""Skill activation tracking — immutable events, list totals, scoped usage.

Activations write one immutable row per successful skills_load or forced
injection; replayed calls dedup on event_key; shadowed same-name skills
never merge; totals cover ALL retained records.
"""

import pytest
from sqlalchemy import select

from agentos.config_schema import AgentConfig, Limits, ModelConfig
from agentos.models.contact import Contact
from agentos.models.run import Message, Run
from agentos.models.session import Session
from agentos.models.skill import Skill, SkillRevision
from agentos.models.skill_usage import SkillActivation


def _cfg(agent_id="qa-agent"):
    return AgentConfig(
        id=agent_id,
        name="QA",
        model=ModelConfig(provider_id="p", name="m"),
        limits=Limits(),
    )


async def _seed(db, agent_id="qa-agent"):
    from agentos.agent_service import create_agent

    cfg = _cfg(agent_id)
    await create_agent(db, cfg)
    db.add(Contact(id="c1", channel="dashboard_chat", bot_id=agent_id, external_user_id="u1"))
    db.add(Session(id="s1", contact_id="c1", agent_id=agent_id))
    db.add(
        Run(
            id="r1",
            session_id="s1",
            contact_id="c1",
            agent_id=agent_id,
            status="completed",
            trigger="user_message",
        )
    )
    db.add(Message(id="m1", run_id="r1", role="user", content="hi", seq=0))
    await db.commit()
    return cfg


async def _global_skill(db, tmp_path, name="gskill"):
    from agentos.skills.loader import _load_skill_from_dir  # noqa

    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n---\nBody", encoding="utf-8"
    )
    skill = Skill(name=name, scope="global", status="published", availability="all")
    db.add(skill)
    await db.flush()
    rev = SkillRevision(
        skill_id=skill.id,
        revision_number=1,
        storage_path=str(d),
        content_hash="h",
        change_summary=None,
    )
    db.add(rev)
    skill.current_revision_id = rev.id
    await db.commit()
    return skill


class _Resolved:
    def __init__(self, name, scope, skill_id, path):
        self.name = name
        self.scope = scope
        self.skill_id = skill_id
        self.path = path


@pytest.mark.asyncio
async def test_load_counts_each_call_replay_dedups(db, tmp_path):
    from agentos.skills.usage import record_skill_activation

    await _seed(db)
    skill = await _global_skill(db, tmp_path)
    r = _Resolved("gskill", "global", skill.id, skill.name)

    id1 = await record_skill_activation(db, r, "r1", "load", call_id="c-1")
    id2 = await record_skill_activation(db, r, "r1", "load", call_id="c-2")
    replay = await record_skill_activation(db, r, "r1", "load", call_id="c-1")
    assert id1 is not None and id2 is not None and id1 != id2
    assert replay == id1  # replay of the same call — no new row
    count = (await db.execute(select(SkillActivation))).scalars().all()
    assert len(count) == 2


@pytest.mark.asyncio
async def test_forced_once_per_run(db, tmp_path):
    from agentos.skills.usage import record_skill_activation

    await _seed(db)
    skill = await _global_skill(db, tmp_path)
    r = _Resolved("gskill", "global", skill.id, skill.name)

    a = await record_skill_activation(db, r, "r1", "forced")
    b = await record_skill_activation(db, r, "r1", "forced")
    assert a is not None and b == a  # same event_key — once per run
    assert len((await db.execute(select(SkillActivation))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_invalid_and_test_runs_record_nothing(db, tmp_path):
    from agentos.skills.usage import record_skill_activation

    await _seed(db)
    skill = await _global_skill(db, tmp_path)
    r = _Resolved("gskill", "global", skill.id, skill.name)

    assert await record_skill_activation(db, r, "missing-run", "load", call_id="x") is None
    assert await record_skill_activation(db, r, None, "load", call_id="x") is None
    db.add(
        Run(
            id="rt",
            session_id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            status="completed",
            trigger="user_message",
            is_test=True,
        )
    )
    db.add(
        Run(
            id="rr",
            session_id="s1",
            contact_id="c1",
            agent_id="qa-agent",
            status="completed",
            trigger="reflection",
        )
    )
    await db.commit()
    assert await record_skill_activation(db, r, "rt", "load", call_id="x") is None
    assert await record_skill_activation(db, r, "rr", "load", call_id="x") is None
    assert (await db.execute(select(SkillActivation))).scalars().all() == []


@pytest.mark.asyncio
async def test_shadow_scopes_never_merge(db, tmp_path, monkeypatch):
    """Same name under different scope/owner keeps separate identities."""
    from agentos.skills.usage import record_skill_activation

    await _seed(db)
    g = await _global_skill(db, tmp_path, "shared")
    # Agent-local live dir — indexed on demand by record_skill_activation.
    local_dir = tmp_path / "wsroot" / "qa-agent" / "skills" / "shared"
    local_dir.mkdir(parents=True)
    (local_dir / "SKILL.md").write_text(
        "---\nname: shared\ndescription: local\n---\nLocal", encoding="utf-8"
    )
    from agentos.config import settings

    monkeypatch.setattr(settings, "workspace_root", tmp_path / "wsroot")

    rg = _Resolved("shared", "global", g.id, None)
    rl = _Resolved("shared", "agent-local", None, local_dir)
    idg = await record_skill_activation(db, rg, "r1", "load", call_id="g1")
    idl = await record_skill_activation(db, rl, "r1", "load", call_id="l1")
    rows = (await db.execute(select(SkillActivation))).scalars().all()
    assert len(rows) == 2 and idg != idl
    ids = {r.skill_id for r in rows}
    assert len(ids) == 2  # separate stable identities — never merged
    assert any(r.scope == "agent-local" and r.owner_agent_id == "qa-agent" for r in rows)


@pytest.mark.asyncio
async def test_totals_and_scoped_usage(db, tmp_path):
    from agentos.skills.usage import record_skill_activation
    from agentos.skills.usage_queries import scoped_skill_usage, skill_usage_totals

    await _seed(db)
    g = await _global_skill(db, tmp_path)
    r = _Resolved("gskill", "global", g.id, None)
    for i in range(5):
        await record_skill_activation(db, r, "r1", "load", call_id=f"c-{i}")
    await record_skill_activation(db, r, "r1", "forced")

    totals = await skill_usage_totals(db, [g.id, "other"])
    assert totals[g.id]["activation_count"] == 6
    assert totals[g.id]["last_used_at"] is not None
    assert "other" not in totals

    scoped = await scoped_skill_usage(db, skill_id=g.id, agent_id="qa-agent", contact_id="c1")
    assert scoped["activation_count"] == 6
    assert len(scoped["recent"]) == 6
    wrong = await scoped_skill_usage(
        db, skill_id=g.id, agent_id="qa-agent", contact_id="someone-else"
    )
    assert wrong["activation_count"] == 0
