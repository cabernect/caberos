"""Worked examples for activation accounting and frozen evidence boundaries."""

from datetime import UTC, datetime, timedelta

import pytest

from agentos.memory.history_queries import freeze_session_evidence, read_frozen_evidence
from agentos.models.agent import Agent
from agentos.models.contact import Contact
from agentos.models.run import Message, Run
from agentos.models.session import Session
from agentos.models.skill import Skill
from agentos.models.skill_usage import SkillActivation
from agentos.skills.usage_queries import scoped_skill_usage, skill_usage_totals


async def seed_scope(db):
    db.add_all([Agent(id="owner", name="Owner"), Agent(id="other", name="Other")])
    await db.flush()
    db.add_all(
        [
            Contact(id="c1", channel="dashboard_chat", bot_id="owner", external_user_id="u1"),
            Contact(id="c2", channel="dashboard_chat", bot_id="owner", external_user_id="u2"),
            Contact(id="c3", channel="dashboard_chat", bot_id="other", external_user_id="u3"),
        ]
    )
    await db.flush()
    db.add_all(
        [
            Session(id="s1", agent_id="owner", contact_id="c1"),
            Session(id="s2", agent_id="owner", contact_id="c2"),
            Session(id="s3", agent_id="other", contact_id="c3"),
        ]
    )
    await db.flush()
    for rid, sid, aid, cid, trigger, is_test in (
        ("r1", "s1", "owner", "c1", "user_message", False),
        ("r2", "s2", "owner", "c2", "user_message", False),
        ("r3", "s3", "other", "c3", "user_message", False),
        ("reflection", "s1", "owner", "c1", "reflection", False),
        ("test", "s1", "owner", "c1", "user_message", True),
    ):
        db.add(
            Run(
                id=rid,
                session_id=sid,
                agent_id=aid,
                contact_id=cid,
                trigger=trigger,
                is_test=is_test,
                status="completed",
            )
        )
    db.add_all(
        [
            Skill(id="shared", name="report", scope="global", status="published"),
            Skill(
                id="local",
                name="report",
                scope="agent-local",
                owner_agent_id="owner",
                status="published",
            ),
        ]
    )
    await db.flush()


@pytest.mark.asyncio
async def test_totals_are_all_recorded_activations_not_recent_page_size(db):
    await seed_scope(db)
    first = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(205):
        db.add(
            SkillActivation(
                skill_id="shared",
                name="report",
                scope="global",
                run_id="r1",
                agent_id="owner",
                source="load",
                call_id=f"call-{index}",
                event_key=f"call-{index}",
                created_at=first + timedelta(minutes=index),
            )
        )
    for key, rid, aid, sid in (
        ("second-contact", "r2", "owner", "shared"),
        ("second-agent", "r3", "other", "shared"),
        ("local-version", "r1", "owner", "local"),
        ("reflection-excluded", "reflection", "owner", "shared"),
        ("test-excluded", "test", "owner", "shared"),
        ("mismatched-agent-excluded", "r1", "other", "shared"),
    ):
        db.add(
            SkillActivation(
                skill_id=sid,
                name="report",
                scope="global" if sid == "shared" else "agent-local",
                run_id=rid,
                agent_id=aid,
                source="load",
                event_key=key,
                created_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )
    await db.commit()

    totals = await skill_usage_totals(db, ["shared", "local", "missing"])
    assert totals["shared"]["activation_count"] == 207
    assert totals["shared"]["last_used_at"] == "2026-01-02T00:00:00+00:00"
    assert totals["local"]["activation_count"] == 1
    assert "missing" not in totals

    own = await scoped_skill_usage(db, skill_id="shared", agent_id="owner", contact_id="c1")
    assert own["activation_count"] == 205
    assert own["last_used_at"] == "2026-01-01T03:24:00+00:00"
    assert len(own["recent"]) == 20
    assert {row["run_id"] for row in own["recent"]} == {"r1"}
    assert {row["session_id"] for row in own["recent"]} == {"s1"}
    assert await skill_usage_totals(db, []) == {}


@pytest.mark.asyncio
async def test_evidence_is_frozen_subject_scoped_and_content_can_be_continued(db):
    await seed_scope(db)
    db.add_all(
        [
            Message(id="original", run_id="r1", role="user", content="a" * 4000 + "END", seq=0),
            Message(id="observation", run_id="r1", role="tool", content="observed failure", seq=1),
            Message(id="private", run_id="r2", role="user", content="other contact", seq=0),
            Message(id="other", run_id="r3", role="user", content="other agent", seq=0),
            Message(id="internal", run_id="reflection", role="assistant", content="reflection"),
            Message(id="scripted", run_id="test", role="user", content="test"),
            Message(
                id="nested", run_id="r1", role="assistant", content="nested", subagent_id="sub"
            ),
        ]
    )
    await db.commit()
    scope = {
        "session_id": "s1",
        "agent_id": "owner",
        "contact_id": "c1",
        "run_ids": ["r1", "r2", "r3", "reflection", "test"],
    }
    frozen = await freeze_session_evidence(db, **scope)
    assert [row.id for row in frozen] == ["original", "observation"]
    db.add(Message(id="later", run_id="r1", role="assistant", content="arrived later", seq=2))
    await db.commit()
    frozen_ids = [row.id for row in frozen]
    page = await read_frozen_evidence(db, **scope, message_ids=frozen_ids, limit=1)
    assert [row["message_id"] for row in page["rows"]] == ["original"]
    assert page["rows"][0]["content"] == "a" * 4000
    assert page["rows"][0]["next_content_offset"] == 4000
    assert page["next_offset"] == 1
    continuation = await read_frozen_evidence(
        db, **scope, message_ids=frozen_ids, message_id="original", content_offset=4000
    )
    assert continuation["rows"][0]["content"] == "END"
    assert continuation["rows"][0]["next_content_offset"] is None
    next_page = await read_frozen_evidence(db, **scope, message_ids=frozen_ids, offset=1)
    assert [row["message_id"] for row in next_page["rows"]] == ["observation"]
    assert next_page["next_offset"] is None
    foreign = await read_frozen_evidence(db, **scope, message_ids=frozen_ids, run_id="r2")
    assert foreign["rows"] == []
    with pytest.raises(ValueError, match="specific message_id"):
        await read_frozen_evidence(db, **scope, message_ids=frozen_ids, content_offset=1)
