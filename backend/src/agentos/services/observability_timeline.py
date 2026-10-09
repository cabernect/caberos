"""Run timeline projector — stage-3 observability (W10).

Assembles a single chronological event list for ``GET /api/runs/{id}``
from the durable rows a run leaves behind. Nothing is re-derived from
spool files, browser profile storage, or heuristics — every event traces
to an exact row.

Correlation rules:
- Tool events are the roots. A call's root exists when an audit row, a
  persisted ``tool_call`` message, or a pending approval carries its
  ``call_id`` — in that precedence order.
- Child events (approvals, elicitations, terminal sessions, citations,
  artifact revisions, capability loads, retrieval) link to a root only
  through the exact ``(sub_agent_id, call_id)`` pair — never by
  timestamp. Multiple roots sharing the pair make the join ambiguous and
  the child stays rootless (``parent_id=None``); legacy NULL call_id rows
  never get an invented join.
- ``at=None`` stays null (never fabricate observed time); those events
  order at run.started_at and carry ``estimated_time=True``.
- Transitions get their own events: an approval row yields a pending
  event at created_at plus an ``approval_decision`` at decided_at;
  terminal rows yield start/completion events at their actual times.
  A row's mutable status is a snapshot, not invented history.
"""

import json
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.approval import ApprovalRequest
from ..models.artifact import Artifact, ArtifactRevision
from ..models.audit import AuditRecord
from ..models.elicitation import ElicitationRequest
from ..models.execution_manifest import ExecutionManifest
from ..models.model_call import ModelCall
from ..models.notification import Notification, NotificationDelivery
from ..models.run import Message, Run
from ..models.schedule import ScheduleOccurrence
from ..models.source import RunSource
from ..models.terminal import TerminalSession
from ..redaction import (
    SUMMARY_BUDGET,
    bound_payload,
    project_args,
    project_result,
    redact_secrets,
    redact_text,
)
from .tool_status import tool_event_status

_TERMINAL_RUN_STATUSES = {"completed", "failed", "stopped", "interrupted", "limit_exceeded"}

# Sort priority within a timestamp — parents (tool roots) always sort
# before their children at the same `at`.
_TYPE_ORDER = {
    "run_started": 0,
    "manifest": 5,
    "model_call": 10,
    "tool_call": 20,
    "capability_load": 25,
    "retrieval": 28,
    "approval": 30,
    "elicitation": 35,
    "terminal": 40,
    "browser_evidence": 45,
    "citation": 50,
    "artifact_revision": 55,
    "schedule_occurrence": 60,
    "approval_decision": 65,
    "elicitation_decision": 66,
    "terminal_completed": 67,
    "notification": 70,
    "notification_delivery": 75,
    "run_completed": 90,
}


def _safe_text(value, max_chars=500):
    if value is None:
        return None
    return redact_text(str(value), max_chars)[0]


def _event(
    event_id,
    event_type,
    *,
    at=None,
    call_id=None,
    sub_agent_id=None,
    parent_id=None,
    status=None,
    data=None,
    redacted=False,
    truncated=False,
    budget=SUMMARY_BUDGET,
):
    """Central final pass — every data field goes through the structural
    sanitizer so no projector slip can leak raw content."""
    bounded, scrub_red, scrub_trunc = bound_payload(data or {}, budget=budget)
    return {
        "id": str(event_id),
        "type": event_type,
        "at": at,
        "call_id": call_id,
        "sub_agent_id": sub_agent_id,
        "parent_id": parent_id,
        "status": status,
        "data": bounded,
        "redacted": bool(redacted or scrub_red),
        "truncated": bool(truncated or scrub_trunc),
        "estimated_time": at is None,
    }


def _tool_root_id(sub_agent_id, call_id):
    return f"tool:{sub_agent_id or '-'}:{call_id}"


def _project_tool_payload(capability_name, args_raw, result_raw, denied_reason):
    args, args_red, args_trunc = project_args(capability_name, args_raw)
    result, res_red, res_trunc = project_result(capability_name, result_raw)
    data = {"capability": capability_name, "args": args, "result": result}
    if denied_reason:
        data["denied_reason"] = _safe_text(denied_reason, 500)
    return data, bool(args_red or res_red), bool(args_trunc or res_trunc)


def _tool_data_from_audit(audit):
    args_raw = audit.args
    try:
        args_raw = json.loads(audit.args) if audit.args else None
    except (ValueError, TypeError):
        pass  # hand the raw string to the projector — it fails closed
    result_raw = audit.result
    try:
        result_raw = json.loads(audit.result) if audit.result else None
    except (ValueError, TypeError):
        pass
    data, redacted, truncated = _project_tool_payload(
        audit.capability_name, args_raw, result_raw, audit.denied_reason
    )
    data["audit_id"] = audit.id
    data["effects"] = audit.effects
    data["latency_ms"] = audit.latency_ms
    return data, redacted, truncated


async def build_run_timeline(db: AsyncSession, run: Run) -> list[dict]:
    run_id = run.id

    audits = (
        (await db.execute(select(AuditRecord).where(AuditRecord.run_id == run_id))).scalars().all()
    )
    calls = (await db.execute(select(ModelCall).where(ModelCall.run_id == run_id))).scalars().all()
    messages = (
        (await db.execute(select(Message).where(Message.run_id == run_id).order_by(Message.seq)))
        .scalars()
        .all()
    )
    approvals = (
        (await db.execute(select(ApprovalRequest).where(ApprovalRequest.run_id == run_id)))
        .scalars()
        .all()
    )
    elicitations = (
        (await db.execute(select(ElicitationRequest).where(ElicitationRequest.run_id == run_id)))
        .scalars()
        .all()
    )
    terminals = (
        (await db.execute(select(TerminalSession).where(TerminalSession.run_id == run_id)))
        .scalars()
        .all()
    )
    sources = (
        (await db.execute(select(RunSource).where(RunSource.run_id == run_id))).scalars().all()
    )
    revisions = (
        await db.execute(
            select(ArtifactRevision, Artifact)
            .join(Artifact, ArtifactRevision.artifact_id == Artifact.id)
            .where(ArtifactRevision.source_run_id == run_id)
        )
    ).all()
    occurrences = (
        (await db.execute(select(ScheduleOccurrence).where(ScheduleOccurrence.run_id == run_id)))
        .scalars()
        .all()
    )
    manifest = (
        await db.execute(select(ExecutionManifest).where(ExecutionManifest.run_id == run_id))
    ).scalar_one_or_none()
    approval_ids = [a.id for a in approvals]
    elicitation_ids = [e.id for e in elicitations]
    notification_filter = [(Notification.entity_type == "run") & (Notification.entity_id == run_id)]
    if approval_ids:
        notification_filter.append(
            (Notification.entity_type == "approval") & Notification.entity_id.in_(approval_ids)
        )
    if elicitation_ids:
        notification_filter.append(
            (Notification.entity_type == "elicitation")
            & Notification.entity_id.in_(elicitation_ids)
        )
    notifications = (
        (await db.execute(select(Notification).where(or_(*notification_filter)))).scalars().all()
    )
    deliveries = []
    if notifications:
        deliveries = (
            (
                await db.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id.in_([n.id for n in notifications])
                    )
                )
            )
            .scalars()
            .all()
        )

    events: list[dict] = []

    events.append(
        _event(
            f"{run_id}:started",
            "run_started",
            at=run.started_at,
            status="running",
            data={"agent_id": run.agent_id, "trigger": run.trigger},
        )
    )

    if manifest is not None:
        skill_pins = _safe_json_map(manifest.skill_revision_ids)
        knowledge_ids = _safe_json_list(manifest.knowledge_snapshot_ids)
        artifact_bases = _safe_json_list(manifest.artifact_base_revision_ids)
        events.append(
            _event(
                f"manifest:{manifest.id}",
                "manifest",
                at=run.started_at,
                data={
                    "agent_version_id": manifest.agent_version_id,
                    "agent_version_number": manifest.agent_version_number,
                    "model_provider_id": manifest.model_provider_id,
                    "model_name": _safe_text(manifest.model_name, 255),
                    "plan_revision_id": manifest.plan_revision_id,
                    "schedule_revision_id": manifest.schedule_revision_id,
                    "skill_revision_ids": skill_pins,
                    "retrieval_profile_revision_id": manifest.retrieval_profile_revision_id,
                    "knowledge_snapshot_ids": knowledge_ids,
                    "browser_profile_id": manifest.browser_profile_id,
                    "artifact_base_revision_ids": artifact_bases,
                },
            )
        )

    for m in calls:
        error = _safe_text(m.error) if m.error else None
        detail = m.detail if isinstance(m.detail, dict) else None
        events.append(
            _event(
                f"model_call:{m.id}",
                "model_call",
                at=m.created_at,
                call_id=None,
                sub_agent_id=m.sub_agent_id,
                status=m.status,
                data={
                    "provider_id": m.provider_id,
                    "model_name": _safe_text(m.model_name, 255),
                    "model_str": _safe_text(m.model_str, 255),
                    "kind": m.kind,
                    "purpose": m.purpose,
                    "streamed": m.streamed,
                    "tokens_in": m.tokens_in,
                    "tokens_out": m.tokens_out,
                    "cached_tokens": m.cached_tokens,
                    "thinking_tokens": m.thinking_tokens,
                    "cost": m.cost,
                    "latency_ms": m.latency_ms,
                    "error": error,
                    "detail": {
                        k: detail.get(k)
                        for k in (
                            "resource_id",
                            "generation_id",
                            "operation",
                            "chunk_count",
                            "cost_source",
                        )
                        if k in detail
                    }
                    if detail
                    else None,
                },
                redacted=bool(m.error and error != m.error),
            )
        )

    # --- Tool roots ---
    # (sub_agent_id, call_id) → ordered list of root event ids. Children
    # attach only when the pair resolves to exactly one root.
    roots: dict[tuple[str | None, str], list[str]] = {}

    def _register_root(sub_agent_id, call_id, root_id):
        if call_id is None:
            return
        roots.setdefault((sub_agent_id, call_id), []).append(root_id)

    audited_pairs: set[tuple[str | None, str]] = set()
    for a in audits:
        data, redacted, truncated = _tool_data_from_audit(a)
        status = tool_event_status(a.outcome)
        if a.call_id:
            pair = (a.sub_agent_id, a.call_id)
            base_id = _tool_root_id(a.sub_agent_id, a.call_id)
            root_id = base_id if pair not in audited_pairs else f"{base_id}#{a.id}"
            audited_pairs.add(pair)
            _register_root(a.sub_agent_id, a.call_id, root_id)
        else:
            root_id = f"tool:{a.id}"
        is_doc_search = a.capability_name == "doc_search"
        events.append(
            _event(
                root_id,
                "tool_call",
                at=a.created_at,
                call_id=a.call_id,
                sub_agent_id=a.sub_agent_id,
                status=status,
                data=data,
                redacted=redacted,
                truncated=truncated,
                budget=7000 if is_doc_search else SUMMARY_BUDGET,
            )
        )
        if a.capability_name == "capabilities_load":
            names = []
            try:
                parsed_args = json.loads(a.args) if a.args else None
                if isinstance(parsed_args, dict):
                    names = parsed_args.get("names") or []
            except (ValueError, TypeError):
                names = []
            events.append(
                _event(
                    f"capload:{a.id}",
                    "capability_load",
                    at=a.created_at,
                    call_id=a.call_id,
                    sub_agent_id=a.sub_agent_id,
                    parent_id=root_id,
                    status=status,
                    data={"capabilities": [str(n)[:100] for n in names][:50]},
                )
            )
        if a.capability_name == "doc_search":
            # Per-call retrieval event — every search, even repeated chunk
            # hits (the RunSource row is first-citation only).
            result_data = data.get("result") if isinstance(data.get("result"), dict) else {}
            events.append(
                _event(
                    f"retrieval:{a.id}",
                    "retrieval",
                    at=a.created_at,
                    call_id=a.call_id,
                    sub_agent_id=a.sub_agent_id,
                    parent_id=root_id,
                    status=status,
                    data={
                        "query": (data.get("args") or {}).get("query")
                        if isinstance(data.get("args"), dict)
                        else None,
                        "trace": result_data.get("trace"),
                        "count": result_data.get("count"),
                        "results": result_data.get("results"),
                    },
                    redacted=redacted,
                    truncated=truncated,
                    budget=7000,
                )
            )
        if a.capability_name.startswith("browser_"):
            # Browser evidence — safe action + sanitized url + workspace
            # evidence refs only.
            args_data = data.get("args") if isinstance(data.get("args"), dict) else {}
            result_data = data.get("result") if isinstance(data.get("result"), dict) else {}
            events.append(
                _event(
                    f"browser:{a.id}",
                    "browser_evidence",
                    at=a.created_at,
                    call_id=a.call_id,
                    sub_agent_id=a.sub_agent_id,
                    parent_id=root_id,
                    status=status,
                    data={
                        "action": args_data.get("action"),
                        "url": args_data.get("url"),
                        "mode": args_data.get("mode"),
                        "profile": args_data.get("profile"),
                        "result": result_data,
                    },
                    redacted=True,
                )
            )

    # Tombstone roots: a persisted tool_call message with no audit row.
    audited_keys = {(a.sub_agent_id, a.call_id) for a in audits if a.call_id}
    seen_message_keys: set[tuple[str | None, str]] = set()
    for msg in messages:
        if msg.role != "tool_call":
            continue
        try:
            payload = json.loads(msg.content)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        tc_id = payload.get("id")
        if not isinstance(tc_id, str) or not tc_id:
            continue
        sub = msg.subagent_id
        key = (sub, tc_id)
        if key in audited_keys or key in seen_message_keys:
            continue
        seen_message_keys.add(key)
        data, redacted, truncated = _project_tool_payload(
            str(payload.get("capability", "")),
            payload.get("args"),
            payload.get("result"),
            None,
        )
        root_id = _tool_root_id(sub, tc_id)
        _register_root(sub, tc_id, root_id)
        events.append(
            _event(
                root_id,
                "tool_call",
                at=msg.created_at,
                call_id=tc_id,
                sub_agent_id=sub,
                status=payload.get("status") if isinstance(payload.get("status"), str) else None,
                data=data,
                redacted=redacted,
                truncated=truncated,
            )
        )

    # Pending approvals with neither audit nor message — the tool root is
    # the approval itself (the call is still parked).
    for ap in approvals:
        if not ap.call_id or (ap.sub_agent_id, ap.call_id) in roots:
            continue
        if ap.status != "pending":
            continue
        root_id = _tool_root_id(ap.sub_agent_id, ap.call_id)
        _register_root(ap.sub_agent_id, ap.call_id, root_id)
        args = None
        try:
            parsed = json.loads(ap.args) if ap.args else None
            args = parsed if isinstance(parsed, dict) else ap.args
        except (ValueError, TypeError):
            args = ap.args
        projected, redacted, _truncated = project_args(ap.capability_name, args)
        events.append(
            _event(
                root_id,
                "tool_call",
                at=ap.created_at,
                call_id=ap.call_id,
                sub_agent_id=ap.sub_agent_id,
                status="pending_approval",
                data={"capability": ap.capability_name, "args": projected},
                redacted=redacted,
            )
        )

    def _root(sub_agent_id, call_id):
        if not call_id:
            return None
        candidates = roots.get((sub_agent_id, call_id))
        return candidates[0] if candidates and len(candidates) == 1 else None

    # --- Domain children ---
    for ap in approvals:
        args = None
        try:
            parsed = json.loads(ap.args) if ap.args else None
            args = parsed if isinstance(parsed, dict) else ap.args
        except (ValueError, TypeError):
            args = ap.args
        projected, redacted, _truncated = project_args(ap.capability_name, args)
        events.append(
            _event(
                f"approval:{ap.id}",
                "approval",
                at=ap.created_at,
                call_id=ap.call_id,
                sub_agent_id=ap.sub_agent_id,
                parent_id=_root(ap.sub_agent_id, ap.call_id),
                status="pending",
                data={
                    "capability": ap.capability_name,
                    "args": projected,
                },
                redacted=redacted,
            )
        )
        if ap.decided_at is not None:
            events.append(
                _event(
                    f"approval_decision:{ap.id}",
                    "approval_decision",
                    at=ap.decided_at,
                    call_id=ap.call_id,
                    sub_agent_id=ap.sub_agent_id,
                    parent_id=f"approval:{ap.id}",
                    status=ap.status,
                    data={
                        "capability": ap.capability_name,
                        "decided_by": ap.decided_by,
                    },
                )
            )

    for el in elicitations:
        options = None
        try:
            parsed = json.loads(el.options) if el.options else None
            if isinstance(parsed, list):
                options = [
                    {
                        "label": _safe_text(o.get("label"), 200)
                        if isinstance(o, dict)
                        else _safe_text(o, 200),
                        "description": _safe_text(o.get("description"), 200)
                        if isinstance(o, dict)
                        else None,
                    }
                    for o in parsed[:10]
                ]
        except (ValueError, TypeError):
            options = None
        events.append(
            _event(
                f"elicitation:{el.id}",
                "elicitation",
                at=el.created_at,
                call_id=el.call_id,
                sub_agent_id=el.sub_agent_id,
                parent_id=_root(el.sub_agent_id, el.call_id),
                status="pending",
                data={
                    "question": _safe_text(el.question, 500),
                    "options": options,
                    # The user's raw response never leaves the request row.
                },
                redacted=True,
            )
        )
        if el.responded_at is not None:
            events.append(
                _event(
                    f"elicitation_decision:{el.id}",
                    "elicitation_decision",
                    at=el.responded_at,
                    call_id=el.call_id,
                    sub_agent_id=el.sub_agent_id,
                    parent_id=f"elicitation:{el.id}",
                    status=el.status,
                    data={"responded_by": el.responded_by},
                )
            )

    for t in terminals:
        command, cmd_red, cmd_trunc = redact_text(t.command, 500)
        events.append(
            _event(
                f"terminal:{t.id}",
                "terminal",
                at=t.started_at,
                call_id=t.call_id,
                sub_agent_id=t.sub_agent_id,
                parent_id=_root(t.sub_agent_id, t.call_id),
                status="running",
                data={
                    "terminal_id": t.id,
                    "command": command,
                    "stdout_bytes": t.stdout_bytes,
                    "stderr_bytes": t.stderr_bytes,
                    "truncated": t.truncated,
                },
                redacted=cmd_red,
                truncated=cmd_trunc or bool(t.truncated),
            )
        )
        if t.completed_at is not None:
            events.append(
                _event(
                    f"terminal:{t.id}:end",
                    "terminal_completed",
                    at=t.completed_at,
                    call_id=t.call_id,
                    sub_agent_id=t.sub_agent_id,
                    parent_id=f"terminal:{t.id}",
                    status=t.status,
                    data={
                        "terminal_id": t.id,
                        "exit_code": t.exit_code,
                        "stdout_bytes": t.stdout_bytes,
                        "stderr_bytes": t.stderr_bytes,
                        "truncated": t.truncated,
                    },
                    truncated=bool(t.truncated),
                )
            )

    for s_ in sources:
        excerpt, red, trunc = redact_text(s_.excerpt, 500)
        try:
            headings = json.loads(s_.heading_path) if s_.heading_path else []
            if not isinstance(headings, list):
                headings = []
        except (ValueError, TypeError):
            headings = []
        events.append(
            _event(
                f"citation:{s_.id}",
                "citation",
                at=None,
                call_id=s_.call_id,
                sub_agent_id=s_.sub_agent_id,
                parent_id=_root(s_.sub_agent_id, s_.call_id),
                data={
                    "chunk_id": s_.chunk_id,
                    "document_id": s_.document_id,
                    "source_path": _safe_text(s_.source_path, 300),
                    "heading_path": [_safe_text(h, 100) for h in headings[:10] if h is not None],
                    "page_number": s_.page_number,
                    "sheet_name": _safe_text(s_.sheet_name, 100),
                    "excerpt": excerpt,
                    "rank": s_.rank,
                },
                redacted=red,
                truncated=trunc,
            )
        )

    for rev, artifact in revisions:
        events.append(
            _event(
                f"artifact:{rev.id}",
                "artifact_revision",
                at=getattr(rev, "created_at", None),
                call_id=rev.call_id,
                sub_agent_id=rev.sub_agent_id,
                parent_id=_root(rev.sub_agent_id, rev.call_id),
                data={
                    "artifact_id": artifact.id,
                    "revision_id": rev.id,
                    "revision_number": rev.revision_number,
                    "path": artifact.current_path,
                    "format": artifact.format,
                    "byte_size": rev.byte_size,
                    "content_hash": rev.content_hash,
                    "summary": _safe_text(rev.change_summary, 200) if rev.change_summary else None,
                },
            )
        )

    for oc in occurrences:
        events.append(
            _event(
                f"schedule:{oc.id}",
                "schedule_occurrence",
                at=oc.created_at,
                status=oc.status,
                data={
                    "schedule_id": oc.schedule_id,
                    "revision_id": oc.revision_id,
                    "scheduled_for": oc.scheduled_for,
                    "attempt": oc.attempt,
                    "error": _safe_text(oc.error) if oc.error else None,
                },
            )
        )

    for n in notifications:
        message, red, trunc = redact_text(n.message, 500)
        events.append(
            _event(
                f"notification:{n.id}",
                "notification",
                at=n.created_at,
                status=n.severity,
                data={
                    "notification_type": n.notification_type,
                    "title": _safe_text(n.title, 255),
                    "severity": n.severity,
                    "message": message,
                    "agent_id": n.agent_id,
                    "agent_name": _safe_text(n.agent_name, 255),
                },
                redacted=red,
                truncated=trunc,
            )
        )
    for d in deliveries:
        events.append(
            _event(
                f"delivery:{d.id}",
                "notification_delivery",
                at=d.created_at,
                parent_id=f"notification:{d.notification_id}",
                status=d.state,
                data={
                    "notification_id": d.notification_id,
                    "adapter": d.adapter,
                    "attempts": d.attempts,
                    "error": _safe_text(d.error, 500) if d.error else None,
                },
            )
        )

    if run.completed_at is not None and run.status in _TERMINAL_RUN_STATUSES:
        events.append(
            _event(
                f"{run_id}:ended",
                "run_completed",
                at=run.completed_at,
                status=run.status,
                data={
                    "status": run.status,
                    "error": _safe_text(run.error, 500) if run.error else None,
                },
            )
        )

    def _sort_key(ev):
        at = ev["at"]
        if at is None:
            at = run.started_at
        if isinstance(at, datetime) and at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        return (at, _TYPE_ORDER.get(ev["type"], 80), ev["id"])

    events.sort(key=_sort_key)
    return events


def _safe_json_list(raw) -> list | None:
    try:
        parsed = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    return [redact_secrets(str(v))[0][:255] for v in parsed[:50]]


def _safe_json_map(raw) -> dict | None:
    try:
        parsed = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        redact_secrets(str(k))[0][:255]: redact_secrets(str(v))[0][:255]
        for k, v in list(parsed.items())[:50]
        if isinstance(v, str)
    }
