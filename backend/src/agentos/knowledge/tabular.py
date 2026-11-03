"""Tabular (CSV/XLSX) parsing, persistence, and exact row queries.

Rows are the canonical queryable layer — chunks stay for lexical discovery,
but complete-set questions go through ``query_rows`` with an allowlisted
predicate grammar. No raw SQL, no evaluated expressions, no guessed totals.
"""

import csv
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.document import Document, DocumentRow, DocumentSheet

# Published parse limits — exceeding them raises TabularParseError, never
# silently truncates and calls the document complete.
MAX_SHEETS = 32
MAX_ROWS_PER_SHEET = 50_000
MAX_COLUMNS = 200
MAX_CELL_CHARS = 2_000
MAX_XLSX_DECOMPRESSED_BYTES = 256 * 1024 * 1024
CSV_SNIFF_BYTES = 8 * 1024
CSV_SHEET_NAME = "csv"  # synthetic sheet name for single-table CSVs

TABULAR_SUFFIXES = {".csv", ".xlsx"}


class TabularParseError(ValueError):
    """Raised when a tabular file exceeds limits or cannot be parsed."""


@dataclass
class ParsedColumn:
    id: str
    label: str
    kind: str = "empty"  # text | number | bool | date | mixed | empty


@dataclass
class ParsedRow:
    row_number: int
    cells: dict[str, Any]


@dataclass
class ParsedSheet:
    name: str
    index: int
    columns: list[ParsedColumn]
    rows: list[ParsedRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hidden: bool = False


def _cell_value(value: Any, warnings: list[str]) -> Any:
    """Normalize a cell to a JSON-safe typed value (never evaluates formulas)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value)
    if len(text) > MAX_CELL_CHARS:
        if not any(w.startswith("Cell text truncated") for w in warnings):
            warnings.append(
                f"Cell text truncated at {MAX_CELL_CHARS} chars — stored value is bounded"
            )
        text = text[:MAX_CELL_CHARS]
    return text


def _infer_kinds(columns: list[ParsedColumn], rows: list[ParsedRow]) -> None:
    """Assign each column a value kind from observed cells (mixed is explicit)."""
    for col in columns:
        kinds = set()
        for row in rows:
            value = row.cells.get(col.id)
            if value is None:
                continue
            if isinstance(value, bool):
                kinds.add("bool")
            elif isinstance(value, (int, float)):
                kinds.add("number")
            elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].*)?", value):
                kinds.add("date")
            else:
                kinds.add("text")
        if len(kinds) > 1:
            col.kind = "mixed"
        elif kinds:
            col.kind = kinds.pop()


def _build_columns(header: list[Any], warnings: list[str]) -> list[ParsedColumn]:
    if len(header) > MAX_COLUMNS:
        raise TabularParseError(f"Sheet exceeds the {MAX_COLUMNS}-column limit ({len(header)})")
    columns: list[ParsedColumn] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(header):
        label = "" if raw is None else str(raw).strip()
        if not label:
            label = f"col_{index + 1}"
            warnings.append(f"Blank header at column {index + 1} — stored as '{label}'")
        elif label in seen:
            seen[label] += 1
            warnings.append(
                f"Duplicate header '{label}' (column {index + 1}) — kept as a separate column"
            )
        else:
            seen[label] = 1
        columns.append(ParsedColumn(id=f"col_{index + 1}", label=label))
    return columns


def parse_tabular(path: Path) -> list[ParsedSheet]:
    """Parse a .csv or .xlsx into bounded sheets. Raises TabularParseError."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return [_parse_csv(path)]
    if suffix == ".xlsx":
        return _parse_xlsx(path)
    raise TabularParseError(f"Not a supported tabular type: {suffix}")


def _parse_csv(path: Path) -> ParsedSheet:
    warnings: list[str] = []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        sample = handle.read(CSV_SNIFF_BYTES)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(handle, dialect)
        try:
            header = next(reader)
        except StopIteration:
            return ParsedSheet(CSV_SHEET_NAME, 0, [], warnings=["CSV file is empty"])
        columns = _build_columns(header, warnings)
        rows: list[ParsedRow] = []
        row_number = 1  # header
        for record in reader:
            row_number += 1
            if row_number - 1 > MAX_ROWS_PER_SHEET:
                raise TabularParseError(f"CSV exceeds the {MAX_ROWS_PER_SHEET}-row limit")
            if len(record) > len(columns):
                warnings.append(
                    f"Row {row_number} has {len(record)} cells — extra cells were dropped"
                )
            cells = {
                col.id: _cell_value(record[i] if i < len(record) else None, warnings)
                for i, col in enumerate(columns)
            }
            rows.append(ParsedRow(row_number, cells))
    sheet = ParsedSheet(CSV_SHEET_NAME, 0, columns, rows, warnings)
    _infer_kinds(columns, rows)
    return sheet


def _parse_xlsx(path: Path) -> list[ParsedSheet]:
    # ZIP-bomb guard: bound decompressed bytes before openpyxl touches them.
    with zipfile.ZipFile(path) as archive:
        decompressed = sum(info.file_size for info in archive.infolist())
    if decompressed > MAX_XLSX_DECOMPRESSED_BYTES:
        raise TabularParseError(
            f"Workbook expands beyond the {MAX_XLSX_DECOMPRESSED_BYTES}-byte limit"
        )
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    if len(workbook.worksheets) > MAX_SHEETS:
        raise TabularParseError(
            f"Workbook exceeds the {MAX_SHEETS}-sheet limit ({len(workbook.worksheets)})"
        )
    sheets: list[ParsedSheet] = []
    for index, ws in enumerate(workbook.worksheets):
        warnings = [
            "Formula cells show their last-saved cached value — stale caches are not re-evaluated"
        ]
        if ws.sheet_state != "visible":
            warnings.append(f"Sheet '{ws.title}' is hidden in the workbook")
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            continue
        columns = _build_columns(list(header), warnings)
        rows: list[ParsedRow] = []
        row_number = 1  # header
        for record in rows_iter:
            row_number += 1
            if row_number - 1 > MAX_ROWS_PER_SHEET:
                raise TabularParseError(
                    f"Sheet '{ws.title}' exceeds the {MAX_ROWS_PER_SHEET}-row limit"
                )
            cells = {
                col.id: _cell_value(record[i] if i < len(record) else None, warnings)
                for i, col in enumerate(columns)
            }
            rows.append(ParsedRow(row_number, cells))
        sheet = ParsedSheet(
            ws.title,
            index,
            columns,
            rows,
            warnings,
            hidden=ws.sheet_state != "visible",
        )
        _infer_kinds(columns, rows)
        sheets.append(sheet)
    if not sheets:
        raise TabularParseError("Workbook contains no non-empty sheets")
    return sheets


def _col_letter(index: int) -> str:
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


async def persist_tabular(db: AsyncSession, document: Document, parsed: list[ParsedSheet]) -> None:
    """Atomically replace a document's sheet/row corpus (same transaction as
    the chunk write — a failed ingest never publishes partial tables)."""
    old_sheets = (
        (await db.execute(select(DocumentSheet.id).where(DocumentSheet.document_id == document.id)))
        .scalars()
        .all()
    )
    if old_sheets:
        await db.execute(delete(DocumentRow).where(DocumentRow.sheet_id.in_(old_sheets)))
        await db.execute(delete(DocumentSheet).where(DocumentSheet.id.in_(old_sheets)))
    for sheet in parsed:
        row = DocumentSheet(
            document_id=document.id,
            name=sheet.name,
            sheet_index=sheet.index,
            columns_json=json.dumps(
                [{"id": c.id, "label": c.label, "kind": c.kind} for c in sheet.columns],
                ensure_ascii=False,
            ),
            row_count=len(sheet.rows),
            warnings_json=json.dumps(sheet.warnings, ensure_ascii=False),
        )
        db.add(row)
        await db.flush()
        span = _col_letter(max(len(sheet.columns), 1))
        db.add_all(
            DocumentRow(
                sheet_id=row.id,
                row_number=r.row_number,
                cells_json=json.dumps(r.cells, ensure_ascii=False, default=str),
                coord=f"{sheet.name}!A{r.row_number}:{span}{r.row_number}",
            )
            for r in sheet.rows
        )
        await db.flush()


# --- Exact row queries ---

_OPERATORS = {"eq", "ne", "lt", "lte", "gt", "gte", "contains"}
_AGGREGATES = {"count", "sum", "min", "max"}


def _resolve_column(columns: list[dict], ref: str) -> dict:
    """Resolve a column by stable id or unique label — ambiguous refs error."""
    for col in columns:
        if col["id"] == ref:
            return col
    matches = [c for c in columns if c["label"] == ref]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise TabularParseError(f"Column label '{ref}' is ambiguous — use a stable id (col_N)")
    raise TabularParseError(f"Unknown column: '{ref}'")


def _coerce_pair(cell: Any, raw: Any) -> tuple[Any, Any] | None:
    """Coerce a (cell, filter) pair for comparison. Returns None = no match."""
    if cell is None:
        return None
    if isinstance(cell, bool) or isinstance(raw, bool):
        return (cell, raw) if isinstance(cell, type(raw)) else None
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        try:
            return cell, float(raw)
        except (TypeError, ValueError):
            return None
    return str(cell), str(raw)


def _matches(cells: dict[str, Any], column_id: str, op: str, raw: Any) -> bool:
    cell = cells.get(column_id)
    if op == "contains":
        if cell is None or raw is None:
            return False
        return str(raw).casefold() in str(cell).casefold()
    pair = _coerce_pair(cell, raw)
    if pair is None:
        return False
    left, right = pair
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    try:
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
    except TypeError:
        return False
    return False


async def query_rows(
    db: AsyncSession,
    document: Document,
    *,
    sheet_name: str | None = None,
    filters: list[dict] | None = None,
    order: str = "asc",
    after_row: int = 0,
    limit: int = 50,
    aggregates: list[dict] | None = None,
) -> dict:
    """Exact filtered/aggregated row query over the persisted corpus.

    Streams the full filtered set — ``matched_count`` and aggregates are
    exact or the call raises. Paging cursors are source row numbers.
    """
    sheet_q = select(DocumentSheet).where(DocumentSheet.document_id == document.id)
    if sheet_name:
        sheet_q = sheet_q.where(DocumentSheet.name == sheet_name)
    sheets = list((await db.execute(sheet_q.order_by(DocumentSheet.sheet_index))).scalars())
    if not sheets:
        return {"error": "No tabular sheets persisted for this document"}
    if sheet_name and len(sheets) != 1:
        return {"error": f"Sheet not found: '{sheet_name}'"}
    if len(sheets) > 1:
        return {"error": "Multiple sheets — specify 'sheet' by name"}

    sheet = sheets[0]
    columns = json.loads(sheet.columns_json or "[]")
    predicates: list[tuple[str, str, Any]] = []
    for spec in filters or []:
        op = spec.get("op")
        if op not in _OPERATORS:
            return {"error": f"Unsupported operator '{op}' — allowed: {sorted(_OPERATORS)}"}
        try:
            col = _resolve_column(columns, str(spec.get("column", "")))
        except TabularParseError as error:
            return {"error": str(error)}
        predicates.append((col["id"], op, spec.get("value")))

    aggs: list[tuple[str, str | None]] = []
    for spec in aggregates or []:
        op = spec.get("op")
        if op not in _AGGREGATES:
            return {"error": f"Unsupported aggregate '{op}' — allowed: {sorted(_AGGREGATES)}"}
        col_id = None
        if op != "count":
            try:
                col_id = _resolve_column(columns, str(spec.get("column", "")))["id"]
            except TabularParseError as error:
                return {"error": str(error)}
        aggs.append((op, col_id))

    ordering = DocumentRow.row_number.asc() if order != "desc" else DocumentRow.row_number.desc()
    if after_row and order == "desc":
        boundary = DocumentRow.row_number < after_row
    elif after_row:
        boundary = DocumentRow.row_number > after_row
    else:
        boundary = DocumentRow.id.isnot(None)
    stream = await db.stream(
        select(DocumentRow).where(DocumentRow.sheet_id == sheet.id, boundary).order_by(ordering)
    )
    matched = 0
    page: list[DocumentRow] = []
    agg_values: list[float | None] = [None] * len(aggs)
    async for record in stream.scalars():
        cells = json.loads(record.cells_json or "{}")
        if not all(_matches(cells, cid, op, val) for cid, op, val in predicates):
            continue
        matched += 1
        if len(page) < limit:
            page.append(record)
        for i, (op, cid) in enumerate(aggs):
            if op == "count":
                agg_values[i] = (agg_values[i] or 0) + 1
                continue
            value = cells.get(cid)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if agg_values[i] is None:
                agg_values[i] = value
            elif op == "sum":
                agg_values[i] += value
            elif op == "min":
                agg_values[i] = min(agg_values[i], value)
            elif op == "max":
                agg_values[i] = max(agg_values[i], value)

    col_by_id = {c["id"]: c for c in columns}
    items = [
        {
            "row_number": r.row_number,
            "coord": r.coord,
            "cells": json.loads(r.cells_json or "{}"),
        }
        for r in page
    ]
    return {
        "document_id": document.id,
        "sheet": sheet.name,
        "columns": columns,
        "matched_count": matched,
        "aggregates": [
            {
                "op": op,
                "column": col_by_id[cid]["label"] if cid else None,
                "value": agg_values[i],
            }
            for i, (op, cid) in enumerate(aggs)
        ],
        "items": items,
        # Cursor resumes after the last *returned* row — matched_count scans
        # the whole set, but paging continues from the page boundary.
        "next_cursor": str(page[-1].row_number) if matched > len(page) else None,
        "truncated": matched > len(page),
    }
