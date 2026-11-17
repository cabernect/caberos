"""Authenticated revision-bound presentation exports."""

import asyncio
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.operator import Operator

router = APIRouter(prefix="/api/agents", tags=["deck-exports"])


async def export_snapshot(
    agent_id: str,
    expected_sha256: str,
    path: str = "",
    artifact_id: str | None = None,
    revision_id: str | None = None,
    session_id: str | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    from ..artifacts.deck_spec import normalize
    from .agent_files import _resolve_source, _workspace_root

    root = await _workspace_root(db, agent_id, session_id)
    source = await _resolve_source(db, root, agent_id, path, artifact_id, revision_id)
    sha = hashlib.sha256(source.data).hexdigest()
    if sha != expected_sha256:
        raise HTTPException(409, "File changed; refresh the preview before exporting")
    if not source.name.lower().endswith(".deck.json"):
        raise HTTPException(400, "Not a presentation source")
    try:
        raw = json.loads(source.data)
        spec = {**normalize(raw), "assets": raw.get("assets", [])}
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return spec, sha, revision_id, source.name[: -len(".deck.json")]


@router.get("/{agent_id}/workspace/deck-export-plan")
async def deck_export_plan(snapshot: tuple = Depends(export_snapshot)):
    from ..artifacts import deck_exports

    try:
        return await asyncio.to_thread(deck_exports.plan, snapshot[0], snapshot[1])
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{agent_id}/workspace/deck-export.pdf")
async def deck_export_pdf(snapshot: tuple = Depends(export_snapshot)):
    from urllib.parse import quote

    from ..artifacts import deck_exports

    spec, sha, revision_id, stem = snapshot
    try:
        content = await deck_exports.pdf(spec, source_sha256=sha, revision_id=revision_id)
    except (ValueError, OSError, TimeoutError) as exc:
        raise HTTPException(422, str(exc) or "Presentation rendering timed out") from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(stem + '.pdf', safe='')}",
            "Cache-Control": "no-store",
            "X-Source-SHA256": sha,
            "X-Export-Mode": "react-fixed-pages",
        },
    )
