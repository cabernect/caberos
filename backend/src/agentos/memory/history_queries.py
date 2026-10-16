"""Subject-scoped raw-history queries; indexed hits remain tied to real records."""

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
  AND m.subagent_id IS NULL
  AND m.role IN ('user', 'assistant')
  AND to_tsvector('simple', m.content) @@ websearch_to_tsquery('simple', :q)
ORDER BY ts_rank_cd(
  to_tsvector('simple', m.content),
  websearch_to_tsquery('simple', :q)
) DESC, m.created_at DESC, m.id
LIMIT :limit
"""
