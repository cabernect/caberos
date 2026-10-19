"""Subject-scoped raw-history queries; indexed hits remain tied to real records."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.run import Message, Run

MAX_EVIDENCE_CHARS = 4000
MAX_EVIDENCE_ROWS = 10

SQLITE_SCOPED_HISTORY = """
SELECT m.id, m.run_id, r.session_id, m.content
FROM messages_fts AS f
JOIN messages AS m ON m.id = f.message_id
JOIN runs AS r ON r.id = m.run_id
JOIN sessions AS s ON s.id = r.session_id
WHERE f.agent_id = :aid
  AND r.agent_id = :aid
  AND s.agent_id = :aid
  AND s.contact_id = :cid
  AND r.trigger != 'reflection'
  AND m.subagent_id IS NULL
  AND m.role IN ('user', 'assistant')
  AND messages_fts MATCH :q
ORDER BY rank, m.id
LIMIT :limit
"""

POSTGRES_SCOPED_HISTORY = """
SELECT m.id, m.run_id, r.session_id, m.content
FROM messages AS m
JOIN runs AS r ON r.id = m.run_id
JOIN sessions AS s ON s.id = r.session_id
WHERE r.agent_id = :aid
  AND s.agent_id = :aid
  AND s.contact_id = :cid
  AND r.trigger != 'reflection'
  AND m.subagent_id IS NULL
  AND m.role IN ('user', 'assistant')
  AND to_tsvector('simple', m.content) @@ websearch_to_tsquery('simple', :q)
ORDER BY ts_rank_cd(
  to_tsvector('simple', m.content),
  websearch_to_tsquery('simple', :q)
) DESC, m.created_at DESC, m.id
LIMIT :limit
"""


def session_task_evidence(*, session_id: str, agent_id: str, contact_id: str, run_ids: list[str]):
    return (
        select(Message)
        .join(Run, Message.run_id == Run.id)
        .where(
            Run.id.in_(run_ids),
            Run.session_id == session_id,
            Run.agent_id == agent_id,
            Run.contact_id == contact_id,
            Run.is_test.is_(False),
            Run.trigger != "reflection",
            Run.status.in_(("completed", "failed", "stopped", "interrupted")),
            Message.subagent_id.is_(None),
            Message.role.in_(("user", "assistant", "tool_call", "tool")),
        )
        .order_by(Run.started_at, Run.id, Message.seq, Message.id)
    )


async def freeze_session_evidence(
    db: AsyncSession, *, session_id: str, agent_id: str, contact_id: str, run_ids: list[str]
) -> list[Message]:
    return list(
        await db.scalars(
            session_task_evidence(
                session_id=session_id, agent_id=agent_id, contact_id=contact_id, run_ids=run_ids
            )
        )
    )


async def read_frozen_evidence(
    db: AsyncSession,
    *,
    session_id: str,
    agent_id: str,
    contact_id: str,
    run_ids: list[str],
    message_ids: list[str],
    run_id: str | None = None,
    message_id: str | None = None,
    offset: int = 0,
    limit: int = MAX_EVIDENCE_ROWS,
    content_offset: int = 0,
    query: str | None = None,
) -> dict:
    if (
        type(offset) is not int
        or type(content_offset) is not int
        or type(limit) is not int
        or offset < 0
        or content_offset < 0
        or not 1 <= limit <= MAX_EVIDENCE_ROWS
    ):
        raise ValueError("Invalid evidence page")
    if content_offset and not message_id:
        raise ValueError("Content continuation requires a specific message_id")
    statement = (
        session_task_evidence(
            session_id=session_id, agent_id=agent_id, contact_id=contact_id, run_ids=run_ids
        )
        .with_only_columns(
            Message.id,
            Message.run_id,
            Message.role,
            func.substr(Message.content, content_offset + 1, MAX_EVIDENCE_CHARS).label("content"),
            func.length(Message.content).label("content_length"),
        )
        .where(Message.id.in_(message_ids))
    )
    if run_id is not None:
        statement = statement.where(Message.run_id == run_id)
    if message_id is not None:
        statement = statement.where(Message.id == message_id)
    if query:
        statement = statement.where(Message.content.icontains(query, autoescape=True))
    rows = list((await db.execute(statement.offset(offset).limit(limit + 1))).all())
    return {
        "rows": [
            {
                "message_id": row.id,
                "run_id": row.run_id,
                "role": row.role,
                "content": row.content,
                "content_offset": content_offset,
                "content_length": row.content_length,
                "next_content_offset": (
                    content_offset + len(row.content)
                    if content_offset + len(row.content) < row.content_length
                    else None
                ),
            }
            for row in rows[:limit]
        ],
        "next_offset": offset + limit if len(rows) > limit else None,
    }
