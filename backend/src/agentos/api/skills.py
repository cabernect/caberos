"""Skills Studio API (W6) — scoped library, drafts, lifecycle, imports.

The DB is the authority for visibility: Skill rows carry scope
(built-in | global | agent-local), status (draft | published | disabled |
archived), availability (all | selected) + assignments, and immutable
SkillRevision snapshots. Content bytes live on disk:

    skills/                                 built-ins (shipped, read-only)
    data/skills-store/{skill_id}/rev-{n}/   published revisions
    data/skills-drafts/{name}/              operator import drafts
    workspace/{agent}/skills/{name}/        agent-local live copies
    workspace/{agent}/skill-drafts/{name}/  builder drafts

Precedence on name collision: agent-local > global > built-in.
Imports (ZIP upload + repo URL) always land as drafts — nothing remote or
unreviewed goes live without an explicit publish.
"""

import io
import json
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import previews
from ..auth import require_operator
from ..capabilities.registry import registry as cap_registry
from ..db import get_db
from ..models.agent import Agent
from ..models.contact import Contact
from ..models.operator import Operator
from ..models.session import Session
from ..models.skill import Skill, SkillAssignment, SkillRevision
from ..skills import importer, service, validate
from ..skills.importer import ImportRejected
from ..skills.loader import _load_skill_from_dir
from ..skills.resolution import resolve_effective_skills
from ..skills.service import SkillError

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------


def _content_dir(
    skill: Skill,
    revision: SkillRevision | None,
    explicit_revision: bool = False,
) -> Path | None:
    """The dir that represents the skill's current inspectable content.

    An explicit ?revision= always serves that revision's bytes — even for
    agent-local skills whose live working copy is the default view.
    """
    if skill.status == "draft" and not explicit_revision:
        path = service.draft_dir(skill)
        return path if path.is_dir() else None
    if skill.scope == "agent-local" and not explicit_revision:
        live = service.live_local_dir(skill)
        if live.is_dir():
            return live
    if revision is not None:
        path = service.revision_abs_path(skill, revision)
        return path if path.is_dir() else None
    return None


async def _current_revision(db: AsyncSession, skill: Skill) -> SkillRevision | None:
    if skill.current_revision_id is None:
        return None
    return await db.scalar(
        select(SkillRevision).where(SkillRevision.id == skill.current_revision_id)
    )


async def _agent_names(db: AsyncSession) -> dict[str, str]:
    rows = (await db.execute(select(Agent.id, Agent.name))).all()
    return {r.id: r.name for r in rows}


async def _skill_row(db: AsyncSession, skill_id: str) -> Skill:
    try:
        return await service.get_skill(db, skill_id)
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e


async def _list_row(db: AsyncSession, skill: Skill, agent_names: dict[str, str]) -> dict:
    revision = await _current_revision(db, skill)
    content_dir = _content_dir(skill, revision)
    loaded = _load_skill_from_dir(content_dir, skill.scope) if content_dir else None
    resource_count = (
        sum(1 for f in content_dir.rglob("*") if f.is_file() and f.name != "SKILL.md")
        if content_dir
        else 0
    )
    assigned = [
        a.agent_id
        for a in (
            await db.execute(select(SkillAssignment).where(SkillAssignment.skill_id == skill.id))
        ).scalars()
    ]
    return {
        "id": skill.id,
        "name": skill.name,
        "description": loaded.description if loaded else "",
        "scope": skill.scope,
        "status": skill.status,
        "owner_agent_id": skill.owner_agent_id,
        "owner_name": agent_names.get(skill.owner_agent_id or ""),
        "availability": skill.availability,
        "assigned_agent_ids": assigned,
        "assigned_names": [agent_names.get(a, a) for a in assigned],
        "current_revision": revision.revision_number if revision else None,
        "resource_count": resource_count,
        "builder_session_id": skill.builder_session_id,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


def _skill_dir_for_request(
    skill: Skill, revision: SkillRevision | None, explicit_revision: bool = False
) -> Path:
    """Resolve the on-disk dir for preview/raw/files endpoints."""
    path = _content_dir(skill, revision, explicit_revision)
    if path is None or not path.is_dir():
        raise HTTPException(status_code=404, detail="skill content not found on disk")
    return path


def _resolve_resource(skill_dir: Path, path: str) -> Path:
    target = (skill_dir / path).resolve()
    try:
        target.relative_to(skill_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside skill directory")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="resource not found")
    return target


async def _revision_for_query(
    db: AsyncSession, skill: Skill, revision_number: int | None
) -> SkillRevision | None:
    if revision_number is None:
        return await _current_revision(db, skill)
    rev = await db.scalar(
        select(SkillRevision).where(
            SkillRevision.skill_id == skill.id,
            SkillRevision.revision_number == revision_number,
        )
    )
    if rev is None:
        raise HTTPException(status_code=404, detail="revision not found")
    return rev


def _known_capabilities() -> set[str]:
    names = set(cap_registry.list_names())
    return names


async def _granted_capabilities(db: AsyncSession, skill: Skill) -> set[str] | None:
    """The union of capability names granted to the owner/assigned agents."""
    from ..agent_service import get_active_config

    agent_ids: list[str] = []
    if skill.owner_agent_id:
        agent_ids.append(skill.owner_agent_id)
    if skill.scope == "global" and skill.availability == "selected":
        agent_ids.extend(
            (
                await db.execute(
                    select(SkillAssignment.agent_id).where(SkillAssignment.skill_id == skill.id)
                )
            ).scalars()
        )
    if not agent_ids:
        return None
    granted: set[str] = set()
    for aid in agent_ids:
        config = await get_active_config(db, aid)
        if config is None:
            continue
        if config.capabilities is None:
            return None  # no ceiling — this agent grants everything
        granted.update(g.name for g in config.capabilities)
    return granted


async def _validate_now(db: AsyncSession, skill: Skill) -> dict:
    revision = await _current_revision(db, skill)
    content_dir = _content_dir(skill, revision)
    if content_dir is None:
        return {"errors": ["no content on disk"], "warnings": [], "stats": {}}
    return validate.validate_skill_dir(
        content_dir,
        known_capabilities=_known_capabilities(),
        granted_capabilities=await _granted_capabilities(db, skill),
        expected_name=skill.name,
    )


# ---------------------------------------------------------------------------
# List + effective menu
# ---------------------------------------------------------------------------


@router.get("")
async def list_skills(
    view: str = "all",
    agent_id: str | None = None,
    q: str | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Scoped skill listing.

    view = all | built-in | global | agent-local | drafts | archived.
    Drafts and archived rows are only visible in their own views.
    """
    stmt = select(Skill).order_by(Skill.name)
    if view == "built-in":
        stmt = stmt.where(Skill.scope == "built-in")
    elif view == "global":
        stmt = stmt.where(Skill.scope == "global")
    elif view == "agent-local":
        stmt = stmt.where(Skill.scope == "agent-local", Skill.status != "draft")
    elif view == "drafts":
        stmt = stmt.where(Skill.status == "draft")
    elif view == "archived":
        stmt = stmt.where(Skill.status == "archived")
    elif view != "all":
        raise HTTPException(status_code=400, detail=f"unknown view '{view}'")

    if view not in ("drafts", "archived"):
        stmt = stmt.where(Skill.status.not_in(["draft", "archived"]))
    if agent_id and view == "agent-local":
        stmt = stmt.where(Skill.owner_agent_id == agent_id)
    if q:
        stmt = stmt.where(Skill.name.contains(q.lower()))

    rows = (await db.execute(stmt)).scalars().all()
    agent_names = await _agent_names(db)
    skills = [await _list_row(db, s, agent_names) for s in rows]
    return {"skills": skills, "count": len(skills)}


@router.get("/effective")
async def effective_skills(
    agent_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The resolved menu for one agent — what it would actually see now."""
    resolved = await resolve_effective_skills(db, agent_id)
    return {
        "agent_id": agent_id,
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "scope": s.scope,
                "skill_id": s.skill_id,
                "revision_id": s.revision_id,
                "pin": s.pin,
                "shadows": s.shadows,
            }
            for s in resolved
        ],
    }


# ---------------------------------------------------------------------------
# Drafts + builder sessions
# ---------------------------------------------------------------------------


class DraftCreate(BaseModel):
    name: str
    agent_id: str | None = None
    launch_session: bool = False


async def _dashboard_session(
    db: AsyncSession, agent_id: str, operator: Operator, title: str
) -> Session:
    """Create a dashboard_chat session for the builder flow."""
    contact = (
        await db.execute(
            select(Contact).where(
                Contact.channel == "dashboard_chat",
                Contact.bot_id == agent_id,
                Contact.external_user_id == operator.id,
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        contact = Contact(
            id=str(uuid.uuid4()),
            channel="dashboard_chat",
            bot_id=agent_id,
            external_user_id=operator.id,
            display_name=operator.id,
        )
        db.add(contact)
        await db.flush()
    session = Session(
        id=str(uuid.uuid4()),
        contact_id=contact.id,
        agent_id=agent_id,
        status="active",
        title=title,
    )
    db.add(session)
    await db.flush()
    return session


@router.post("/drafts")
async def create_draft(
    body: DraftCreate,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a draft. With agent_id + launch_session this is the builder
    flow: a dashboard session is created and linked — the next run on it
    force-loads skill-creator and writes files under skill-drafts/."""
    session_id = None
    if body.launch_session:
        if not body.agent_id:
            raise HTTPException(status_code=400, detail="launch_session requires agent_id")
        session = await _dashboard_session(db, body.agent_id, operator, f"Skill draft: {body.name}")
        session_id = session.id
    try:
        skill = await service.create_draft(
            db,
            name=body.name,
            owner_agent_id=body.agent_id,
            builder_session_id=session_id,
        )
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {
        "id": skill.id,
        "name": skill.name,
        "status": skill.status,
        "session_id": session_id,
    }


@router.delete("/drafts/{skill_id}")
async def delete_draft(
    skill_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    skill = await _skill_row(db, skill_id)
    try:
        await service.delete_draft(db, skill)
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {"deleted": True, "id": skill_id}


# ---------------------------------------------------------------------------
# Imports — ZIP upload + repo URL, both draft-only
# ---------------------------------------------------------------------------


async def _import_archive(
    db: AsyncSession,
    archive: bytes,
    paths: list[str] | None,
    owner_agent_id: str | None,
) -> dict:
    """Shared import flow: detect skill dirs → pick-list or import selected."""
    candidates = importer.skill_candidates(archive)
    if not candidates:
        raise HTTPException(status_code=400, detail="no SKILL.md found in the archive")

    if paths is None:
        if len(candidates) == 1:
            paths = [candidates[0]["path"]]
        else:
            # Multi-skill archive — the operator picks.
            return {"candidates": candidates, "imported": []}

    selected = [c for c in candidates if c["path"] in set(paths)]
    if not selected:
        raise HTTPException(status_code=400, detail="no selected paths match the archive")

    imported: list[dict] = []
    errors: list[str] = []
    for cand in selected:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                importer.extract_skill_subtree(archive, cand["path"], tmpdir)
                name = cand["name"] or cand["dir_name"]
                skill = await service.import_draft(
                    db, name=name, source_dir=tmpdir, owner_agent_id=owner_agent_id
                )
            imported.append({"id": skill.id, "name": skill.name})
        except (ImportRejected, SkillError) as e:
            errors.append(f"{cand['path'] or cand['name']}: {e}")
    await db.commit()
    return {"imported": imported, "errors": errors, "candidates": candidates}


@router.post("/import")
async def import_zip(
    file: UploadFile = File(...),
    owner_agent_id: str | None = Form(None),
    paths: str | None = Form(None),
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import skill(s) from a zip upload. All imports land as drafts."""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="file must be a .zip")
    archive = await file.read()
    if len(archive) > importer.MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=400, detail="archive exceeds the 50 MB cap")
    selected = json.loads(paths) if paths else None
    try:
        return await _import_archive(db, archive, selected, owner_agent_id)
    except ImportRejected as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class ImportUrlBody(BaseModel):
    url: str
    owner_agent_id: str | None = None
    paths: list[str] | None = None


@router.post("/import-url")
async def import_url(
    body: ImportUrlBody,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Install from a git-host URL: fetches the archive over HTTP (no git
    exec), detects every SKILL.md dir, and imports the selection as drafts."""
    try:
        archive = await importer.fetch_archive(body.url)
        return await _import_archive(db, archive, body.paths, body.owner_agent_id)
    except ImportRejected as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Detail + tabs (overview/instructions/resources/history/usage)
# ---------------------------------------------------------------------------


@router.get("/{skill_id}")
async def skill_detail(
    skill_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    skill = await _skill_row(db, skill_id)
    agent_names = await _agent_names(db)
    row = await _list_row(db, skill, agent_names)

    revision = await _current_revision(db, skill)
    content_dir = _content_dir(skill, revision)
    loaded = _load_skill_from_dir(content_dir, skill.scope) if content_dir else None

    revisions = (
        (
            await db.execute(
                select(SkillRevision)
                .where(SkillRevision.skill_id == skill.id)
                .order_by(SkillRevision.revision_number.desc())
            )
        )
        .scalars()
        .all()
    )

    # Usage: runs whose manifest pins one of this skill's revisions.
    from ..models.execution_manifest import ExecutionManifest
    from ..models.run import Run

    usage: list[dict] = []
    rev_ids = {r.id for r in revisions}
    if rev_ids:
        manifests = (
            (
                await db.execute(
                    select(ExecutionManifest)
                    .order_by(ExecutionManifest.created_at.desc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        run_ids = []
        for m in manifests:
            try:
                pins = json.loads(m.skill_revision_ids or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            values = pins.values() if isinstance(pins, dict) else pins
            if any(str(v).replace("rev:", "") in rev_ids for v in values):
                run_ids.append(m.run_id)
        if run_ids:
            runs = (await db.execute(select(Run).where(Run.id.in_(run_ids[:20])))).scalars().all()
            usage = [
                {
                    "run_id": r.id,
                    "status": r.status,
                    "created_at": r.started_at.isoformat() if r.started_at else None,
                }
                for r in runs
            ]

    row.update(
        {
            "body": loaded.body if loaded else "",
            "license": loaded.license if loaded else "",
            "compatibility": loaded.compatibility if loaded else "",
            "allowed_tools": loaded.allowed_tools if loaded else "",
            "revisions": [
                {
                    "id": r.id,
                    "revision_number": r.revision_number,
                    "content_hash": r.content_hash,
                    "change_summary": r.change_summary,
                    "source_run_id": r.source_run_id,
                    "validation_result": json.loads(r.validation_result or "{}"),
                    "is_current": r.id == skill.current_revision_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in revisions
            ],
            "validation": await _validate_now(db, skill),
            "usage": usage,
        }
    )
    return row


@router.get("/{skill_id}/files")
async def skill_files(
    skill_id: str,
    revision: int | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    skill = await _skill_row(db, skill_id)
    rev = await _revision_for_query(db, skill, revision)
    # Drafts + live locals ignore `revision` and show working bytes.
    root = _skill_dir_for_request(skill, rev, revision is not None)
    files = []
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        try:
            resolved = f.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        files.append(
            {
                "path": f.relative_to(root).as_posix(),
                "size": resolved.stat().st_size,
                "mime": previews.media_type(f.name),
            }
        )
    return {"files": files}


@router.get("/{skill_id}/preview")
async def skill_preview(
    skill_id: str,
    path: str,
    revision: int | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    skill = await _skill_row(db, skill_id)
    rev = await _revision_for_query(db, skill, revision)
    root = _skill_dir_for_request(skill, rev, revision is not None)
    target = _resolve_resource(root, path)
    payload = previews.preview_bytes(target.read_bytes(), target.name)
    payload["path"] = path
    payload["absolute_path"] = str(target)
    payload["artifact"] = None
    return payload


@router.get("/{skill_id}/raw")
async def skill_raw(
    skill_id: str,
    path: str,
    revision: int | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    skill = await _skill_row(db, skill_id)
    rev = await _revision_for_query(db, skill, revision)
    root = _skill_dir_for_request(skill, rev, revision is not None)
    target = _resolve_resource(root, path)
    return FileResponse(target, media_type=previews.media_type(target.name), filename=target.name)


@router.get("/{skill_id}/pdf-page")
async def skill_pdf_page(
    skill_id: str,
    path: str,
    page: int,
    revision: int | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    skill = await _skill_row(db, skill_id)
    rev = await _revision_for_query(db, skill, revision)
    root = _skill_dir_for_request(skill, rev, revision is not None)
    target = _resolve_resource(root, path)
    if not target.name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="not a PDF")
    try:
        png = previews.render_pdf_page(target.read_bytes(), page)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"pdf render failed: {e}") from e
    return Response(content=png, media_type="image/png")


@router.get("/{skill_id}/validate")
async def skill_validate(
    skill_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-run validation on the current working bytes (draft saves revalidate)."""
    skill = await _skill_row(db, skill_id)
    return await _validate_now(db, skill)


@router.get("/{skill_id}/export")
async def skill_export(
    skill_id: str,
    revision: int | None = None,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """Export the current (or requested) revision as a zip download."""
    skill = await _skill_row(db, skill_id)
    rev = await _revision_for_query(db, skill, revision)
    root = _skill_dir_for_request(skill, rev, revision is not None)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(root).as_posix())
    filename = f"{skill.name}-rev{rev.revision_number}.zip" if rev else f"{skill.name}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------


class PublishBody(BaseModel):
    scope: str  # global | agent-local
    owner_agent_id: str | None = None
    availability: str = "all"
    agent_ids: list[str] | None = None
    change_summary: str | None = None


@router.post("/{skill_id}/publish")
async def publish_skill(
    skill_id: str,
    body: PublishBody,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish a draft or snapshot a live agent-local copy — gated by
    validation errors (warnings ride along)."""
    skill = await _skill_row(db, skill_id)
    if skill.scope == "built-in":
        raise HTTPException(status_code=400, detail="built-ins ship with the app")

    result = await _validate_now(db, skill)
    if result["errors"]:
        raise HTTPException(
            status_code=422,
            detail={"message": "validation failed", "errors": result["errors"]},
        )
    try:
        revision = await service.publish(
            db,
            skill,
            scope=body.scope,
            owner_agent_id=body.owner_agent_id,
            availability=body.availability,
            agent_ids=body.agent_ids,
            change_summary=body.change_summary,
            validation=result,
        )
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {"published": True, "revision": revision.revision_number, "id": skill.id}


class PromoteBody(BaseModel):
    availability: str = "all"
    agent_ids: list[str] | None = None
    change_summary: str | None = None


@router.post("/{skill_id}/promote")
async def promote_skill(
    skill_id: str,
    body: PromoteBody,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Promote agent-local → global on the same row (history preserved)."""
    skill = await _skill_row(db, skill_id)
    if skill.scope != "agent-local":
        raise HTTPException(status_code=400, detail="only agent-local skills can be promoted")
    result = await _validate_now(db, skill)
    if result["errors"]:
        raise HTTPException(
            status_code=422,
            detail={"message": "validation failed", "errors": result["errors"]},
        )
    try:
        revision = await service.promote(
            db,
            skill,
            availability=body.availability,
            agent_ids=body.agent_ids,
            change_summary=body.change_summary,
            validation=result,
        )
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {"promoted": True, "revision": revision.revision_number}


class DuplicateBody(BaseModel):
    owner_agent_id: str | None = None
    new_name: str | None = None


@router.post("/{skill_id}/duplicate")
async def duplicate_skill(
    skill_id: str,
    body: DuplicateBody,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    skill = await _skill_row(db, skill_id)
    try:
        draft = await service.duplicate(
            db, skill, owner_agent_id=body.owner_agent_id, new_name=body.new_name
        )
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {"id": draft.id, "name": draft.name, "status": draft.status}


class RestoreBody(BaseModel):
    revision_number: int


@router.post("/{skill_id}/restore")
async def restore_skill(
    skill_id: str,
    body: RestoreBody,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restore-as-new-revision — history is never rewritten."""
    skill = await _skill_row(db, skill_id)
    try:
        revision = await service.restore(db, skill, body.revision_number)
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {"restored": True, "revision": revision.revision_number}


class StatusBody(BaseModel):
    status: str  # published | disabled | archived


@router.post("/{skill_id}/status")
async def set_skill_status(
    skill_id: str,
    body: StatusBody,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    skill = await _skill_row(db, skill_id)
    try:
        await service.set_status(db, skill, body.status)
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {"id": skill.id, "status": skill.status}


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    operator: Operator = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Drafts delete outright; published skills purge (archived/disabled +
    no active run pins first)."""
    skill = await _skill_row(db, skill_id)
    try:
        if skill.status == "draft":
            await service.delete_draft(db, skill)
        else:
            await service.purge(db, skill)
    except SkillError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    await db.commit()
    return {"deleted": True, "id": skill_id}
