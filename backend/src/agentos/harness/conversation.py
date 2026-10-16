"""Conversation state — durable replay of uncovered originals + summary.

A Conversation is the session's model-facing history for the next run:
stored Message rows for the session (deterministic per-run order), minus
covered rows, thinking rows, nested sub-agent rows, and the current run —
plus at most one rendered summary. A generated summary is never stored as
if it were an original message; coverage is recorded as real Message ids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update


@dataclass
class Conversation:
    """Uncovered originals + cumulative summary + coverage bookkeeping."""

    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    source_ids: list[set[str]] = field(default_factory=list)
    summary: str | None = None
    summary_id: str | None = None
    covered_ids: set[str] = field(default_factory=set)
    summary_version: int = 0
    # Unknown legacy coverage (NULL column) → retain originals alongside the
    # prior summary; never guess coverage.
    coverage_known: bool = True
    # Stored rows skipped during replay (malformed JSON, unsupported roles,
    # or simply already-covered) — replay reporting stays honest.
    dropped_rows: list[str] = field(default_factory=list)

    @classmethod
    async def load(
        cls,
        db: Any,
        session: Any,
        *,
        exclude_run_id: str | None = None,
    ) -> Conversation:
        """Load all parent-level stored records for the session.

        Order: (Run.started_at, Run.id, Message.seq, Message.id) — equal
        timestamps follow per-run seq, and no LIMIT cut drops history.
        Excludes: the current run, thinking rows, nested sub-agent rows, and
        already-covered Message ids.
        """
        from ..models.run import Message, Run

        summary, summary_id, covered_ids, version, coverage_known = await cls.coverage_state(
            db, session
        )

        stmt = (
            select(Message)
            .join(Run, Message.run_id == Run.id)
            .where(
                Run.session_id == session.id,
                Message.subagent_id.is_(None),
                Message.role != "thinking",
            )
            .order_by(Run.started_at, Run.id, Message.seq, Message.id)
        )
        if exclude_run_id:
            stmt = stmt.where(Message.run_id != exclude_run_id)
        conv = cls(
            session_id=session.id,
            summary=summary,
            summary_id=summary_id,
            covered_ids=covered_ids,
            summary_version=version,
            coverage_known=coverage_known,
        )
        from .context import format_stored_message

        async for row in await db.stream_scalars(stmt.execution_options(yield_per=200)):
            if row.id in covered_ids:
                continue
            rendered = format_stored_message(row)
            if not rendered:
                # Malformed/unsupported legacy record — recorded as dropped,
                # never replayed as an invented valid record.
                conv.dropped_rows.append(row.id)
                continue
            conv.messages.extend(rendered)
            conv.source_ids.extend([{row.id}] * len(rendered))
        return conv

    @classmethod
    async def coverage_state(
        cls,
        db: Any,
        session: Any,
    ) -> tuple[str | None, str | None, set[str], int, bool]:
        """Resolve (summary, summary_id, covered_ids, version, coverage_known).

        The canonical coverage parse — shared by load() and consumers that
        already hold their own row set (e.g. session-close summarization).
        An explicitly referenced snapshot is authoritative — and must be
        consistent with the session's cached fields (same session, same
        text, same coverage, same version). A missing, foreign, or
        mismatched snapshot is untrusted: originals are retained under
        the cached summary with NO coverage and summary_id=None.
        """
        covered_raw = getattr(session, "conversation_summary_coverage", None)
        summary = getattr(session, "conversation_summary", None)
        version = getattr(session, "conversation_summary_version", 0) or 0
        summary_id = getattr(session, "active_conversation_summary_id", None)
        covered_ids: set[str] = set()
        coverage_known_override: bool | None = None
        coverage_col = getattr(session, "conversation_summary_coverage_known", None)
        if summary_id:
            from ..models.conversation_summary import ConversationSummary

            snap = await db.get(ConversationSummary, summary_id)
            if (
                snap is not None
                and snap.session_id == session.id
                and snap.version == version
                and snap.summary == summary
                and snap.covered_message_ids == (covered_raw or "[]")
                and (coverage_col is None or snap.coverage_known == bool(coverage_col))
            ):
                covered_raw = snap.covered_message_ids
            else:
                # Invalid reference — retain all originals, report unknown.
                covered_raw = None
                covered_ids = set()
                summary_id = None
                coverage_known_override = False
            # summary/version stay the SESSION's CAS-tracked values.
        # Covered ids parse independently of the coverage flag — valid
        # explicit covered ids may still filter originals even when total
        # coverage is unknown.
        if covered_raw:
            try:
                parsed = json.loads(covered_raw)
                if isinstance(parsed, list) and all(isinstance(x, str) and x for x in parsed):
                    covered_ids = set(parsed)
                else:
                    covered_raw = None
            except (json.JSONDecodeError, TypeError):
                covered_raw = None
        # Coverage-known: a session with NO nonempty prior summary has
        # nothing to lose — always known. With a summary, the explicit
        # column wins; NULL derives unknown only when coverage was never
        # recorded. An invalid snapshot override forces unknown.
        if not (summary and summary.strip()):
            covered_ids = set()  # orphaned coverage never filters
            coverage_known = True
        elif coverage_known_override is not None:
            coverage_known = coverage_known_override
        elif coverage_col is not None:
            coverage_known = bool(coverage_col)
        else:
            coverage_known = covered_raw is not None
        return summary, summary_id, covered_ids, version, coverage_known

    def render(self) -> list[dict[str, Any]]:
        """Model-facing list: summary rendered exactly once, then uncovered."""
        from .compaction import _summary_message

        if not self.summary:
            return list(self.messages)
        return [_summary_message(self.summary, [], self.messages), *self.messages]

    def append(self, message: dict[str, Any], source_ids: set[str] | None = None) -> None:
        """Append a live (in-run) row. Transient rows get empty ids — never
        invented DB ids."""
        self.messages.append(message)
        self.source_ids.append(set(source_ids or set()))

    async def store_summary(
        self,
        db: Any,
        summary: str,
        covered_ids: set[str],
        *,
        retained_head_ids: set[str] | None = None,
        retained_tail_ids: set[str] | None = None,
    ) -> bool:
        """Persist summary + coverage + version + immutable snapshot in one
        short transaction.

        Conditional on the expected version — a concurrent compactor loses
        instead of clobbering, and the loser leaves NO snapshot row. The
        active pointer references the new snapshot; the prior snapshot's id
        is recorded, never fabricated for legacy sessions.
        """
        import uuid as _uuid

        from ..models.conversation_summary import ConversationSummary
        from ..models.session import Session

        snapshot_id = _uuid.uuid4().hex
        new_version = self.summary_version + 1
        stmt = (
            update(Session)
            .where(
                Session.id == self.session_id,
                Session.conversation_summary_version == self.summary_version,
            )
            .values(
                conversation_summary=summary,
                conversation_summary_coverage=json.dumps(sorted(covered_ids)),
                conversation_summary_version=new_version,
                active_conversation_summary_id=snapshot_id,
                conversation_summary_coverage_known=self.coverage_known,
            )
        )
        result = await db.execute(stmt)
        if result.rowcount == 0:
            return False
        db.add(
            ConversationSummary(
                id=snapshot_id,
                session_id=self.session_id,
                version=new_version,
                prior_summary_id=self.summary_id,
                summary=summary,
                covered_message_ids=json.dumps(sorted(covered_ids)),
                retained_head_ids=json.dumps(sorted(retained_head_ids or set())),
                retained_tail_ids=json.dumps(sorted(retained_tail_ids or set())),
                coverage_known=self.coverage_known,
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()
        self.summary = summary
        self.summary_id = snapshot_id
        self.covered_ids = set(covered_ids)
        self.summary_version += 1
        return True
