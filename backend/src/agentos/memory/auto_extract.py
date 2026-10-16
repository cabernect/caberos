"""Session-close learning: validated persistent MemoryEntries, an optional
curated-core update, then cleanup of snapshotted run scratch.
Only real, persisted parent-level user messages may be
cited as sources; a clarification or conflict blocks the core write and
retains the scratch."""

import hashlib
import json
import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..harness.compaction import count_tokens
from ..harness.memory_prompts import MEMORY_CREDENTIAL_ASSIGNMENT_PATTERN, MEMORY_EXTRACTION_PROMPT
from ..models.memory import MemoryEntry
from ..models.run import Message, Run
from ..models.session import Session
from ..notifications import create_notification
from ..providers import ProviderRegistry
from ..providers.catalog_policy import resolve_input_budget
from ..redaction import redact_text
from ..services import model_ledger
from ..services.context_capture import capture_scope
from . import core as core_mod
from . import recall

TERMINAL_STATUSES = ("completed", "failed", "stopped", "interrupted")


async def auto_extract_memory(
    db: AsyncSession,
    agent_config: Any,
    agent_id: str,
    messages: list[Any],
    run_id: str | None = None,
    contact_id: str | None = None,
    session_id: str | None = None,
    *,
    session_run_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Extract durable learnings from the supplied parent-message snapshot.

    Order (spec): validate + persist confirmed contact-scoped entries
    first, then apply an optional full curated core update, then clear
    run scratch — so a provider/parse/persistence failure always retains
    the scratch notes for a later attempt.

    Two modes: run-scoped (existing direct callers — `run_id` given, source
    ids come from `messages`) and session-scoped (`run_id` None — supplied
    sources and outstanding scratch span terminal non-test session runs).
    `session_run_ids` freezes the close attempt's run set for scratch cleanup.
    """

    outcome: dict[str, Any] = {"saved": 0, "core_updated": False, "clarifications": []}

    if not contact_id or not session_id:
        return outcome

    # Trusted scope: the session must match the supplied agent+contact.
    session = await db.get(Session, session_id)
    if session is None:
        return outcome
    if session.agent_id != agent_id or session.contact_id != contact_id:
        raise ValueError("Session does not match the supplied agent/contact scope")

    if run_id is not None:
        run_ids = [run_id]
    else:
        scoped_runs = (
            select(Run.id)
            .join(Session, Session.id == Run.session_id)
            .where(
                Session.id == session_id,
                Session.agent_id == agent_id,
                Session.contact_id == contact_id,
                Run.agent_id == agent_id,
                Run.contact_id == contact_id,
                Run.is_test.is_(False),
                Run.status.in_(TERMINAL_STATUSES),
            )
            .order_by(Run.started_at, Run.id)
        )
        # A caller-provided frozen set narrows the scoped query — it's never
        # trusted alone; agent/contact/status filtering still applies.
        if session_run_ids is not None:
            scoped_runs = scoped_runs.where(Run.id.in_(session_run_ids))
        run_ids = list(await db.scalars(scoped_runs))
    if not run_ids:
        return outcome

    supplied_ids = [
        message.id
        for message in messages
        if isinstance(getattr(message, "id", None), str) and message.id
    ]
    if not supplied_ids:
        return outcome

    source_query = (
        select(Message)
        .join(Run, Message.run_id == Run.id)
        .join(Session, Run.session_id == Session.id)
        .where(
            Message.id.in_(supplied_ids),
            Message.subagent_id.is_(None),
            Message.role.in_(("user", "assistant")),
            Run.agent_id == agent_id,
            Run.contact_id == contact_id,
            Session.agent_id == agent_id,
            Session.contact_id == contact_id,
            Session.id == session_id,
        )
        .order_by(Run.started_at, Run.id, Message.seq, Message.id)
    )
    if run_id is not None:
        source_query = source_query.where(Message.run_id == run_id)
    else:
        source_query = source_query.where(Run.is_test.is_(False), Run.status.in_(TERMINAL_STATUSES))
    source_rows = list(await db.scalars(source_query))
    if not source_rows:
        return outcome

    # Snapshot outstanding scratch per run BEFORE the model call — the
    # clean path clears only these ids, never entries written mid-flight.
    scratch_by_run: dict[str, list[str]] = {}
    working_entries: list[dict] = []
    if run_id is not None:
        working_entries = await recall.get_run_entries(db, run_id)
        scratch_by_run[run_id] = [e["id"] for e in working_entries]
    else:
        scratch_rows = list(
            await db.scalars(
                select(MemoryEntry)
                .where(
                    MemoryEntry.run_id.in_(run_ids),
                    MemoryEntry.agent_id == agent_id,
                    MemoryEntry.contact_id == contact_id,
                    MemoryEntry.revoked_at.is_(None),
                )
                .order_by(MemoryEntry.created_at, MemoryEntry.id)
            )
        )
        for e in scratch_rows:
            working_entries.append(
                {
                    "id": e.id,
                    "key": e.key,
                    "value": e.value,
                    "tags": json.loads(e.tags) if e.tags else [],
                }
            )
            scratch_by_run.setdefault(e.run_id, []).append(e.id)

    # Incremental learning coverage (session-scoped): messages a successful
    # close already presented stay covered — a re-close learns only the new
    # tail instead of re-reading the whole transcript. NULL/corrupt coverage
    # = nothing proven learned → everything is presented again.
    learned_ids: set[str] = set()
    extractable_rows = source_rows
    context_tail_rows: list[Any] = []
    prior_entries: list[dict] = []
    if run_id is None:
        raw_cov = getattr(session, "learned_coverage", None)
        if raw_cov:
            try:
                parsed = json.loads(raw_cov)
                if isinstance(parsed, list):
                    learned_ids = {i for i in parsed if isinstance(i, str)}
            except Exception:
                learned_ids = set()
        # Scratch-cited sources must stay extractable — a scratch note can
        # cite an already-covered message; excluding it leaves the cite
        # unconfirmable and would wedge every later close.
        scratch_cited: set[str] = set()
        for e in scratch_rows:
            try:
                scratch_cited |= {
                    i for i in json.loads(e.source_refs or "[]") if isinstance(i, str)
                }
            except Exception:
                pass
        uncovered_rows = [
            m for m in source_rows if m.id not in learned_ids or m.id in scratch_cited
        ]
        if not uncovered_rows and not working_entries:
            return outcome  # fully learned — nothing new to extract
        # If scratch survives but nothing is uncovered, fall back to the
        # full supplied set so its cites stay confirmable.
        extractable_rows = uncovered_rows or source_rows
        covered_rows = [m for m in source_rows if m.id in learned_ids and m.id not in scratch_cited]
        context_tail_rows = covered_rows[-6:]

        # Prior durable entries as dedup/revision context — the learner
        # merges corrections instead of re-stating. Newest entries win the
        # budget; older ones simply leave the prompt (still in the store).
        prior_rows = list(
            await db.scalars(
                select(MemoryEntry)
                .where(
                    MemoryEntry.agent_id == agent_id,
                    MemoryEntry.contact_id == contact_id,
                    MemoryEntry.revoked_at.is_(None),
                    MemoryEntry.key.like("extracted-%"),
                )
                .order_by(MemoryEntry.created_at.desc(), MemoryEntry.id)
                .limit(100)
            )
        )
        chars = 0
        for e in prior_rows:
            chars += len(e.value or "")
            if chars > 8000:
                break
            prior_entries.append({"key": e.key, "value": e.value})
        prior_entries.reverse()  # chronological, oldest first

    # Current curated core — never the managed identity section.
    curated_existing = ""
    disk = core_mod._read_disk(core_mod._core_path(agent_id))
    if disk:
        _sha, _idt, curated_existing = core_mod.split_core(disk)
        if _sha is None:
            curated_existing = disk
    # Captured BEFORE the model call — a stale disk after the await means
    # an external edit happened; the publish will conflict rather than stomp.
    _disk_hash = core_mod._sha256(disk)

    def _tag(rows):
        return [
            {
                "id": m.id,
                "role": m.role,
                "at": str(getattr(m, "created_at", "")),
                "content": getattr(m, "content", "") or "",
            }
            for m in rows
        ]

    tagged = _tag(extractable_rows)
    payload = json.dumps(
        {
            "messages": tagged,
            "context_tail": _tag(context_tail_rows),
            "prior_entries": prior_entries,
            "scratch_notes": working_entries,
            "existing_curated_core": curated_existing,
        }
    )

    # Hard input-budget check — fail visibly, retain scratch.
    capped_model = agent_config.model.model_copy(
        update={"max_tokens": min(agent_config.model.max_tokens or 4096, 4096)}
    )
    adapter = await ProviderRegistry(db).for_model(agent_config.model.provider_id)
    info = await adapter.get_model_info(capped_model)
    budget = resolve_input_budget(
        info.get("resolved_model") or {},
        model_override=agent_config.model.max_context_tokens,
        run_override=agent_config.limits.max_context_tokens,
        output_tokens=capped_model.max_tokens,
    )["tokens"]
    request_msgs = [{"role": "user", "content": f"{MEMORY_EXTRACTION_PROMPT}\n\n{payload}"}]
    if count_tokens(request_msgs, info["model_str"]) > budget:
        raise RuntimeError("Memory extraction input exceeds the resolved input budget")

    await db.commit()
    # Session-scoped extraction has no run of its own — link the latest
    # frozen run so the receipt surfaces in that run's trace.
    ledger_run_id = run_id or (session_run_ids[-1] if session_run_ids else None)
    started = time.perf_counter()
    try:
        with capture_scope(
            run_id=ledger_run_id,
            session_id=session_id,
            agent_id=agent_id,
            purpose="reasoning",
            operation="memory_extract",
            source_message_ids=[message.id for message in source_rows],
        ):
            response = await adapter.complete(
                agent_model=capped_model,
                messages=request_msgs,
                tools=None,
            )
        await model_ledger.record_system_call(
            kind="extract",
            provider_id=agent_config.model.provider_id,
            model_name=agent_config.model.name,
            model_str=info["model_str"],
            agent_id=agent_id,
            session_id=session_id,
            run_id=ledger_run_id,
            response=response,
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail={"operation": "memory_extract"},
        )
    except BaseException as exc:
        await model_ledger.record_system_call(
            kind="extract",
            provider_id=agent_config.model.provider_id,
            model_name=agent_config.model.name,
            model_str=info["model_str"],
            agent_id=agent_id,
            session_id=session_id,
            run_id=ledger_run_id,
            error=exc,
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail={"operation": "memory_extract"},
        )
        raise

    try:
        data = json.loads((getattr(response, "content", "") or "").strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("Memory extraction returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Memory extraction returned a non-object payload")
    # Strict shape — malformed payloads keep scratch (no durable writes).
    memories = data.get("memories")
    if not isinstance(memories, list) or any(not isinstance(m, dict) for m in memories):
        raise RuntimeError("Memory extraction returned malformed memories")
    clarifications = data.get("clarifications", [])
    if not isinstance(clarifications, list) or any(
        not isinstance(question, str) or not question.strip() for question in clarifications
    ):
        raise RuntimeError("Memory extraction returned malformed clarifications")

    # Only USER message ids may confirm; a mixed valid+invalid cite list
    # rejects the whole candidate — no silent filtering.
    user_ids = {t["id"] for t in tagged if t["role"] == "user"}

    def _all_valid_cites(ids: Any) -> list[str] | None:
        if not isinstance(ids, list) or not ids:
            return None
        if any(not isinstance(i, str) or i not in user_ids for i in ids):
            return None
        return list(ids)

    _secret_pat = re.compile(MEMORY_CREDENTIAL_ASSIGNMENT_PATTERN)

    def _has_secret(text: str) -> bool:
        try:
            _r, redacted, _t = redact_text(text, max(1, len(text)))
            if redacted:
                return True
        except Exception:
            return True  # fail closed — never publish past a broken redactor
        return bool(_secret_pat.search(text))

    # First: durable contact+agent scoped entries — via store_snippet so the
    # FTS index is maintained; dedup key is a stable hash of kind+text so a
    # repeat extraction reuses the same entry with merged sources.

    saved = 0
    rejected = 0
    clarification_requested = bool(clarifications)
    safe_clarifications = [question for question in clarifications if not _has_secret(question)]
    rejected += len(clarifications) - len(safe_clarifications)
    clarifications = safe_clarifications
    for mem in memories:
        text = str(mem.get("text") or "").strip()
        kind = str(mem.get("kind") or "")
        if not text or kind not in ("fact", "preference", "lesson"):
            rejected += 1
            continue
        if _has_secret(text):
            rejected += 1
            continue  # reject without persisting the rejected secret
        cites = _all_valid_cites(mem.get("source_ids"))
        if cites is None:
            rejected += 1
            continue  # unconfirmed — never publish
        dedup_key = hashlib.sha256((kind + "\0" + text.casefold()).encode("utf-8")).hexdigest()
        existing = await db.scalar(
            select(MemoryEntry).where(
                MemoryEntry.agent_id == agent_id,
                MemoryEntry.contact_id == (contact_id or ""),
                MemoryEntry.key == f"extracted-{dedup_key[:24]}",
            )
        )
        if existing is not None:
            if existing.revoked_at is not None:
                continue  # revoked stays revoked — never revived or re-saved
            merged = set(json.loads(existing.source_refs or "[]")) | set(cites)
            existing.source_refs = json.dumps(sorted(merged))
            await db.flush()
            saved += 1
            continue
        await recall.store_snippet(
            db,
            contact_id=contact_id or "",
            agent_id=agent_id,
            key=f"extracted-{dedup_key[:24]}",
            value=text,
            tags=[kind],
            run_id=None,
            source_refs=cites,
        )
        saved += 1
    outcome["saved"] = saved
    if saved:
        await db.flush()

    # Then: optional full curated core — requires confirmed user cites AND
    # must pass the same credential guard.
    core_markdown = data.get("core_markdown")
    core_cites = _all_valid_cites(data.get("core_source_ids"))
    if (
        isinstance(core_markdown, str)
        and core_markdown.strip()
        and (core_cites is None or _has_secret(core_markdown))
    ):
        # A core proposal we can't confirm/publish (unverified cites or
        # credential-looking content) counts as rejected — scratch stays.
        rejected += 1
        core_markdown = None
    if core_markdown is not None and not isinstance(core_markdown, str):
        rejected += 1
    if not isinstance(data.get("core_source_ids"), list):
        rejected += 1
    if (
        isinstance(core_markdown, str)
        and core_markdown.strip()
        and core_cites
        and not clarification_requested
    ):
        try:
            snap = await core_mod.update_core(
                db,
                agent_config,
                core_markdown,
                expected_hash=_disk_hash,
                source_refs=core_cites,
            )
            outcome["core_updated"] = True
            outcome["core_revision_id"] = snap.revision_id
        except core_mod.CoreConflict as exc:
            outcome["core_conflict"] = str(exc)

    # Clarifications — existing operator notification, session action link.
    clarifications = [c for c in clarifications if c.strip()]
    outcome["clarifications"] = clarifications
    if clarifications and session_id:
        try:
            await create_notification(
                db,
                notification_type="memory_clarification",
                severity="info",
                title="Memory question needs clarification",
                message=clarifications[0],
                action_path=f"/agents/{agent_id}/chat?session={session_id}",
                entity_id=session_id,
                entity_type="session",
                agent_id=agent_id,
            )
        except Exception:
            pass

    if "core_conflict" in outcome and session_id:
        try:
            await create_notification(
                db,
                notification_type="memory_update_failed",
                severity="warning",
                title="Core memory update was not published",
                message="The original conversation and run scratch remain available for review.",
                action_path=f"/agents/{agent_id}/chat?session={session_id}",
                entity_id=run_id,
                entity_type="run",
                agent_id=agent_id,
            )
        except Exception:
            pass

    # Scratch clears ONLY after a fully-clean extraction + durable
    # retention — clarifications, rejected candidates, or a core conflict
    # all mean the run's evidence stays put for the next attempt.
    clean = not clarification_requested and rejected == 0 and "core_conflict" not in outcome
    if clean:
        for rid, ids in scratch_by_run.items():
            await recall.clear_run_entries(db, rid, entry_ids=ids)
        # Extend learned coverage by exactly what the learner was shown —
        # same commit as the scratch clear, so coverage and scratch never
        # disagree about whether the evidence was consumed.
        if run_id is None:
            session.learned_coverage = json.dumps(
                sorted(learned_ids | {m.id for m in extractable_rows})
            )
    await db.commit()
    return outcome
