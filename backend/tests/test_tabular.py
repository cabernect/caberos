"""Tabular row layer — bounded parse, exact queries, inspection endpoints."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agentos.auth import require_operator
from agentos.config import settings
from agentos.db import get_db
from agentos.main import app
from agentos.models.operator import Operator


@pytest.fixture
async def client(db, monkeypatch, tmp_path: Path):
    async def fake_operator():
        return Operator(id="test-operator", username="test", password_hash="x")

    app.dependency_overrides[require_operator] = fake_operator
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(settings, "knowledge_root", tmp_path / "knowledge")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


CSV_BYTES = (
    b"Name,Qty,Name\n"
    b"Apples,5,red\n"
    b'"Multi\nline",12,green\n'
    b"Cherries,3\n"  # uneven row
    b"Dates,9,blue,extra-cell\n"  # too many cells
)


@pytest.mark.asyncio
async def test_csv_ingest_persists_rows_with_warnings(client):
    resp = await client.post(
        "/api/knowledge/scopes/shared/documents/upload",
        files={"file": ("stock.csv", CSV_BYTES, "text/csv")},
    )
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["status"] == "indexed"

    sheets = await client.get(f"/api/knowledge/scopes/shared/documents/{doc['id']}/sheets")
    assert sheets.status_code == 200
    body = sheets.json()
    assert [s["name"] for s in body["sheets"]] == ["csv"]
    sheet = body["sheets"][0]
    assert sheet["row_count"] == 4
    assert [c["label"] for c in sheet["columns"]] == ["Name", "Qty", "Name"]
    assert any("Duplicate header" in w for w in sheet["warnings"])
    assert any("extra cells were dropped" in w for w in sheet["warnings"])

    rows = await client.get(
        f"/api/knowledge/scopes/shared/documents/{doc['id']}/rows",
        params={"sheet": "csv"},
    )
    assert rows.status_code == 200
    items = rows.json()["items"]
    assert [i["row_number"] for i in items] == [2, 3, 4, 5]
    assert items[0]["cells"]["col_1"] == "Apples"
    assert items[0]["coord"].startswith("csv!A2:")
    # Uneven rows preserve empty cells; quoted newlines stay inside the cell.
    assert items[2]["cells"]["col_3"] is None
    assert "\n" in items[1]["cells"]["col_1"]


@pytest.mark.asyncio
async def test_xlsx_multi_sheet_and_query_rows(client, db):
    import io

    from openpyxl import Workbook
    from sqlalchemy import select

    from agentos.knowledge.tabular import query_rows
    from agentos.models.document import Document

    book = Workbook()
    ws = book.active
    ws.title = "Sales"
    ws.append(["City", "Revenue"])
    ws.append(["Hue", 10])
    ws.append(["Saigon", 40])
    ws.append(["Hanoi", 25])
    ws2 = book.create_sheet("Costs")
    ws2.append(["City", "Cost"])
    ws2.append(["Hue", 4])
    buffer = io.BytesIO()
    book.save(buffer)

    resp = await client.post(
        "/api/knowledge/scopes/shared/documents/upload",
        files={
            "file": (
                "book.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 200
    doc_id = resp.json()["id"]

    sheets = (await client.get(f"/api/knowledge/scopes/shared/documents/{doc_id}/sheets")).json()[
        "sheets"
    ]
    assert [(s["name"], s["row_count"]) for s in sheets] == [("Sales", 3), ("Costs", 1)]
    assert any("cached value" in w for w in sheets[0]["warnings"])

    # Multi-sheet requires an explicit sheet choice.
    ambiguous = await client.get(f"/api/knowledge/scopes/shared/documents/{doc_id}/rows")
    assert ambiguous.status_code == 400
    costs = await client.get(
        f"/api/knowledge/scopes/shared/documents/{doc_id}/rows",
        params={"sheet": "Costs"},
    )
    assert [i["coord"] for i in costs.json()["items"]] == ["Costs!A2:B2"]

    document = await db.scalar(select(Document).where(Document.id == doc_id))

    # Exact filter + aggregate over the full set.
    result = await query_rows(
        db,
        document,
        sheet_name="Sales",
        filters=[{"column": "Revenue", "op": "gte", "value": 10}],
        aggregates=[{"op": "count"}, {"op": "sum", "column": "Revenue"}],
        limit=2,
    )
    assert result["matched_count"] == 3
    assert result["aggregates"] == [
        {"op": "count", "column": None, "value": 3},
        {"op": "sum", "column": "Revenue", "value": 75},
    ]
    assert len(result["items"]) == 2 and result["truncated"]
    page2 = await query_rows(
        db,
        document,
        sheet_name="Sales",
        filters=[{"column": "Revenue", "op": "gte", "value": 10}],
        after_row=int(result["next_cursor"]),
        limit=2,
    )
    assert [i["row_number"] for i in page2["items"]] == [4]

    # Allowlist enforcement and unknown columns — errors, never raw SQL.
    assert "error" in await query_rows(
        db,
        document,
        sheet_name="Sales",
        filters=[{"column": "City", "op": "DROP TABLE", "value": 1}],
    )
    assert "error" in await query_rows(
        db,
        document,
        sheet_name="Sales",
        filters=[{"column": "Nope", "op": "eq", "value": 1}],
    )
    assert "error" in await query_rows(db, document, sheet_name="Missing")


@pytest.mark.asyncio
async def test_tabular_stale_cursor_scope_and_refusals(client):
    resp = await client.post(
        "/api/knowledge/scopes/shared/documents/upload",
        files={"file": ("stock.csv", CSV_BYTES, "text/csv")},
    )
    doc_id = resp.json()["id"]

    stale = await client.get(
        f"/api/knowledge/scopes/shared/documents/{doc_id}/rows",
        params={"cursor": "bogus:1"},
    )
    assert stale.status_code == 409

    # Rows of an agent-private doc are invisible from the shared scope.
    private = await client.post(
        "/api/knowledge/scopes/missing/documents/upload",
        files={"file": ("x.csv", CSV_BYTES, "text/csv")},
    )
    assert private.status_code == 404  # unknown scope

    # Legacy .xls stays refused; so do unknown types.
    refused = await client.post(
        "/api/knowledge/scopes/shared/documents/upload",
        files={"file": ("old.xls", b"PK", "application/vnd.ms-excel")},
    )
    assert refused.status_code == 400
    assert ".xlsx or .csv" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_doc_query_rows_executes_through_mediator(client, db, workspace):
    """The row-query tool must run through the syscall mediator — the
    injection path supplies db/agent_id, so a mediated call returns real
    rows, never `execution error: 'db'`."""
    from types import SimpleNamespace

    from agentos.capabilities.builtin import register_builtin_capabilities
    from agentos.capabilities.registry import registry
    from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    resp = await client.post(
        "/api/knowledge/scopes/shared/documents/upload",
        files={"file": ("stock.csv", CSV_BYTES, "text/csv")},
    )
    doc_id = resp.json()["id"]

    registry._caps.clear()
    register_builtin_capabilities()
    try:
        handler = SyscallHandler(db=db, workspace_path=workspace)
        result = await handler.mediate(
            call=ToolCall(
                id="1",
                name="doc_query_rows",
                args={
                    "document_id": doc_id,
                    "sheet": "csv",
                    "aggregates": [{"op": "count"}],
                },
            ),
            session=SimpleNamespace(contact_id="c1", id="s1", channel=None),
            agent_config=AgentConfig(
                id="a",
                name="A",
                model=ModelConfig(provider_id="p", name="m"),
                capabilities=[CapabilityGrant(name="doc_query_rows", require_approval=False)],
            ),
            run_id="r1",
        )
    finally:
        registry._caps.clear()

    assert result.allowed is True
    out = result.output
    assert "error" not in out
    assert out["matched_count"] == 4
    assert out["aggregates"] == [{"op": "count", "column": None, "value": 4}]
    assert len(out["rows"]) == 4
