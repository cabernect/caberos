"""W10 stage 3 — run timeline projection + read-boundary redaction.

Covers ordering, exact parent links, estimated_time for legacy rows, and
that no canary secret can leak through any projected field — including
the legacy flat lists (audit args/result, tool_call messages).
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from agentos.models.approval import ApprovalRequest
from agentos.models.artifact import Artifact, ArtifactRevision
from agentos.models.audit import AuditRecord
from agentos.models.elicitation import ElicitationRequest
from agentos.models.model_call import ModelCall
from agentos.models.notification import Notification, NotificationDelivery
from agentos.models.run import Message, Run
from agentos.models.schedule import ScheduleOccurrence
from agentos.models.source import RunSource
from agentos.models.terminal import TerminalSession
from agentos.services.observability_timeline import build_run_timeline

CANARY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ"


@pytest.fixture
async def timeline_run(db):
    run = Run(
        id="r-tl",
        session_id="s",
        contact_id="c",
        agent_id="a",
        status="completed",
        started_at=datetime(2024, 1, 1, tzinfo=UTC),
        completed_at=datetime(2024, 1, 1, 0, 1, tzinfo=UTC),
        error=None,
    )
    db.add(run)

    # Audit row for call c-term — contains a secret canary in args/result.
    db.add(
        AuditRecord(
            id="au-term",
            run_id="r-tl",
            agent_id="a",
            call_id="c-term",
            capability_name="terminal",
            allowed=True,
            outcome="ok",
            args=json.dumps({"command": f"echo {CANARY} > out.txt", "cwd": "/w"}),
            result=json.dumps(
                {
                    "stdout": CANARY,
                    "stderr": "",
                    "exit_code": 0,
                    "stdout_bytes": 60,
                    "cookies": {"session": "abc"},
                }
            ),
            created_at=datetime(2024, 1, 1, 0, 0, 10, tzinfo=UTC),
        )
    )
    # Legacy audit row — no created_at, no call_id. A Core insert is used
    # because the ORM's Python-side default fires for explicit None.
    await db.execute(
        AuditRecord.__table__.insert().values(
            id="au-legacy",
            run_id="r-tl",
            agent_id="a",
            call_id=None,
            capability_name="read_file",
            allowed=True,
            outcome="ok",
            args=json.dumps({"path": "notes.md"}),
            result=json.dumps({"content": CANARY, "path": "notes.md"}),
            created_at=None,
        )
    )
    # Denied browser call carrying creds in the URL.
    db.add(
        AuditRecord(
            id="au-browser",
            run_id="r-tl",
            agent_id="a",
            call_id="c-nav",
            sub_agent_id="sub-1",
            capability_name="browser_navigate",
            allowed=False,
            outcome="denied",
            denied_reason="policy",
            args=json.dumps(
                {
                    "action": "navigate",
                    "url": f"https://user:{CANARY}@example.com/path?token={CANARY}#frag",
                    "cookies": "x",
                }
            ),
            result=json.dumps({"observation": CANARY, "screenshot": "s.png"}),
            created_at=datetime(2024, 1, 1, 0, 0, 20, tzinfo=UTC),
        )
    )
    # Terminal session + approval + elicitation all linked to c-term.
    db.add(
        TerminalSession(
            id="ts-1",
            agent_id="a",
            run_id="r-tl",
            call_id="c-term",
            workspace_path="/w",
            command=f"echo {CANARY}",
            status="completed",
            exit_code=0,
            started_at=datetime(2024, 1, 1, 0, 0, 11, tzinfo=UTC),
            completed_at=datetime(2024, 1, 1, 0, 0, 12, tzinfo=UTC),
        )
    )
    db.add(
        ApprovalRequest(
            id="ap-1",
            run_id="r-tl",
            call_id="c-term",
            capability_name="terminal",
            args=json.dumps({"command": "ls"}),
            status="approved",
            created_at=datetime(2024, 1, 1, 0, 0, 9, tzinfo=UTC),
        )
    )
    db.add(
        ElicitationRequest(
            id="el-1",
            run_id="r-tl",
            call_id="c-ask",
            question="pick one",
            options=json.dumps([{"label": "a", "description": ""}]),
            status="answered",
            response="the raw answer " + CANARY,
            created_at=datetime(2024, 1, 1, 0, 0, 30, tzinfo=UTC),
        )
    )
    # c-ask has NO audit row — pending-less orphan stays rootless.
    db.add(
        RunSource(
            id="rs-1",
            run_id="r-tl",
            call_id="c-term",
            chunk_id="ch-1",
            document_id="doc-1",
            source_path="notes.md",
            storage_path="vault/notes.md",
            heading_path="[]",
            excerpt="private doc text " + CANARY,
            rank=0.9,
        )
    )
    db.add(Artifact(id="art-1", workspace_id="a", current_path="out.docx", format="docx"))
    db.add(
        ArtifactRevision(
            id="rev-1",
            artifact_id="art-1",
            revision_number=1,
            content_hash="h" * 8,
            storage_path="art-1/rev1.docx",
            byte_size=42,
            source_run_id="r-tl",
            call_id="c-term",
        )
    )
    db.add(
        ModelCall(
            id="mc-1",
            run_id="r-tl",
            agent_id="a",
            turn=1,
            provider_id="p1",
            model_name="m1",
            model_str="openai/m1",
            tokens_in=10,
            tokens_out=5,
            thinking_tokens=3,
            cost=0.01,
            latency_ms=100,
            status="ok",
            created_at=datetime.now(UTC),
        )
    )
    db.add(
        ScheduleOccurrence(
            id="occ-1",
            schedule_id="sched-1",
            revision_id="rev-x",
            run_id="r-tl",
            scheduled_for=datetime(2024, 1, 1, tzinfo=UTC),
            status="completed",
        )
    )
    db.add(
        Notification(
            id="n-1",
            notification_type="run_completed",
            severity="info",
            title="Run done",
            message=f"finished; key={CANARY}",
            entity_type="run",
            entity_id="r-tl",
        )
    )
    db.add(
        Notification(
            id="n-2",
            notification_type="approval_required",
            severity="warning",
            title="Approval",
            message="terminal needs approval",
            entity_type="approval",
            entity_id="ap-1",
        )
    )
    db.add(
        NotificationDelivery(id="d-1", notification_id="n-1", adapter="toast", state="delivered")
    )
    # Tombstone tool_call message — call never reached the audit ledger (B42).
    db.add(
        Message(
            id="msg-tc",
            run_id="r-tl",
            role="tool_call",
            seq=5,
            content=json.dumps(
                {
                    "id": "c-tombstone",
                    "capability": "terminal",
                    "args": {"command": f"rm {CANARY}"},
                    "status": "interrupted",
                    "result": None,
                }
            ),
            created_at=datetime(2024, 1, 1, 0, 0, 40, tzinfo=UTC),
        )
    )
    db.add(
        Message(
            id="msg-u",
            run_id="r-tl",
            role="user",
            seq=0,
            content=f"please run key={CANARY}",
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
    )
    await db.commit()
    return run


async def test_timeline_shape_order_and_parents(db, timeline_run):
    events = await build_run_timeline(db, timeline_run)
    by_id = {e["id"]: e for e in events}

    assert by_id["r-tl:started"]["type"] == "run_started"
    assert by_id["r-tl:ended"]["type"] == "run_completed"
    assert by_id["model_call:mc-1"]["data"]["thinking_tokens"] == 3

    # Roots from audit rows — deterministic scoped ids.
    assert by_id["tool:-:c-term"]["status"] == "complete"
    assert by_id["tool:sub-1:c-nav"]["status"] == "denied"
    # Tombstone message becomes the root when no audit exists.
    assert by_id["tool:-:c-tombstone"]["status"] == "interrupted"
    # Legacy audit (null call_id) roots by its own row id, no invented join.
    assert by_id["tool:au-legacy"]["parent_id"] is None
    assert by_id["tool:au-legacy"]["estimated_time"] is True
    assert by_id["tool:au-legacy"]["at"] is None

    # Domain children link through the exact (subagent, call_id) pair.
    assert by_id["approval:ap-1"]["parent_id"] == "tool:-:c-term"
    assert by_id["terminal:ts-1"]["parent_id"] == "tool:-:c-term"
    assert by_id["citation:rs-1"]["parent_id"] == "tool:-:c-term"
    assert by_id["artifact:rev-1"]["parent_id"] == "tool:-:c-term"
    # el-1's call (c-ask) has no audit/message root → parent stays null.
    assert by_id["elicitation:el-1"]["parent_id"] is None

    # Notifications + deliveries link exactly.
    assert "notification:n-1" in by_id
    assert "notification:n-2" in by_id  # via approval entity link
    assert by_id["delivery:d-1"]["parent_id"] == "notification:n-1"

    # Ordering is stable: nondecreasing sort key.
    keys = [
        (
            (e["at"] or timeline_run.started_at),
            e["id"],
        )
        for e in events
    ]
    assert all(
        keys[i][0] <= keys[i + 1][0] or keys[i][0] == keys[i + 1][0] for i in range(len(keys) - 1)
    )


async def test_timeline_redaction_no_canary_anywhere(db, timeline_run):
    events = await build_run_timeline(db, timeline_run)
    blob = json.dumps(events, default=str)
    assert CANARY not in blob
    # Browser args: only action/mode/profile/url survive; url stripped of
    # userinfo/query/fragment.
    nav = {e["id"]: e for e in events}["tool:sub-1:c-nav"]
    assert nav["data"]["args"]["url"] == "https://example.com/path"
    assert "cookies" not in nav["data"]["args"]
    # Browser result keeps only evidence-ish keys, no observation body.
    assert nav["data"]["result"]["screenshot"] == "s.png"
    assert "observation" not in nav["data"]["result"]
    # Terminal result has no stdout/stderr.
    term = {e["id"]: e for e in events}["tool:-:c-term"]
    assert "stdout" not in term["data"]["result"]
    assert term["data"]["result"]["exit_code"] == 0
    assert term["data"]["args"]["command"] == "echo [REDACTED] > out.txt"
    # Elicitation exposes the question, never the raw response.
    el = {e["id"]: e for e in events}["elicitation:el-1"]
    assert el["data"]["question"] == "pick one"
    assert "response" not in el["data"]
    # Sensitive reader results are metadata only.
    legacy = {e["id"]: e for e in events}["tool:au-legacy"]
    assert legacy["data"]["result"].get("path") == "notes.md"
    assert "content" not in legacy["data"]["result"]


# --- API-level: the flat legacy lists carry the same protections ---


@pytest.fixture
def client(db_engine):
    from agentos.auth import require_operator
    from agentos.main import app

    async def mock_auth():
        return {"id": "op-1", "username": "admin"}

    app.dependency_overrides[require_operator] = mock_auth
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def db_session(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def get_test_db():
        async with factory() as session:
            yield session

    from agentos.db import get_db
    from agentos.main import app

    app.dependency_overrides[get_db] = get_test_db
    yield factory
    app.dependency_overrides.pop(get_db, None)


async def _seed_api_run(factory, timeline_run):
    # timeline_run fixture already committed rows on `db` — API tests use
    # their own session on the same engine, so the rows are visible.
    return timeline_run


async def test_run_detail_timeline_and_flat_lists_redacted(client, db_session, db, timeline_run):
    resp = client.get("/api/runs/r-tl")
    assert resp.status_code == 200
    body = resp.json()
    blob = json.dumps(body)
    assert CANARY not in blob, "canary leaked somewhere in run detail"
    assert body["timeline"]
    assert {e["type"] for e in body["timeline"]} >= {
        "run_started",
        "model_call",
        "tool_call",
        "terminal",
        "approval",
        "citation",
        "artifact_revision",
        "notification",
    }
    # Flat audit list: projected args — terminal args allowlist drops cwd.
    term_audit = next(a for a in body["audit_records"] if a["capability_name"] == "terminal")
    assert term_audit["call_id"] == "c-term"
    assert term_audit["created_at"] is not None
    args = json.loads(term_audit["args"])
    assert "cwd" not in args
    # tool_call message JSON is projected, not raw.
    tc_msg = next(m for m in body["messages"] if m["role"] == "tool_call")
    payload = json.loads(tc_msg["content"])
    assert payload["status"] == "interrupted"
    assert CANARY not in payload["args"]["command"]
    # user message regex-redacted, not dropped.
    assert "[REDACTED]" in next(m for m in body["messages"] if m["role"] == "user")["content"]


async def test_runs_filter_params(client, db_session, db, timeline_run):
    resp = client.get("/api/runs?provider_id=p1&model=m1")
    assert resp.status_code == 200
    assert [r["id"] for r in resp.json()] == ["r-tl"]
    resp = client.get("/api/runs?provider_id=p1&model=nope")
    assert resp.json() == []
    # capability + tool_status via audit rows
    resp = client.get("/api/runs?capability=terminal&tool_status=complete")
    assert [r["id"] for r in resp.json()] == ["r-tl"]
    resp = client.get("/api/runs?capability=terminal&tool_status=denied")
    assert resp.json() == []
    # validations
    assert client.get("/api/runs?status=,").status_code == 422
    assert client.get("/api/runs?limit=0").status_code == 422
    assert (
        client.get("/api/runs?since=2024-02-01T00:00:00&until=2024-01-01T00:00:00").status_code
        == 422
    )
    resp = client.get("/api/runs?since=2024-01-01T00:00:00")
    assert resp.status_code == 200 and resp.json()[0]["id"] == "r-tl"


async def test_audit_filters_and_projection(client, db_session, db, timeline_run):
    resp = client.get("/api/audit?run_id=r-tl&call_id=c-term")
    rows = resp.json()
    assert len(rows) == 1 and rows[0]["capability_name"] == "terminal"
    resp = client.get("/api/audit?run_id=r-tl&outcome=denied")
    assert [r["capability_name"] for r in resp.json()] == ["browser_navigate"]
    resp = client.get("/api/audit?run_id=r-tl&since=2024-01-01T00:00:15")
    # Only the browser row is after :15 — legacy NULL created_at excluded.
    assert [r["id"] for r in resp.json()] == ["au-browser"]
    resp = client.get("/api/audit?run_id=r-tl&sub_agent_id=sub-1")
    assert [r["id"] for r in resp.json()] == ["au-browser"]


async def test_spend_scope(client, db_session, db, timeline_run):
    # default unchanged — agent scope keeps the Run-totals shape.
    resp = client.get("/api/spend")
    assert resp.status_code == 200
    assert "by_agent" in resp.json()
    # ledger-only filters rejected for agent scope.
    assert client.get("/api/spend?provider_id=p1").status_code == 422
    # platform scope returns the ledger dict contract.
    resp = client.get("/api/spend?scope=platform&provider_id=p1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "platform"
    assert body["total_calls"] == 1  # mc-1 — test/excluded rows don't leak in
    assert body["thinking_tokens"] == 3
    assert resp.json()["by_model"][0]["model_name"] == "m1"


async def test_browser_navigate_value_url_and_evidence_refs():
    """navigate carries its URL in args.value; evidence must be a
    workspace-relative path — no absolute/URL/traversal."""
    from agentos.redaction import project_args, project_result

    args, _, _ = project_args(
        "browser_navigate",
        {"action": "navigate", "value": f"https://u:{CANARY}@ex.com/p?x=1#f", "typed": "secret"},
    )
    assert args["url"] == "https://ex.com/p"
    assert "typed" not in args and "value" not in args

    result, _, _ = project_result(
        "browser_act",
        {
            "status": "ok",
            "screenshot": "../escape.png",
            "evidence": "evidence/shot-1.png",
            "observation": CANARY,
            "title": "page title",
        },
    )
    assert result == {"status": "ok", "evidence": "evidence/shot-1.png"}


async def test_unbounded_args_structure_truncates_safely():
    """Huge payloads bound inside valid JSON — never a cut string."""
    from agentos.redaction import project_args

    args, _, truncated = project_args(
        "custom_tool",
        {"data": [{"k": "x" * 600} for _ in range(60)], "big": "y" * 5000},
    )
    blob = json.dumps(args)
    assert len(blob) <= 2100
    assert CANARY not in blob
    assert truncated is True


async def test_model_call_detail_named_keys_only(db, timeline_run):
    from agentos.services.observability_timeline import build_run_timeline

    events = await build_run_timeline(db, timeline_run)
    mc = next(e for e in events if e["type"] == "model_call")
    assert set(mc["data"]["detail"] or {}) <= {
        "resource_id",
        "generation_id",
        "operation",
        "chunk_count",
        "cost_source",
    }


# --- round-2 review cases ---


async def test_active_run_has_no_end_event(db):
    """A still-running run must not show a fabricated completion."""
    db.add(
        Run(
            id="r-live",
            session_id="s",
            contact_id="c",
            agent_id="a",
            status="running",
            completed_at=None,
        )
    )
    await db.commit()
    events = await build_run_timeline(db, await db.get(Run, "r-live"))
    assert "run_completed" not in {e["type"] for e in events}
    assert any(e["type"] == "run_started" for e in events)


async def test_failed_run_end_event_carries_real_status(db):
    db.add(
        Run(
            id="r-fail",
            session_id="s",
            contact_id="c",
            agent_id="a",
            status="failed",
            completed_at=datetime.now(UTC),
            error="model exploded",
        )
    )
    await db.commit()
    events = await build_run_timeline(db, await db.get(Run, "r-fail"))
    end = next(e for e in events if e["type"] == "run_completed")
    assert end["status"] == "failed"
    assert end["data"]["error"] == "model exploded"
    assert end["status"] != "completed"


async def test_same_call_id_in_parent_and_subagent_roots(db):
    """Sibling scopes sharing a call_id must produce two distinct roots —
    the tombstone dedup key is (subagent, call)."""
    db.add(Run(id="r-sib", session_id="s", contact_id="c", agent_id="a", status="running"))
    for i, sub in enumerate((None, "sub-9")):
        db.add(
            Message(
                id=f"msg-{i}",
                run_id="r-sib",
                role="tool_call",
                seq=i,
                subagent_id=sub,
                content=json.dumps({"id": "same-call", "capability": "terminal", "status": "ok"}),
                created_at=datetime.now(UTC),
            )
        )
    await db.commit()
    events = await build_run_timeline(db, await db.get(Run, "r-sib"))
    roots = [e for e in events if e["type"] == "tool_call" and e["call_id"] == "same-call"]
    assert {e["sub_agent_id"] for e in roots} == {None, "sub-9"}


async def test_duplicate_audit_same_call_disambiguated(db):
    """Two audits sharing (scope, call_id) get unique event ids; children
    can't pick a unique root → parent stays None."""
    db.add(Run(id="r-dup", session_id="s", contact_id="c", agent_id="a", status="running"))
    for i, audit_id in enumerate(("au-a", "au-b")):
        db.add(
            AuditRecord(
                id=audit_id,
                run_id="r-dup",
                agent_id="a",
                call_id="dup-call",
                capability_name="datetime_now",
                allowed=True,
                outcome="ok",
                args="{}",
                created_at=datetime(2024, 1, 1, i, tzinfo=UTC),
            )
        )
    db.add(
        TerminalSession(
            id="ts-dup",
            agent_id="a",
            run_id="r-dup",
            call_id="dup-call",
            workspace_path="/w",
            command="x",
            status="completed",
            exit_code=0,
            started_at=datetime(2024, 1, 1, 2, tzinfo=UTC),
            completed_at=datetime(2024, 1, 1, 2, tzinfo=UTC),
        )
    )
    await db.commit()
    events = await build_run_timeline(db, await db.get(Run, "r-dup"))
    ids = [e["id"] for e in events if e["type"] == "tool_call"]
    assert len(ids) == len(set(ids)) == 2
    term = next(e for e in events if e["type"] == "terminal")
    assert term["parent_id"] is None  # ambiguous — never a guessed join


async def test_malformed_list_payloads_do_not_500(db):
    db.add(Run(id="r-mal", session_id="s", contact_id="c", agent_id="a", status="running"))
    db.add(
        AuditRecord(
            id="au-mal",
            run_id="r-mal",
            agent_id="a",
            call_id="c-mal",
            capability_name="capabilities_load",
            allowed=True,
            outcome="ok",
            args="[1, 2]",  # valid JSON, wrong shape
            result="[true, false]",
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
    events = await build_run_timeline(db, await db.get(Run, "r-mal"))
    assert {e["type"] for e in events} >= {"tool_call", "capability_load"}
    tool = next(e for e in events if e["type"] == "tool_call")
    # non-dict args are redacted+bounded strings, not crashes
    assert tool["data"]["args"] is not None


async def test_model_call_detail_named_keys_and_types(db):
    """detail keeps exactly the named keys — chunk_count stays numeric,
    nested/secret fields drop entirely."""
    db.add(Run(id="r-det", session_id="s", contact_id="c", agent_id="a", status="running"))
    db.add(
        ModelCall(
            id="mc-det",
            run_id="r-det",
            agent_id="a",
            kind="embedding",
            purpose="embedding",
            provider_id="p",
            model_name="m",
            detail={
                "resource_id": "res-1",
                "generation_id": "gen-1",
                "operation": "ingest",
                "chunk_count": 4,
                "secret_extras": {"leak": CANARY},
            },
        )
    )
    await db.commit()
    events = await build_run_timeline(db, await db.get(Run, "r-det"))
    mc = next(e for e in events if e["type"] == "model_call")
    assert mc["data"]["detail"] == {
        "resource_id": "res-1",
        "generation_id": "gen-1",
        "operation": "ingest",
        "chunk_count": 4,
    }
    assert isinstance(mc["data"]["detail"]["chunk_count"], int)


@pytest.mark.asyncio
async def test_receipt_projection_whitelist_run_detail_and_timeline(
    client, db_session, db, timeline_run
):
    """cost_assessment/rate_authority survive the read projection — but
    only their whitelisted fields; secrets and arbitrary keys never do."""
    canary = CANARY
    db.add(
        ModelCall(
            id="mc-receipt",
            run_id="r-tl",
            agent_id="a",
            turn=2,
            kind="chat",
            purpose="reasoning",
            provider_id="p1",
            model_name="m1",
            model_str="openai/m1",
            tokens_in=1000,
            tokens_out=100,
            cost=0.003,
            latency_ms=50,
            status="ok",
            created_at=datetime.now(UTC),
            detail={
                "operation": "chat",
                "cost_source": "user_rate",
                "evil": canary,
                "api_key": canary,
                "cost_assessment": {
                    "amount": "0.003",
                    "source": "user_rate",
                    "currency": "USD",
                    "reason": None,
                    "snapshot_revision": None,
                    "calculated_at": "2026-10-12T00:00:00Z",
                    "calculation_version": "aggregate-token-rates-v2",
                    "tier": {"type": "context", "size": 200000, "leak": canary},
                    "rates": {"input": 2, "output": 10, "leak": canary},
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 100,
                        "cache_read_tokens": None,
                        "cache_write_tokens": 0,
                        "reasoning_tokens": None,
                        "cache_write_1h_tokens": 0,
                        "audio_input_tokens": 0,
                        "audio_output_tokens": 0,
                        "leak": canary,
                    },
                    "leak": canary,
                },
                "rate_authority": {
                    "provider_id": "p1",
                    "request_model_id": "m1",
                    "config_fingerprint": "fp",
                    "offering_revision": 3,
                    "snapshot_revision": None,
                    "routing_override_unresolved": False,
                    "pricing_authority": {
                        "source": "user_override",
                        "confidence": "user_declared",
                        "as_of": "2026-10-12T00:00:00Z",
                        "leak": canary,
                    },
                    "leak": canary,
                },
            },
        )
    )
    await db.commit()

    resp = client.get("/api/runs/r-tl")
    assert resp.status_code == 200
    body = resp.json()
    blob = json.dumps(body)
    assert canary not in blob, "secret/canary leaked through run detail"

    # Run-detail model_calls: receipt fields projected and intact.
    call = next(c for c in body["model_calls"] if c["id"] == "mc-receipt")
    detail = call["detail"]
    assert detail["operation"] == "chat"
    assert detail["cost_source"] == "user_rate"
    assessment = detail["cost_assessment"]
    assert assessment["amount"] == "0.003"
    assert assessment["source"] == "user_rate"
    assert assessment["calculation_version"] == "aggregate-token-rates-v2"
    assert assessment["rates"] == {"input": "2", "output": "10"}
    assert assessment["usage"]["input_tokens"] == 1000
    assert assessment["usage"]["output_tokens"] == 100
    # Nullable counter stays explicitly null, not dropped.
    assert assessment["usage"]["cache_read_tokens"] is None
    assert "leak" not in assessment
    assert "leak" not in assessment["usage"]
    assert assessment["tier"] == {"type": "context", "size": 200000}
    authority = detail["rate_authority"]
    assert authority["provider_id"] == "p1"
    assert authority["request_model_id"] == "m1"
    assert authority["offering_revision"] == 3
    assert authority["pricing_authority"] == {
        "source": "user_override",
        "confidence": "user_declared",
        "as_of": "2026-10-12T00:00:00Z",
    }
    assert "leak" not in authority

    # Timeline event for the same call uses the same projector.
    event = next(
        e
        for e in body["timeline"]
        if e["type"] == "model_call" and e["id"] == "model_call:mc-receipt"
    )
    ev_detail = event["data"]["detail"]
    # model_call events get the scoped policy: full receipt fields
    # survive — all 8 nullable usage counters and the authority dict.
    assert ev_detail["cost_source"] == "user_rate"
    assert ev_detail["cost_assessment"]["amount"] == "0.003"
    assert ev_detail["cost_assessment"]["rates"]["input"] == "2"
    ev_usage = ev_detail["cost_assessment"]["usage"]
    assert ev_usage["input_tokens"] == 1000
    assert ev_usage["output_tokens"] == 100
    assert ev_usage["cache_read_tokens"] is None
    assert set(ev_usage) == {
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "cache_write_1h_tokens",
        "audio_input_tokens",
        "audio_output_tokens",
    }
    ev_auth = ev_detail["rate_authority"]
    assert ev_auth["provider_id"] == "p1"
    assert ev_auth["request_model_id"] == "m1"
    assert ev_auth["pricing_authority"]["source"] == "user_override"
    assert canary not in json.dumps(ev_detail)


@pytest.mark.asyncio
async def test_receipt_scoped_policy_only_for_model_call_events(db):
    """The widened numeric/metadata allowances apply ONLY to model_call
    events — generic bound_payload keeps dropping secret-named keys."""
    import json as _json

    from agentos.redaction import bound_payload

    detail = {
        "rate_authority": {"provider_id": "p1"},
        "usage": {"input_tokens": 5},
    }
    out, red, _ = bound_payload({"detail": detail})
    # Without the scoped policy: authority + token counters drop.
    assert "rate_authority" not in out["detail"]
    assert out["detail"]["usage"] == {}
    # A non-model_call event that somehow carries the same keys still
    # drops them — the widening is not global.
    from agentos.services.observability_timeline import _event

    other = _event("x", "tool_call", data={"detail": detail})
    assert "rate_authority" not in other["data"]["detail"]

    # Inside an allowed authority dict, secret-named values are still
    # scrubbed by the recursive pass.
    scoped = {
        "detail": {
            "rate_authority": {
                "provider_id": "p1",
                "api_key": CANARY,
                "env": CANARY,
            }
        }
    }
    mc = _event("mc", "model_call", data=scoped)
    blob = _json.dumps(mc["data"])
    assert CANARY not in blob
    assert mc["data"]["detail"]["rate_authority"]["provider_id"] == "p1"


def test_projector_redact_before_truncate_and_rate_validation():
    """A >255-char credential is fully redacted, never prefix-truncated;
    invalid rate scalars project as null, not crashy floats."""
    from agentos.services.accounting_projection import project_call_detail

    long_secret = "sk-proj-" + ("a" * 300)
    detail = {
        "cost_source": long_secret,
        "cost_assessment": {
            "amount": long_secret,
            "reason": "x " + long_secret,
            "rates": {
                "input": float("nan"),
                "output": float("inf"),
                "cache_read": -3,
                "cache_write": True,
                "reasoning": "abc",
            },
        },
        "rate_authority": {
            "provider_id": long_secret,
            "routing_override_unresolved": "false",
        },
    }
    out = project_call_detail(detail)
    blob = json.dumps(out)
    assert long_secret not in blob
    assert "a" * 64 not in blob  # no unredacted prefix survives
    assert "[REDACTED]" in blob or "REDACTED" in blob
    assert out["cost_assessment"]["rates"] == {
        "input": None,
        "output": None,
        "cache_read": None,
        "cache_write": None,
        "reasoning": None,
    }
    assert out["rate_authority"]["routing_override_unresolved"] is None
    # Valid rates serialize exactly as decimal strings.
    good = project_call_detail({"cost_assessment": {"rates": {"input": 2, "output": 10.5}}})
    assert good["cost_assessment"]["rates"] == {"input": "2", "output": "10.5"}


@pytest.mark.asyncio
async def test_receipt_long_secret_redacted_at_both_read_seams(
    client, db_session, db, timeline_run
):
    """The >255-char credential never leaks a prefix through run detail
    or the timeline event."""
    long_secret = "sk-proj-" + ("b" * 300)
    db.add(
        ModelCall(
            id="mc-secret",
            run_id="r-tl",
            agent_id="a",
            turn=3,
            kind="chat",
            provider_id="p1",
            model_name="m1",
            model_str="openai/m1",
            tokens_in=1,
            tokens_out=1,
            cost=0.0,
            latency_ms=1,
            status="ok",
            created_at=datetime.now(UTC),
            detail={
                "operation": "chat",
                "cost_assessment": {
                    "amount": "0.003",
                    "reason": f"billed {long_secret} twice",
                },
                "rate_authority": {
                    "provider_id": long_secret,
                },
            },
        )
    )
    await db.commit()
    resp = client.get("/api/runs/r-tl")
    blob = resp.text
    assert long_secret not in blob
    assert "b" * 64 not in blob  # no unredacted prefix anywhere
    call = next(c for c in resp.json()["model_calls"] if c["id"] == "mc-secret")
    assert "REDACTED" in call["detail"]["cost_assessment"]["reason"]
