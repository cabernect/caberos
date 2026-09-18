"""Artifact service — the module interface for versioned deliverables.

Workspace containment is unconditional: artifact paths always resolve inside
the workspace regardless of the agent's sandbox_mode. Revision bytes live in
managed app data (next to the DB), never in the workspace.
"""

import hashlib
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.artifact import Artifact, ArtifactRevision
from ..sandbox.workspace import resolve_within
from . import formats

MAX_ARTIFACT_BYTES = 100 * 1024 * 1024

_FORMATS = {"docx", "pptx", "xlsx", "pdf", "docm", "pptm", "xlsm"}


class ArtifactError(Exception):
    """Base artifact-domain error."""


class ArtifactConflictError(ArtifactError):
    """Current file hash differs from the named base revision — never
    silently overwrite an external edit."""


def storage_root() -> Path:
    """Managed storage for revision bytes — app data dir, not the workspace."""
    return settings.db_path.parent / "artifacts"


def _format_of(rel_path: str) -> str:
    suffix = Path(rel_path).suffix.lstrip(".").lower()
    return suffix if suffix in _FORMATS else "other"


async def create(
    db: AsyncSession,
    *,
    workspace_id: str,
    workspace_path: str | Path,
    rel_path: str,
    data: bytes,
    created_by: str | None = None,
    source_run_id: str | None = None,
    source_message_id: str | None = None,
    source_plan_step_id: str | None = None,
    change_summary: str | None = None,
) -> tuple[Artifact, ArtifactRevision]:
    """Write `data` to `rel_path` and open tracking with revision 1."""
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactError("artifact exceeds size limit")

    target = resolve_within(workspace_path, rel_path)
    if target.exists():
        raise ArtifactConflictError(f"path already exists: {rel_path}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    artifact = Artifact(
        workspace_id=workspace_id,
        current_path=rel_path,
        format=_format_of(rel_path),
        tracking_status="tracked",
        created_by=created_by,
    )
    db.add(artifact)
    await db.flush()

    revision = await _store_revision(
        db,
        artifact,
        data,
        base_revision_id=None,
        created_by=created_by,
        source_run_id=source_run_id,
        source_message_id=source_message_id,
        source_plan_step_id=source_plan_step_id,
        change_summary=change_summary or "created",
    )
    artifact.current_revision_id = revision.id
    await db.commit()
    return artifact, revision


async def revise(
    db: AsyncSession,
    artifact_id: str,
    *,
    workspace_path: str | Path,
    base_revision_id: str,
    data: bytes,
    created_by: str | None = None,
    source_run_id: str | None = None,
    source_message_id: str | None = None,
    source_plan_step_id: str | None = None,
    change_summary: str | None = None,
) -> ArtifactRevision:
    """Write `data` over the current file and store a new revision.

    Every edit names a base revision; if the file on disk no longer matches
    that base's hash, an external edit happened — raise, don't overwrite.
    """
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactError("artifact exceeds size limit")

    artifact = await _get(db, artifact_id)
    base = await db.get(ArtifactRevision, base_revision_id)
    if base is None or base.artifact_id != artifact.id:
        raise ArtifactError(f"unknown base revision: {base_revision_id}")

    target = resolve_within(workspace_path, artifact.current_path)
    disk_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    if disk_hash != base.content_hash:
        artifact.tracking_status = "conflict"
        await db.commit()
        raise ArtifactConflictError(
            f"file changed since base revision {base_revision_id} — "
            "preserve-both, capture external version, or discard draft"
        )

    target.write_bytes(data)
    revision = await _store_revision(
        db,
        artifact,
        data,
        base_revision_id=base_revision_id,
        created_by=created_by,
        source_run_id=source_run_id,
        source_message_id=source_message_id,
        source_plan_step_id=source_plan_step_id,
        change_summary=change_summary,
    )
    artifact.current_revision_id = revision.id
    artifact.tracking_status = "tracked"
    await db.commit()
    return revision


async def capture_external(
    db: AsyncSession,
    artifact_id: str,
    *,
    workspace_path: str | Path,
    created_by: str | None = None,
    change_summary: str | None = None,
) -> ArtifactRevision:
    """Store the file as it exists on disk right now — resolves a conflict
    by preserving the external edit as a revision instead of discarding it."""
    artifact = await _get(db, artifact_id)
    target = resolve_within(workspace_path, artifact.current_path)
    if not target.exists():
        raise ArtifactError(f"file missing: {artifact.current_path}")

    data = target.read_bytes()
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactError("artifact exceeds size limit")

    revision = await _store_revision(
        db,
        artifact,
        data,
        base_revision_id=artifact.current_revision_id,
        created_by=created_by,
        change_summary=change_summary or "external edit captured",
    )
    artifact.current_revision_id = revision.id
    artifact.tracking_status = "tracked"
    await db.commit()
    return revision


async def restore(
    db: AsyncSession,
    artifact_id: str,
    *,
    workspace_path: str | Path,
    revision_id: str,
    created_by: str | None = None,
    change_summary: str | None = None,
) -> ArtifactRevision:
    """Write an old revision's bytes back to the workspace — as a NEW
    revision. History is append-only; restore never rewinds the pointer."""
    artifact = await _get(db, artifact_id)
    target_rev = await db.get(ArtifactRevision, revision_id)
    if target_rev is None or target_rev.artifact_id != artifact.id:
        raise ArtifactError(f"unknown revision: {revision_id}")

    data = await revision_bytes(db, revision_id)
    target = resolve_within(workspace_path, artifact.current_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    revision = await _store_revision(
        db,
        artifact,
        data,
        base_revision_id=artifact.current_revision_id,
        created_by=created_by,
        change_summary=change_summary or f"restored revision {target_rev.revision_number}",
    )
    artifact.current_revision_id = revision.id
    artifact.tracking_status = "tracked"
    await db.commit()
    return revision


async def relocate(
    db: AsyncSession,
    artifact_id: str,
    *,
    workspace_path: str | Path,
    new_rel_path: str,
) -> Artifact:
    """Move/rename the workspace file — identity and history are unchanged."""
    artifact = await _get(db, artifact_id)
    old_target = resolve_within(workspace_path, artifact.current_path)
    new_target = resolve_within(workspace_path, new_rel_path)
    if new_target.exists():
        raise ArtifactConflictError(f"destination exists: {new_rel_path}")

    new_target.parent.mkdir(parents=True, exist_ok=True)
    old_target.rename(new_target)
    artifact.current_path = new_rel_path
    artifact.format = _format_of(new_rel_path)
    await db.commit()
    return artifact


async def adopt(
    db: AsyncSession,
    *,
    workspace_id: str,
    workspace_path: str | Path,
    rel_path: str,
    created_by: str | None = None,
    change_summary: str | None = None,
) -> tuple[Artifact, ArtifactRevision]:
    """Start tracking a file that already exists in the workspace — its
    current bytes become revision 1 (downloads, imports, user drops)."""
    target = resolve_within(workspace_path, rel_path)
    if not target.exists():
        raise ArtifactError(f"file missing: {rel_path}")
    data = target.read_bytes()
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactError("artifact exceeds size limit")

    artifact = Artifact(
        workspace_id=workspace_id,
        current_path=rel_path,
        format=_format_of(rel_path),
        tracking_status="tracked",
        created_by=created_by,
    )
    db.add(artifact)
    await db.flush()

    revision = await _store_revision(
        db,
        artifact,
        data,
        base_revision_id=None,
        created_by=created_by,
        change_summary=change_summary or "adopted existing file",
    )
    artifact.current_revision_id = revision.id
    await db.commit()
    return artifact, revision


async def archive(db: AsyncSession, artifact_id: str) -> Artifact:
    """Tombstone the artifact — hidden, but revisions survive for
    restore/audit. Permanent purge is a separate operator action."""
    from datetime import UTC, datetime

    artifact = await _get(db, artifact_id)
    artifact.archived_at = datetime.now(UTC)
    await db.commit()
    return artifact


async def create_structured(
    db: AsyncSession,
    *,
    workspace_id: str,
    workspace_path: str | Path,
    rel_path: str,
    format: str,
    spec: dict,
    created_by: str | None = None,
    source_run_id: str | None = None,
    source_message_id: str | None = None,
    source_plan_step_id: str | None = None,
    change_summary: str | None = None,
) -> tuple[Artifact, ArtifactRevision]:
    """Build a deliverable from a structured spec (never raw XML) and track
    it — the primary creation path for Office formats."""
    try:
        handler = formats.get_handler(format)
    except formats.UnsupportedFormatError as e:
        raise ArtifactError(str(e)) from e
    if not hasattr(handler, "build"):
        raise ArtifactError(f"format is read-only: {format}")
    data = handler.build(spec, workspace_path)
    return await create(
        db,
        workspace_id=workspace_id,
        workspace_path=workspace_path,
        rel_path=rel_path,
        data=data,
        created_by=created_by,
        source_run_id=source_run_id,
        source_message_id=source_message_id,
        source_plan_step_id=source_plan_step_id,
        change_summary=change_summary,
    )


async def revise_structured(
    db: AsyncSession,
    artifact_id: str,
    *,
    workspace_path: str | Path,
    base_revision_id: str,
    ops: list[dict],
    created_by: str | None = None,
    source_run_id: str | None = None,
    source_message_id: str | None = None,
    source_plan_step_id: str | None = None,
    change_summary: str | None = None,
) -> ArtifactRevision:
    """Apply structured ops (append/replace/set-cell) and store the result
    as a new revision — same base-check as raw revise."""
    artifact = await _get(db, artifact_id)
    try:
        handler = formats.get_handler(artifact.format)
    except formats.UnsupportedFormatError as e:
        raise ArtifactError(str(e)) from e
    if not hasattr(handler, "revise"):
        raise ArtifactError(f"format is read-only: {artifact.format}")
    target = resolve_within(workspace_path, artifact.current_path)
    if not target.exists():
        raise ArtifactError(f"file missing: {artifact.current_path}")

    new_data = handler.revise(target.read_bytes(), ops, workspace_path)
    return await revise(
        db,
        artifact_id,
        workspace_path=workspace_path,
        base_revision_id=base_revision_id,
        data=new_data,
        created_by=created_by,
        source_run_id=source_run_id,
        source_message_id=source_message_id,
        source_plan_step_id=source_plan_step_id,
        change_summary=change_summary,
    )


async def inspect(db: AsyncSession, artifact_id: str, *, workspace_path: str | Path) -> dict:
    """Structure + validity of the current workspace file."""
    artifact = await _get(db, artifact_id)
    target = resolve_within(workspace_path, artifact.current_path)
    if not target.exists():
        raise ArtifactError(f"file missing: {artifact.current_path}")
    data = target.read_bytes()

    info: dict = {
        "artifact_id": artifact.id,
        "path": artifact.current_path,
        "format": artifact.format,
        "tracking_status": artifact.tracking_status,
        "current_revision_id": artifact.current_revision_id,
    }
    try:
        handler = formats.get_handler(artifact.format)
    except formats.UnsupportedFormatError:
        info.update({"valid": True, "errors": [], "structure": None})
        return info
    info.update(handler.validate(data))
    if info["valid"]:
        inspected = handler.inspect(data)
        info["structure"] = inspected.pop("structure", None)
        info.update(inspected)
    return info


# Formats where a linear document render preserves the content faithfully —
# slide decks are layout-bound: a text-flow PDF of a presentation isn't a
# real export, so pptx requires the layout engine (LibreOffice).
#
# TODO(W4): Chromium renderer — elements → HTML → headless --print-to-pdf.
# W4 browser automation ships a managed engine (Playwright cache); slides
# carry absolute coordinates so positioned-HTML gives real deck layout
# without LibreOffice. Chain: soffice → chromium → reportlab → unavailable.
_REPORTLAB_FORMATS = {"docx", "xlsx"}


def _find_soffice() -> str | None:
    """Locate a LibreOffice binary for Office→PDF rendering."""
    import shutil

    if found := shutil.which("soffice"):
        return found
    for candidate in (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",
    ):
        if Path(candidate).exists():
            return candidate
    return None


async def export_pdf(
    db: AsyncSession,
    artifact_id: str,
    *,
    workspace_path: str | Path,
    created_by: str | None = None,
    source_run_id: str | None = None,
    source_message_id: str | None = None,
) -> dict:
    """Render the current revision to PDF.

    Renderer chain: LibreOffice headless (layout-faithful) when installed →
    pure-Python reportlab render of the extracted elements (works anywhere,
    document-grade fidelity) → renderer_unavailable only when neither can
    handle the format. The produced PDF is tracked as its own read-only
    artifact linked to the source run.
    """
    import asyncio
    import tempfile

    artifact = await _get(db, artifact_id)
    if artifact.format == "pdf":
        raise ArtifactError("artifact is already pdf")

    src = resolve_within(workspace_path, artifact.current_path)
    if not src.exists():
        raise ArtifactError(f"file missing: {artifact.current_path}")

    pdf_data: bytes | None = None
    renderer: str | None = None
    soffice_error: str | None = None

    soffice = _find_soffice()
    if soffice is not None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = await asyncio.create_subprocess_exec(
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                tmp,
                str(src),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except TimeoutError:
                proc.kill()
                soffice_error = "timeout"
            else:
                produced = Path(tmp) / f"{src.stem}.pdf"
                if proc.returncode != 0:
                    soffice_error = stderr.decode("utf-8", errors="replace")[-500:]
                elif not produced.exists():
                    soffice_error = "renderer produced no output"
                else:
                    pdf_data = produced.read_bytes()
                    renderer = "libreoffice"

    if pdf_data is None and artifact.format in _REPORTLAB_FORMATS:
        try:
            handler = formats.get_handler(artifact.format)
        except formats.UnsupportedFormatError:
            handler = None
        to_elements = getattr(handler, "to_elements", None)
        if to_elements is not None:
            try:
                from .pdf_render import render_document

                pdf_data = render_document(
                    to_elements(src.read_bytes(), workspace_path), workspace_path
                )
                renderer = "reportlab"
            except Exception as e:
                if soffice_error is None:
                    return {
                        "export_status": "failed",
                        "renderer": "reportlab",
                        "error": str(e)[:500],
                    }

    if pdf_data is None:
        if soffice_error is not None:
            return {"export_status": "failed", "renderer": "libreoffice", "error": soffice_error}
        reason = (
            f"{artifact.format} export requires LibreOffice — layout-bound format"
            if artifact.format not in _REPORTLAB_FORMATS
            else None
        )
        return {"export_status": "renderer_unavailable", "renderer": None, "reason": reason}

    pdf_rel = str(Path(artifact.current_path).with_suffix(".pdf"))
    pdf_artifact, _ = await create(
        db,
        workspace_id=artifact.workspace_id,
        workspace_path=workspace_path,
        rel_path=pdf_rel,
        data=pdf_data,
        created_by=created_by,
        source_run_id=source_run_id,
        source_message_id=source_message_id,
        change_summary=f"exported from {artifact.current_path}",
    )
    return {
        "export_status": "exported",
        "renderer": renderer,
        "pdf_artifact_id": pdf_artifact.id,
    }


async def history(db: AsyncSession, artifact_id: str) -> list[dict]:
    """Revision list for an artifact — newest first."""
    from sqlalchemy import select

    artifact = await _get(db, artifact_id)
    rows = (
        (
            await db.execute(
                select(ArtifactRevision)
                .where(ArtifactRevision.artifact_id == artifact.id)
                .order_by(ArtifactRevision.revision_number.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "revision_id": r.id,
            "revision_number": r.revision_number,
            "content_hash": r.content_hash[:12],
            "byte_size": r.byte_size,
            "change_summary": r.change_summary,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "source_run_id": r.source_run_id,
            "source_message_id": r.source_message_id,
            "base_revision_id": r.base_revision_id,
            "current": r.id == artifact.current_revision_id,
        }
        for r in rows
    ]


async def _get(db: AsyncSession, artifact_id: str) -> Artifact:
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None:
        raise ArtifactError(f"unknown artifact: {artifact_id}")
    return artifact


async def get_by_path(db: AsyncSession, workspace_id: str, rel_path: str) -> Artifact | None:
    """Look up the artifact tracking a workspace path — None for ordinary
    files. The preview API uses this to split tracked vs untracked actions."""
    from sqlalchemy import select

    return await db.scalar(
        select(Artifact).where(
            Artifact.workspace_id == workspace_id,
            Artifact.current_path == rel_path,
        )
    )


async def _store_revision(
    db: AsyncSession,
    artifact: Artifact,
    data: bytes,
    **fields,
) -> ArtifactRevision:
    """Persist bytes to managed storage and insert the revision row."""
    from sqlalchemy import func, select

    n = (
        await db.execute(
            select(func.count(ArtifactRevision.id)).where(
                ArtifactRevision.artifact_id == artifact.id
            )
        )
    ).scalar_one() + 1

    rel_storage = Path(artifact.id) / f"rev{n}{Path(artifact.current_path).suffix}"
    dest = storage_root() / rel_storage
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    revision = ArtifactRevision(
        artifact_id=artifact.id,
        revision_number=n,
        content_hash=hashlib.sha256(data).hexdigest(),
        storage_path=str(rel_storage),
        byte_size=len(data),
        **fields,
    )
    db.add(revision)
    await db.flush()
    return revision


async def revision_bytes(db: AsyncSession, revision_id: str) -> bytes:
    """Read stored revision bytes — the seam previews/restore/diffs use."""
    rev = await db.get(ArtifactRevision, revision_id)
    if rev is None:
        raise ArtifactError(f"unknown revision: {revision_id}")
    return (storage_root() / rev.storage_path).read_bytes()
