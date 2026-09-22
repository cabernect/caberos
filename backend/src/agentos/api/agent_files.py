"""Agent files API — MEMORY.md, skills, workspace browser, memory management (D34, D37)."""

import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..config import settings
from ..db import get_db
from ..memory import recall, triples
from ..models.operator import Operator
from ..skills.loader import _load_skill_from_dir
from ..skills.loader import list_skills as load_available_skills

router = APIRouter(prefix="/api/agents", tags=["agent-files"])
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _safe_component(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return value


def _child_path(parent: Path, name: str) -> Path:
    """Resolve ``name`` inside ``parent``, verifying it can't escape.

    ``name`` has already passed ``_safe_component`` (no separators), but the
    resolved-path containment check keeps the guarantee CodeQL-visible.
    """
    from ..sandbox.workspace import resolve_within

    return resolve_within(parent, name)


def _agent_home(agent_id: str) -> Path:
    """Get the agent's home directory."""
    agent_id = _safe_component(agent_id, "agent id")
    home = settings.agent_home_root / agent_id
    home.mkdir(parents=True, exist_ok=True)
    return home


def _memory_path(agent_id: str) -> Path:
    """Get the path to the agent's MEMORY.md file."""
    return _agent_home(agent_id) / "MEMORY.md"


def _skills_dir(agent_id: str) -> Path:
    """Get the agent's workspace skills directory."""
    from ..sandbox.workspace import WorkspaceManager

    agent_id = _safe_component(agent_id, "agent id")
    skills = Path(WorkspaceManager().create_workspace(agent_id)) / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    return skills


def _workspace_path(agent_id: str) -> Path:
    """Get the agent's workspace path."""
    from ..sandbox.workspace import WorkspaceManager

    wm = WorkspaceManager()
    agent_id = _safe_component(agent_id, "agent id")
    return Path(wm.create_workspace(agent_id))


# --- MEMORY.md ---


@router.get("/{agent_id}/memory")
async def get_memory(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the agent's MEMORY.md content."""
    path = _memory_path(agent_id)
    if not path.exists():
        return {"content": "", "exists": False}
    content = path.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "exists": True}


class UpdateMemoryRequest(BaseModel):
    content: str


@router.put("/{agent_id}/memory")
async def update_memory(
    agent_id: str,
    req: UpdateMemoryRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update the agent's MEMORY.md content."""
    path = _memory_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(req.content, encoding="utf-8")
    return {"ok": True, "bytes": len(req.content)}


# --- Skills ---


@router.get("/{agent_id}/skills")
async def list_skills(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all skills for an agent."""
    skills_dir = _skills_dir(agent_id)
    skills = []
    if skills_dir.exists():
        for entry in sorted(skills_dir.iterdir()):
            if entry.is_dir():
                skill = _load_skill_from_dir(entry, "agent")
                if skill is None:
                    continue
                skills.append(
                    {
                        "name": skill.name,
                        "type": "directory",
                        "description": skill.description,
                    }
                )
            elif entry.is_file() and entry.suffix in (".md", ".yaml", ".yml"):
                skills.append(
                    {
                        "name": entry.name,
                        "type": "file",
                        "description": "",
                    }
                )
    return skills


@router.get("/{agent_id}/available-skills")
async def list_available_skills(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List system and agent skills available to the active agent."""
    return load_available_skills(agent_id)


class CreateSkillRequest(BaseModel):
    name: str
    content: str = ""


@router.post("/{agent_id}/skills")
async def create_skill(
    agent_id: str,
    req: CreateSkillRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new skill (as a directory with SKILL.md)."""
    skills_dir = _skills_dir(agent_id)
    skill_name = _safe_component(req.name, "skill name")
    skill_path = _child_path(skills_dir, skill_name)
    if skill_path.exists():
        raise HTTPException(status_code=409, detail="Skill already exists")
    skill_path.mkdir(parents=True)
    skill_md = skill_path / "SKILL.md"
    content = req.content or f"# {skill_name}\n\nDescribe this skill here.\n"
    skill_md.write_text(content, encoding="utf-8")
    return {"name": skill_name, "path": str(skill_path)}


@router.delete("/{agent_id}/skills/{skill_name}")
async def delete_skill(
    agent_id: str,
    skill_name: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a skill."""
    skills_dir = _skills_dir(agent_id)
    skill_name = _safe_component(skill_name, "skill name")
    skill_path = _child_path(skills_dir, skill_name)
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill_path.is_dir():
        import shutil

        shutil.rmtree(skill_path)
    else:
        skill_path.unlink()
    return {"ok": True}


# --- Workspace browser ---


@router.get("/{agent_id}/workspace")
async def list_workspace(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    path: str = "",
) -> dict:
    """List files in the agent's workspace."""
    from ..sandbox.workspace import WorkspaceManager

    ws = _workspace_path(agent_id)
    try:
        target = Path(WorkspaceManager().validate_path(str(ws), path or "."))
    except ValueError as error:
        raise HTTPException(status_code=403, detail="Path outside workspace") from error

    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    if target.is_file():
        content = target.read_text(encoding="utf-8", errors="replace")
        return {
            "type": "file",
            "path": path,
            "content": content,
            "size": target.stat().st_size,
        }

    entries = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name)):
        if entry.name.startswith("."):
            continue
        entries.append(
            {
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
            }
        )
    return {
        "type": "dir",
        "path": path,
        "entries": entries,
    }


@router.delete("/{agent_id}/workspace")
async def delete_workspace_entry(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    path: str = "",
) -> dict:
    """Delete a file or directory in the agent's workspace.

    Tracked artifact files refuse deletion — their revisions would point at
    a missing file. Directories delete recursively, but refuse when any
    tracked artifact lives inside. Attachment files may be deleted; chat
    cards referencing them degrade to a missing-file state.
    """
    import shutil

    from sqlalchemy import select

    from ..models.artifact import Artifact
    from ..sandbox.workspace import WorkspaceManager

    rel = (path or "").strip().strip("/")
    if not rel:
        raise HTTPException(status_code=400, detail="path is required")

    ws = _workspace_path(agent_id)
    # Containment applies to the parent directory (fully resolved — '..'
    # and symlinked dirs still can't escape), never to the leaf: a symlink
    # leaf is a workspace entry and must be unlinked without being followed.
    norm = os.path.normpath(rel)
    if os.path.isabs(norm) or norm == "." or norm.startswith(".."):
        raise HTTPException(status_code=403, detail="Path outside workspace")
    try:
        parent = Path(WorkspaceManager().validate_path(str(ws), os.path.dirname(norm) or "."))
    except ValueError as error:
        raise HTTPException(status_code=403, detail="Path outside workspace") from error
    target = parent / os.path.basename(norm)

    if target == ws:
        raise HTTPException(status_code=400, detail="Cannot delete the workspace root")
    if not target.exists() and not target.is_symlink():
        raise HTTPException(status_code=404, detail="Path not found")

    tracked = (
        (
            await db.execute(
                select(Artifact.current_path).where(
                    Artifact.workspace_id == agent_id,
                    (Artifact.current_path == norm) | (Artifact.current_path.like(f"{norm}/%")),
                )
            )
        )
        .scalars()
        .all()
    )
    if tracked:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{norm}' is tracked as an artifact ({len(tracked)} file(s)). "
                "Artifact history would point at a missing file — remove it "
                "from artifact tracking first."
            ),
        )

    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)
    return {"deleted": True, "path": rel}


# --- File previews (W3) ---
#
# One endpoint family serves both ordinary workspace files and exact
# artifact revisions: pass `path` for the current file, or
# `artifact_id`+`revision_id` for managed revision bytes. The response
# embeds artifact metadata so the panel can split tracked vs ordinary
# actions and flag newer revisions.


async def _resolve_source(
    db: AsyncSession,
    ws: Path,
    agent_id: str,
    path: str,
    artifact_id: str | None,
    revision_id: str | None,
) -> tuple[bytes, str, object | None, Path | None]:
    """Resolve preview bytes + owning artifact.

    Returns (data, name, artifact, file_path). file_path is set only when
    the bytes are the live workspace file (raw endpoint streams it without
    a memory copy); revision bytes always load from managed storage.
    """
    from ..artifacts import service as artifact_service
    from ..artifacts.service import ArtifactError
    from ..sandbox.workspace import WorkspaceManager

    if artifact_id or revision_id:
        try:
            if artifact_id:
                artifact = await artifact_service._get(db, artifact_id)
            else:
                from ..models.artifact import ArtifactRevision

                rev = await db.get(ArtifactRevision, revision_id)
                if rev is None:
                    raise ArtifactError(f"unknown revision: {revision_id}")
                artifact = await artifact_service._get(db, rev.artifact_id)
        except ArtifactError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        if artifact.workspace_id != agent_id:
            raise HTTPException(status_code=404, detail="Artifact not found")
        if revision_id:
            from ..models.artifact import ArtifactRevision

            rev = await db.get(ArtifactRevision, revision_id)
            if rev is None or rev.artifact_id != artifact.id:
                raise HTTPException(status_code=404, detail="Revision not found")
            data = await artifact_service.revision_bytes(db, revision_id)
        else:
            target = _child_path(ws, artifact.current_path)
            if not target.exists() or not target.is_file():
                raise HTTPException(status_code=404, detail="File not found")
            data = target.read_bytes()
        return data, Path(artifact.current_path).name, artifact, None

    try:
        target = Path(WorkspaceManager().validate_path(str(ws), path))
    except ValueError as error:
        raise HTTPException(status_code=403, detail="Path outside workspace") from error
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    artifact = await artifact_service.get_by_path(db, agent_id, path)
    return target.read_bytes(), target.name, artifact, target


async def _artifact_meta(db: AsyncSession, artifact, revision_id: str | None) -> dict:
    """Tracked-file metadata for the panel: revision position + newer flag."""
    from sqlalchemy import func, select

    from ..models.artifact import ArtifactRevision

    count = (
        await db.execute(
            select(func.count(ArtifactRevision.id)).where(
                ArtifactRevision.artifact_id == artifact.id
            )
        )
    ).scalar_one()
    current = (
        await db.get(ArtifactRevision, artifact.current_revision_id)
        if artifact.current_revision_id
        else None
    )
    meta = {
        "id": artifact.id,
        "format": artifact.format,
        "tracking_status": artifact.tracking_status,
        "current_path": artifact.current_path,
        "current_revision_id": artifact.current_revision_id,
        "current_revision_number": current.revision_number if current else None,
        "revision_count": count,
        "viewing_revision_id": None,
        "viewing_revision_number": None,
        "newer_exists": False,
    }
    if revision_id:
        viewing = await db.get(ArtifactRevision, revision_id)
        if viewing is not None:
            meta["viewing_revision_id"] = viewing.id
            meta["viewing_revision_number"] = viewing.revision_number
            meta["newer_exists"] = bool(
                current and viewing.revision_number < current.revision_number
            )
    return meta


@router.get("/{agent_id}/workspace/preview")
async def preview_workspace_file(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    path: str = "",
    artifact_id: str | None = None,
    revision_id: str | None = None,
) -> dict:
    """Bounded preview payload for a workspace file or artifact revision."""
    from .. import previews

    ws = _workspace_path(agent_id)
    data, name, artifact, _ = await _resolve_source(
        db, ws, agent_id, path, artifact_id, revision_id
    )
    payload = previews.preview_bytes(data, name)
    payload["artifact"] = await _artifact_meta(db, artifact, revision_id) if artifact else None
    if artifact and not artifact_id and not revision_id:
        payload["path"] = artifact.current_path
    else:
        payload["path"] = path
    # Operator-only: the desktop shell uses the absolute path for
    # open/reveal-in-finder. Revision previews point at the live file.
    live_path = artifact.current_path if artifact else path
    payload["absolute_path"] = str(ws / live_path)
    return payload


@router.get("/{agent_id}/workspace/raw")
async def raw_workspace_file(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    path: str = "",
    artifact_id: str | None = None,
    revision_id: str | None = None,
):
    """Raw bytes with the correct Content-Type — images/media/downloads
    stream through object URLs on the client (Bearer auth blocks <img src>)."""
    from fastapi.responses import FileResponse, Response

    from .. import previews

    ws = _workspace_path(agent_id)
    data, name, _, file_path = await _resolve_source(
        db, ws, agent_id, path, artifact_id, revision_id
    )
    mime = previews.media_type(name)
    if file_path is not None:
        return FileResponse(file_path, media_type=mime, filename=name)
    return Response(content=data, media_type=mime)


@router.get("/{agent_id}/workspace/pdf-page")
async def pdf_page(
    agent_id: str,
    page: int,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    path: str = "",
    artifact_id: str | None = None,
    revision_id: str | None = None,
):
    """One PDF page rendered to PNG — the paginated viewer's image source."""
    from fastapi.responses import Response

    from .. import previews

    ws = _workspace_path(agent_id)
    data, name, _, _ = await _resolve_source(db, ws, agent_id, path, artifact_id, revision_id)
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Not a PDF")
    try:
        png = previews.render_pdf_page(data, page)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"pdf render failed: {e}") from e
    return Response(content=png, media_type="image/png")


# --- Artifact actions (W3 panel) ---
#
# Operator-side artifact operations — the preview panel's History/restore/
# Track actions call these directly; agent-side edits still go through the
# artifact_* capabilities. Restore stays append-only: it writes a new
# revision, never rewinds history.


@router.get("/{agent_id}/artifacts/{artifact_id}/revisions")
async def list_artifact_revisions(
    agent_id: str,
    artifact_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revision list for the History dropdown — newest first."""
    from ..artifacts import service as artifact_service
    from ..artifacts.service import ArtifactError

    try:
        artifact = await artifact_service._get(db, artifact_id)
    except ArtifactError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if artifact.workspace_id != agent_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"revisions": await artifact_service.history(db, artifact_id)}


class RestoreRevisionRequest(BaseModel):
    revision_id: str


@router.post("/{agent_id}/artifacts/{artifact_id}/restore")
async def restore_artifact_revision(
    agent_id: str,
    artifact_id: str,
    req: RestoreRevisionRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Operator-initiated restore — old bytes back as a new revision."""
    from ..artifacts import service as artifact_service
    from ..artifacts.service import ArtifactError

    ws = _workspace_path(agent_id)
    try:
        artifact = await artifact_service._get(db, artifact_id)
        if artifact.workspace_id != agent_id:
            raise ArtifactError("Artifact not found")
        rev = await artifact_service.restore(
            db,
            artifact_id,
            workspace_path=ws,
            revision_id=req.revision_id,
            created_by=f"operator:{operator.id}",
        )
    except ArtifactError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"revision_id": rev.id, "revision_number": rev.revision_number}


class AdoptRequest(BaseModel):
    path: str


@router.post("/{agent_id}/artifacts/adopt")
async def adopt_workspace_file(
    agent_id: str,
    req: AdoptRequest,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Track history for an ordinary workspace file — its current bytes
    become revision 1."""
    from ..artifacts import service as artifact_service
    from ..artifacts.service import ArtifactError

    ws = _workspace_path(agent_id)
    try:
        artifact, rev = await artifact_service.adopt(
            db,
            workspace_id=agent_id,
            workspace_path=ws,
            rel_path=req.path,
            created_by=f"operator:{operator.id}",
            change_summary="tracked via preview panel",
        )
    except ArtifactError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "artifact_id": artifact.id,
        "revision_id": rev.id,
        "path": artifact.current_path,
    }


# --- Composer attachment previews (W3c) ---
#
# The tray renders a card before the message sends — these endpoints give
# it bounded previews of in-flight files and URL metadata without
# persisting anything. Attachment bytes only reach the workspace when the
# message actually sends.


@router.post("/{agent_id}/attachments/preview")
async def preview_attachment_upload(
    agent_id: str,
    file: UploadFile,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Ephemeral preview of an in-flight attachment — same bounded renderers
    as workspace previews, nothing persisted. PDF payloads carry a
    first-page PNG (`thumb_png`, base64) for the card thumbnail."""
    import base64

    from .. import previews

    _safe_component(agent_id, "agent id")
    data = await file.read(previews.PREVIEW_MAX_BYTES + 1)
    payload = previews.preview_bytes(data, file.filename or "attachment")
    payload["artifact"] = None
    payload["path"] = ""
    if payload["kind"] == "pdf" and not payload.get("too_large"):
        try:
            png = previews.render_pdf_page(data, 1)
            payload["thumb_png"] = base64.b64encode(png).decode("ascii")
        except Exception:
            pass  # thumbnails are best-effort — the card falls back to an icon
    return payload


@router.get("/{agent_id}/attachments/url-preview")
async def url_attachment_preview(
    agent_id: str,
    url: str,
    operator: Operator = Depends(require_operator),
) -> dict:
    """Domain + <title> for a URL attachment card. Bounded: http(s) only,
    5s ceiling, first 256KB of the body, 200-char title."""
    import re as _re

    import httpx

    _safe_component(agent_id, "agent id")
    if not _re.match(r"^https?://", url, _re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Only http(s) URLs can be previewed")
    try:
        from urllib.parse import urlparse

        domain = urlparse(url).hostname or ""
    except Exception:
        domain = ""
    result: dict = {"url": url, "domain": domain, "title": None}
    try:
        from ..ssl_utils import SSL_CERT_PATH

        async with httpx.AsyncClient(
            timeout=5.0,
            follow_redirects=True,
            verify=SSL_CERT_PATH,
            headers={"User-Agent": "CaberOS-UrlPreview/1.0"},
        ) as client:
            resp = await client.get(url)
            body = resp.content[: 256 * 1024].decode("utf-8", errors="replace")
            m = _re.search(r"<title[^>]*>(.*?)</title>", body, _re.IGNORECASE | _re.DOTALL)
            if m:
                title = _re.sub(r"\s+", " ", m.group(1)).strip()[:200]
                if title:
                    result["title"] = title
    except Exception:
        pass  # preview metadata is best-effort — domain label still works
    return result


@router.get("/{agent_id}/artifacts/{artifact_id}/compare")
async def compare_artifact_revisions(
    agent_id: str,
    artifact_id: str,
    from_revision: str,
    to_revision: str | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Unified diff between two revisions — text decodable bytes only.

    Binary formats answer honestly: no fabricated diff, just the
    size/hash delta so the panel can say "changed" without pretending
    to show what."""
    import difflib

    from ..artifacts import service as artifact_service
    from ..artifacts.service import ArtifactError

    try:
        artifact = await artifact_service._get(db, artifact_id)
        if artifact.workspace_id != agent_id:
            raise ArtifactError("Artifact not found")
        target_id = to_revision or artifact.current_revision_id
        if not target_id:
            raise ArtifactError("Artifact has no current revision")
        old = await artifact_service.revision_bytes(db, from_revision)
        new = await artifact_service.revision_bytes(db, target_id)
    except ArtifactError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    from ..models.artifact import ArtifactRevision

    frm = await db.get(ArtifactRevision, from_revision)
    to = await db.get(ArtifactRevision, target_id)
    meta = {
        "from_revision_number": frm.revision_number if frm else None,
        "to_revision_number": to.revision_number if to else None,
        "from_bytes": len(old),
        "to_bytes": len(new),
        "identical": old == new,
    }

    try:
        old_text = old.decode("utf-8")
        new_text = new.decode("utf-8")
    except UnicodeDecodeError:
        return {"comparable": False, "reason": "binary", **meta}

    diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"r{meta['from_revision_number']}/{artifact.current_path}",
            tofile=f"r{meta['to_revision_number']}/{artifact.current_path}",
        )
    )
    return {"comparable": True, "diff": diff, **meta}


# --- Memory management (triples + recall entries) ---


@router.get("/{agent_id}/memory/triples")
async def list_triples(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all knowledge graph triples for an agent."""
    return await triples.list_triples(db, agent_id)


@router.delete("/{agent_id}/memory/triples")
async def clear_triples(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
    contact_id: str | None = None,
) -> dict:
    """Clear knowledge graph triples for an agent. Optional contact_id to scope."""
    count = await triples.clear_triples(db, agent_id, contact_id)
    await db.commit()
    return {"deleted": count}


@router.delete("/{agent_id}/contacts/{contact_id}/memory")
async def clear_contact_memory(
    agent_id: str,
    contact_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Clear all per-contact memory (triples + recall entries) for a specific contact."""
    triple_count = await triples.clear_triples(db, agent_id, contact_id)
    entry_count = await recall.clear_entries(db, agent_id, contact_id)
    await db.commit()
    return {"deleted_triples": triple_count, "deleted_entries": entry_count}
