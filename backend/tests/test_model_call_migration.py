"""model_calls → unified ledger migration (W10 stage 1).

Legacy DBs carry model_calls with NOT NULL run_id/agent_id — embedding
calls have no run/agent, so the unified ledger relaxes both via a table
rebuild (rename → recreate → copy → drop), then drops embedding_calls.
"""

import pytest
from sqlalchemy import text

from agentos.db_backends.sqlite_backend import SQLiteBackend

LEGACY_DDL = """
CREATE TABLE model_calls (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES runs(id),
    agent_id VARCHAR(36) NOT NULL,
    sub_agent_id VARCHAR(36),
    turn INTEGER NOT NULL,
    provider_id VARCHAR(36),
    model_name VARCHAR(255),
    model_str VARCHAR(255),
    streamed BOOLEAN NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    cached_tokens INTEGER,
    cost FLOAT NOT NULL,
    latency_ms INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    error TEXT,
    created_at DATETIME
)
"""

LEGACY_ROW = {
    "id": "mc-1",
    "run_id": "run-1",
    "agent_id": "agent-1",
    "sub_agent_id": "sub-1",
    "turn": 3,
    "provider_id": "prov-1",
    "model_name": "gpt-x",
    "model_str": "openai/gpt-x",
    "streamed": 1,
    "tokens_in": 123,
    "tokens_out": 45,
    "cached_tokens": 12,
    "cost": 0.0123,
    "latency_ms": 987,
    "status": "ok",
    "error": "some error text",
    "created_at": "2024-05-01 12:34:56",
}


async def _seed_legacy(engine, rows=(LEGACY_ROW,)):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE runs (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO runs (id) VALUES ('run-1')"))
        await conn.execute(text(LEGACY_DDL))
        await conn.execute(text("CREATE INDEX ix_model_calls_run ON model_calls(run_id)"))
        for row in rows:
            cols = ", ".join(row)
            await conn.execute(
                text(
                    f"INSERT INTO model_calls ({cols}) VALUES ({', '.join(':' + c for c in row)})"
                ),
                row,
            )


async def _columns(conn):
    result = await conn.execute(text("PRAGMA table_info(model_calls)"))
    return {r[1]: {"notnull": r[3], "type": r[2]} for r in result.fetchall()}


async def _init(backend, engine):
    async with engine.begin() as conn:
        await backend.init_schema(conn)


@pytest.fixture
async def backend_engine(tmp_path):
    backend = SQLiteBackend()
    engine = backend.create_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield backend, engine
    await engine.dispose()


async def test_legacy_table_rebuilt_rows_preserved(backend_engine):
    backend, engine = backend_engine
    await _seed_legacy(engine)
    await _init(backend, engine)

    async with engine.begin() as conn:
        cols = await _columns(conn)
        assert cols["run_id"]["notnull"] == 0
        assert cols["agent_id"]["notnull"] == 0
        for new_col in ("kind", "purpose", "thinking_tokens", "detail"):
            assert new_col in cols

        row = (
            (await conn.execute(text("SELECT * FROM model_calls WHERE id='mc-1'"))).mappings().one()
        )
        # Every legacy column survived the rebuild byte-for-byte.
        for name, expected in LEGACY_ROW.items():
            assert row[name] == expected, f"{name}: {row[name]!r} != {expected!r}"
        assert row["kind"] == "chat"
        assert row["purpose"] == "reasoning"
        assert row["thinking_tokens"] is None
        assert row["detail"] is None

        # NULL run/agent rows (embedding calls) land after the migration.
        await conn.execute(
            text(
                "INSERT INTO model_calls (id, run_id, agent_id, kind, purpose, "
                "turn, streamed, tokens_in, tokens_out, cost, latency_ms, status) "
                "VALUES ('emb-1', NULL, NULL, 'embedding', 'embedding', "
                "0, 0, 7, 0, 0.001, 42, 'ok')"
            )
        )
        # Column defaults hold for fresh chat rows.
        await conn.execute(
            text(
                "INSERT INTO model_calls (id, run_id, agent_id, turn, streamed, "
                "tokens_in, tokens_out, cost, latency_ms, status) "
                "VALUES ('chat-1', 'run-1', 'agent-1', 1, 0, 1, 1, 0.0, 1, 'ok')"
            )
        )
    async with engine.connect() as conn:
        chat = (
            (await conn.execute(text("SELECT * FROM model_calls WHERE id='chat-1'")))
            .mappings()
            .one()
        )
        assert chat["kind"] == "chat" and chat["purpose"] == "reasoning"


async def test_init_schema_twice_is_idempotent(backend_engine):
    backend, engine = backend_engine
    await _seed_legacy(engine)
    await _init(backend, engine)
    await _init(backend, engine)

    async with engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM model_calls"))).scalar()
        assert count == 1
        cols = await _columns(conn)
        assert cols["run_id"]["notnull"] == 0


async def test_failed_create_rolls_back_original_table(backend_engine, monkeypatch):
    """The new table never existing must leave the legacy table untouched."""
    backend, engine = backend_engine
    await _seed_legacy(engine)

    from agentos.models.model_call import ModelCall

    def boom(*_args, **_kwargs):
        raise RuntimeError("injected create failure")

    monkeypatch.setattr(ModelCall.__table__, "create", boom)
    with pytest.raises(RuntimeError, match="injected create failure"):
        await _init(backend, engine)

    async with engine.connect() as conn:
        # Savepoint rolled the rename back — the original table + row live.
        cols = await _columns(conn)
        assert cols["run_id"]["notnull"] == 1
        assert "kind" not in cols
        count = (await conn.execute(text("SELECT count(*) FROM model_calls"))).scalar()
        assert count == 1
        legacy = (
            await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='model_calls_legacy'"
                )
            )
        ).fetchone()
        assert legacy is None


async def test_failed_copy_rolls_back_original_table(backend_engine, monkeypatch):
    """The copy step failing after the new table exists restores the
    original table AND its indexes — nothing half-migrated."""
    backend, engine = backend_engine
    await _seed_legacy(engine)

    from sqlalchemy.ext.asyncio import AsyncConnection

    real_execute = AsyncConnection.execute

    async def guarded(self, statement, *args, **kwargs):
        sql = getattr(statement, "text", str(statement))
        if sql.startswith("INSERT INTO model_calls"):
            raise RuntimeError("injected copy failure")
        return await real_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", guarded)
    with pytest.raises(RuntimeError, match="injected copy failure"):
        await _init(backend, engine)

    async with engine.connect() as conn:
        # Original schema, row, and index all survive — the rename was
        # rolled back, not just the copy.
        cols = await _columns(conn)
        assert cols["run_id"]["notnull"] == 1
        assert "kind" not in cols
        count = (await conn.execute(text("SELECT count(*) FROM model_calls"))).scalar()
        assert count == 1
        index = (
            await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND name='ix_model_calls_run'"
                )
            )
        ).fetchone()
        assert index is not None
        orphan = (
            await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='model_calls_legacy'"
                )
            )
        ).fetchone()
        assert orphan is None


async def test_migration_creates_ledger_indexes(backend_engine):
    """The W10 indexes exist after init and survive a second run."""
    backend, engine = backend_engine
    await _seed_legacy(engine)
    await _init(backend, engine)

    async with engine.connect() as conn:
        names = {
            r[0]
            for r in (
                await conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
            ).fetchall()
        }
        for expected in (
            "ix_model_calls_run_created",
            "ix_model_calls_provider_model",
            "ix_model_calls_kind_created",
            "ix_audit_run_call_sub",
            "ix_run_sources_run_call_sub",
            "ix_artifact_revisions_source_call",
        ):
            assert expected in names

    await _init(backend, engine)  # second init — index creation idempotent


async def test_audit_created_at_nullable_additive(backend_engine):
    """Legacy audit rows keep NULL created_at (never fabricated); rows
    written through the ORM on the migrated DB get real UTC."""
    backend, engine = backend_engine
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE runs (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO runs (id) VALUES ('run-1')"))
        await conn.execute(
            text(
                "CREATE TABLE audit_records ("
                "id VARCHAR(36) PRIMARY KEY, run_id VARCHAR(36) NOT NULL REFERENCES runs(id), "
                "agent_id VARCHAR(36) NOT NULL, sub_agent_id VARCHAR(36), "
                "capability_name VARCHAR(255) NOT NULL, subject_contact_id VARCHAR(36), "
                "allowed BOOLEAN NOT NULL, outcome VARCHAR(20) NOT NULL, "
                "denied_reason TEXT, cost FLOAT NOT NULL, latency_ms INTEGER NOT NULL, "
                "args TEXT NOT NULL, result TEXT)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO audit_records (id, run_id, agent_id, capability_name, "
                "allowed, outcome, cost, latency_ms, args) "
                "VALUES ('a-legacy', 'run-1', 'ag', 'read_file', 1, 'ok', 0.0, 1, '{}')"
            )
        )
    await _init(backend, engine)

    async with engine.begin() as conn:
        legacy = (
            await conn.execute(text("SELECT created_at FROM audit_records WHERE id='a-legacy'"))
        ).scalar()
        assert legacy is None

    # A fresh row through the ORM on the migrated DB gets a real timestamp.
    from sqlalchemy.ext.asyncio import AsyncSession

    from agentos.models.audit import AuditRecord

    async with AsyncSession(engine) as session:
        session.add(
            AuditRecord(
                id="a-new",
                run_id="run-1",
                agent_id="ag",
                capability_name="read_file",
                allowed=True,
            )
        )
        await session.commit()
    async with engine.connect() as conn:
        fresh = (
            await conn.execute(text("SELECT created_at FROM audit_records WHERE id='a-new'"))
        ).scalar()
        assert fresh is not None


async def test_fresh_init_has_no_embedding_calls(backend_engine):
    backend, engine = backend_engine
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE embedding_calls (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO embedding_calls (id) VALUES ('ec-1')"))
    await _init(backend, engine)

    async with engine.connect() as conn:
        gone = (
            await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='embedding_calls'")
            )
        ).fetchone()
        assert gone is None
        # Fresh DBs get the full ledger schema straight from create_all.
        cols = await _columns(conn)
        assert cols["run_id"]["notnull"] == 0
        assert "detail" in cols


# --- run_id FK removal (user-approved: string reference, no enforcement) ---

NULLABLE_FK_DDL = """
CREATE TABLE model_calls (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) REFERENCES runs(id),
    agent_id VARCHAR(36),
    sub_agent_id VARCHAR(36),
    turn INTEGER NOT NULL,
    provider_id VARCHAR(36),
    model_name VARCHAR(255),
    model_str VARCHAR(255),
    streamed BOOLEAN NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    cached_tokens INTEGER,
    cost FLOAT NOT NULL,
    latency_ms INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    error TEXT,
    created_at DATETIME,
    kind VARCHAR(20) NOT NULL DEFAULT 'chat',
    purpose VARCHAR(20) NOT NULL DEFAULT 'reasoning',
    thinking_tokens INTEGER,
    detail JSON
)
"""

ORPHAN_ROW = {**LEGACY_ROW, "id": "mc-orphan", "run_id": "ghost-run-404"}


async def _seed_nullable_fk(engine, rows):
    """Seed an already-nullable legacy table that still carries the run_id
    FK. FK enforcement is disabled only for the seed — matching the real
    dev DB state that grew orphan ledger rows."""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.execute(text("CREATE TABLE runs (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO runs (id) VALUES ('run-1')"))
        await conn.execute(text(NULLABLE_FK_DDL))
        for row in rows:
            cols = ", ".join(row)
            await conn.execute(
                text(
                    f"INSERT INTO model_calls ({cols}) VALUES ({', '.join(':' + c for c in row)})"
                ),
                row,
            )


async def test_nullable_table_with_fk_still_rebuilt(backend_engine):
    """Nullable-but-FKed tables must also be rebuilt — enforced integrity
    is intentionally given up."""
    backend, engine = backend_engine
    await _seed_nullable_fk(engine, [LEGACY_ROW, ORPHAN_ROW])
    await _init(backend, engine)

    async with engine.begin() as conn:
        # Orphan row survives intact — its ghost run_id is preserved,
        # never nulled or deleted.
        row = (
            (await conn.execute(text("SELECT * FROM model_calls WHERE id='mc-orphan'")))
            .mappings()
            .one()
        )
        for name, expected in ORPHAN_ROW.items():
            assert row[name] == expected
        fks = (await conn.execute(text("PRAGMA foreign_key_list(model_calls)"))).fetchall()
        assert fks == []
        # The lookup index still exists.
        idx = (
            await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND name='ix_model_calls_run_created'"
                )
            )
        ).scalar_one_or_none()
        assert idx == "ix_model_calls_run_created"
        # Unknown-run ledger inserts are now allowed (intentional).
        await conn.execute(
            text(
                "INSERT INTO model_calls (id, run_id, agent_id, turn, streamed, "
                "tokens_in, tokens_out, cost, latency_ms, status) "
                "VALUES ('mc-new', 'never-existed', 'a', 0, 0, 1, 1, 0.0, 1, 'ok')"
            )
        )


async def test_legacy_orphan_rows_survive_full_rebuild(backend_engine):
    """NOT NULL + FK + orphan row: the real dev-DB shape. FK enforcement is
    off for the seed only — like the live DB's own state."""
    backend, engine = backend_engine
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=OFF"))
        await conn.execute(text("CREATE TABLE runs (id VARCHAR(36) PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO runs (id) VALUES ('run-1')"))
        await conn.execute(text(LEGACY_DDL))
        for row in (LEGACY_ROW, ORPHAN_ROW):
            cols = ", ".join(row)
            await conn.execute(
                text(
                    f"INSERT INTO model_calls ({cols}) VALUES ({', '.join(':' + c for c in row)})"
                ),
                row,
            )
    await _init(backend, engine)
    async with engine.begin() as conn:
        ids = {r[0] for r in (await conn.execute(text("SELECT id FROM model_calls"))).fetchall()}
        assert ids == {"mc-1", "mc-orphan"}
        fks = (await conn.execute(text("PRAGMA foreign_key_list(model_calls)"))).fetchall()
        assert fks == []
        # Second init is a no-op.
    await _init(backend, engine)
    async with engine.begin() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM model_calls"))).scalar()
        assert count == 2


async def test_fresh_table_has_no_run_fk(backend_engine):
    """New databases create model_calls with no run_id FK at all."""
    backend, engine = backend_engine
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE runs (id VARCHAR(36) PRIMARY KEY)"))
    await _init(backend, engine)
    async with engine.begin() as conn:
        fks = (await conn.execute(text("PRAGMA foreign_key_list(model_calls)"))).fetchall()
        assert all(row[3] != "run_id" for row in fks)


async def test_postgres_drops_custom_named_run_fk():
    """PG path uses the exact lead-authored constraint query and drops each
    returned name — quote-escaped — leaving other constraints alone.
    (No live Postgres is exercised — the recipe is verified against a
    recording stub.)"""
    from unittest.mock import AsyncMock

    from agentos.db_backends.postgres_backend import PostgresBackend

    backend = PostgresBackend()
    statements = []

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class _Conn:
        async def execute(self, clause):
            stmt = str(clause)
            statements.append(stmt)
            if "pg_constraint" in stmt:
                return _Result([('model_calls_run"f"key_fk',), ("mc_fk2",)])
            return _Result([])

    backend.column_exists = AsyncMock(return_value=True)
    backend.add_column = AsyncMock()
    await backend._apply_schema_patches(_Conn())

    drops = [s for s in statements if "DROP CONSTRAINT" in s]
    assert drops == [
        'ALTER TABLE model_calls DROP CONSTRAINT "model_calls_run""f""key_fk"',
        'ALTER TABLE model_calls DROP CONSTRAINT "mc_fk2"',
    ]
    assert any("pg_constraint" in s for s in statements)
