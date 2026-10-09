"""filter_runs regressions — same-row model match, retrieval JSON guards,
exact effect membership, malformed payload safety."""

import json
from datetime import datetime

from sqlalchemy import select

from agentos.models.artifact import Artifact, ArtifactRevision
from agentos.models.audit import AuditRecord
from agentos.models.execution_manifest import ExecutionManifest
from agentos.models.model_call import ModelCall
from agentos.models.run import Run
from agentos.models.schedule import ScheduleOccurrence
from agentos.models.session import Session
from agentos.services.observability_filters import filter_runs


async def _ids(db, stmt):
    return {r.id for r in (await db.execute(stmt)).scalars().all()}


def _run(db, rid, session_id="s", is_test=False):
    db.add(Run(id=rid, session_id=session_id, contact_id="c", agent_id="a", is_test=is_test))


def _call(db, cid, run_id, provider, model, kind="chat", purpose="reasoning"):
    db.add(
        ModelCall(
            id=cid,
            run_id=run_id,
            agent_id="a",
            provider_id=provider,
            model_name=model,
            kind=kind,
            purpose=purpose,
            status="ok",
        )
    )


def _audit(db, aid, run_id, capability, args="{}", result=None, outcome="ok", effects=None):
    db.add(
        AuditRecord(
            id=aid,
            run_id=run_id,
            agent_id="a",
            capability_name=capability,
            allowed=outcome == "ok",
            outcome=outcome,
            args=args,
            result=result,
            effects=effects,
        )
    )


async def test_model_filters_must_match_the_same_call(db):
    """provider+model must land on ONE call, not two different calls —
    r1 has (p1,m1) and (p2,m2), r2 has (p1,m2)."""
    _run(db, "r1")
    _run(db, "r2")
    _call(db, "c1", "r1", "p1", "m1")
    _call(db, "c2", "r1", "p2", "m2")
    _call(db, "c3", "r2", "p1", "m2")
    await db.commit()

    stmt = filter_runs(select(Run), db, provider_id="p1", model="m2")
    assert await _ids(db, stmt) == {"r2"}
    stmt = filter_runs(select(Run), db, provider_id="p1")
    assert await _ids(db, stmt) == {"r1", "r2"}


async def test_multiple_calls_do_not_duplicate_runs(db):
    """A run with two matching calls must appear once."""
    _run(db, "r1")
    _call(db, "c1", "r1", "p1", "m1")
    _call(db, "c2", "r1", "p1", "m1")
    await db.commit()

    stmt = filter_runs(select(Run), db, provider_id="p1")
    rows = (await db.execute(stmt)).scalars().all()
    assert [r.id for r in rows] == ["r1"]


async def test_retrieval_filters_separate_valid_degraded_and_malformed(db):
    """JSON null/malformed trace must match neither degraded=True nor False."""
    _run(db, "hybrid")
    _audit(
        db,
        "a-hy",
        "hybrid",
        "doc_search",
        result=json.dumps({"trace": {"fusion": "hybrid", "degraded": ["why"]}}),
    )
    _run(db, "lexical")
    _audit(
        db,
        "a-lex",
        "lexical",
        "doc_search",
        result=json.dumps({"trace": {"fusion": "lexical", "degraded": []}}),
    )
    _run(db, "broken")
    _audit(db, "a-bad", "broken", "doc_search", result="not json")
    await db.commit()

    stmt = filter_runs(select(Run), db, retrieval_degraded=False)
    assert await _ids(db, stmt) == {"lexical"}
    stmt = filter_runs(select(Run), db, retrieval_degraded=True)
    assert await _ids(db, stmt) == {"hybrid"}
    stmt = filter_runs(select(Run), db, retrieval_mode="hybrid")
    assert await _ids(db, stmt) == {"hybrid"}


async def test_effect_membership_is_exact(db):
    """'write' must not match 'write_file'; legacy NULL effects excluded."""
    _run(db, "r-write")
    _audit(db, "a-1", "r-write", "write_file", effects=["write"])
    _run(db, "r-writefile")
    _audit(db, "a-2", "r-writefile", "write_file", effects=["write_file"])
    _run(db, "r-legacy")
    _audit(db, "a-3", "r-legacy", "write_file")  # effects NULL
    await db.commit()

    stmt = filter_runs(select(Run), db, effect="write")
    assert await _ids(db, stmt) == {"r-write"}
    stmt = filter_runs(select(Run), db, effect="write_file")
    assert await _ids(db, stmt) == {"r-writefile"}


async def test_audit_effects_snapshot_survives_registry_changes(db, monkeypatch):
    """The snapshot on the audit row is what the filter sees — not whatever
    the registry declares today."""
    from agentos.capabilities.registry import registry

    _run(db, "r-snap")
    _audit(db, "a-s", "r-snap", "terminal", effects=["local_execute"])
    await db.commit()

    cap = registry.get("terminal")
    original = cap.effects
    monkeypatch.setattr(cap, "effects", frozenset({"read"}))
    try:
        stmt = filter_runs(select(Run), db, effect="local_execute")
        assert await _ids(db, stmt) == {"r-snap"}
        stmt = filter_runs(select(Run), db, effect="read")
        assert await _ids(db, stmt) == set()
    finally:
        assert cap.effects == frozenset({"read"}) or original


async def test_malformed_json_listing_does_not_crash(db):
    """Hand-edited/legacy text in args/result never breaks a filtered list."""
    _run(db, "r-bad")
    _audit(db, "a-bad", "r-bad", "browser_open", args="not json", result="still not json")
    _run(db, "r-good")
    _audit(db, "a-good", "r-good", "browser_open", args=json.dumps({"profile": "work"}))
    await db.commit()

    stmt = filter_runs(select(Run), db, browser_profile="work")
    assert await _ids(db, stmt) == {"r-good"}
    stmt = filter_runs(select(Run), db, capability="browser_open")
    assert await _ids(db, stmt) == {"r-bad", "r-good"}


async def test_schedule_channel_artifact_and_manifest_profile_filters(db):
    _run(db, "r-sched", session_id="s1")
    _run(db, "r-plain", session_id="s2")
    db.add(Session(id="s1", contact_id="c", agent_id="a", channel="telegram"))
    db.add(Session(id="s2", contact_id="c", agent_id="a", channel="web"))
    db.add(
        ScheduleOccurrence(
            id="occ-1",
            schedule_id="sched-9",
            revision_id="rev-1",
            run_id="r-sched",
            scheduled_for=datetime(2024, 1, 1),
        )
    )
    db.add(Artifact(id="art-1", workspace_id="w", current_path="a.docx", format="docx"))
    db.add(
        ArtifactRevision(
            id="rev-1x",
            artifact_id="art-1",
            revision_number=1,
            content_hash="h",
            storage_path="p",
            byte_size=1,
            source_run_id="r-sched",
        )
    )
    db.add(ExecutionManifest(id="em-1", run_id="r-sched", browser_profile_id="prof-7"))
    _audit(db, "a-obs", "r-plain", "browser_open", args=json.dumps({"profile": "prof-7"}))
    await db.commit()

    assert await _ids(db, filter_runs(select(Run), db, schedule_id="sched-9")) == {"r-sched"}
    assert await _ids(db, filter_runs(select(Run), db, channel="telegram")) == {"r-sched"}
    assert await _ids(db, filter_runs(select(Run), db, artifact_format="docx")) == {"r-sched"}
    # browser_profile matches EITHER manifest pin or browser_open args.
    assert await _ids(db, filter_runs(select(Run), db, browser_profile="prof-7")) == {
        "r-sched",
        "r-plain",
    }
    assert await _ids(
        db, filter_runs(select(Run), db, capability="browser_open", tool_status="complete")
    ) == {"r-plain"}
