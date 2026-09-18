"""Artifact service — format-agnostic revision core (W2a).

Seam under test: agentos.artifacts.service — the module interface the
artifact capabilities call. Tests observe behavior through service calls +
workspace files, never internals.
"""

import hashlib
from pathlib import Path

import pytest


@pytest.fixture
def artifact_storage(tmp_path, monkeypatch):
    """Managed revision bytes under tmp_path, not the repo data dir."""
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    return tmp_path / "artifacts"


async def test_create_writes_workspace_file_and_first_revision(db, workspace, artifact_storage):
    from agentos.artifacts import service

    art, rev = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="report.docx",
        data=b"docx-bytes-v1",
        created_by="agent-1",
    )

    assert (Path(workspace) / "report.docx").read_bytes() == b"docx-bytes-v1"
    assert art.format == "docx"
    assert art.tracking_status == "tracked"
    assert rev.revision_number == 1
    assert rev.content_hash == hashlib.sha256(b"docx-bytes-v1").hexdigest()
    assert art.current_revision_id == rev.id
    # Revision bytes preserved in managed storage, readable via the service.
    assert await service.revision_bytes(db, rev.id) == b"docx-bytes-v1"


async def test_revise_creates_new_revision_and_updates_file(db, workspace, artifact_storage):
    from agentos.artifacts import service

    art, rev1 = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="deck.pptx",
        data=b"v1",
        created_by="agent-1",
    )

    rev2 = await service.revise(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=rev1.id,
        data=b"v2",
        change_summary="edit title slide",
    )

    assert rev2.revision_number == 2
    assert rev2.base_revision_id == rev1.id
    assert (Path(workspace) / "deck.pptx").read_bytes() == b"v2"
    assert await service.revision_bytes(db, rev1.id) == b"v1"  # history preserved
    await db.refresh(art)
    assert art.current_revision_id == rev2.id


async def test_external_modification_conflicts_instead_of_overwrite(
    db, workspace, artifact_storage
):
    from agentos.artifacts import service

    art, rev1 = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="book.xlsx",
        data=b"v1",
        created_by="agent-1",
    )
    # User edits the file outside the agent (e.g. in Excel).
    (Path(workspace) / "book.xlsx").write_bytes(b"external-edit")

    with pytest.raises(service.ArtifactConflictError):
        await service.revise(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=rev1.id,
            data=b"agent-draft",
        )

    # The external edit is never overwritten, and no phantom revision exists.
    assert (Path(workspace) / "book.xlsx").read_bytes() == b"external-edit"
    await db.refresh(art)
    assert art.tracking_status == "conflict"
    assert art.current_revision_id == rev1.id


async def test_capture_external_stores_the_external_edit_as_a_revision(
    db, workspace, artifact_storage
):
    from agentos.artifacts import service

    art, rev1 = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="book.xlsx",
        data=b"v1",
        created_by="agent-1",
    )
    (Path(workspace) / "book.xlsx").write_bytes(b"external-edit")

    ext = await service.capture_external(
        db, art.id, workspace_path=workspace, change_summary="user edit in Excel"
    )

    assert ext.revision_number == 2
    await db.refresh(art)
    assert art.tracking_status == "tracked"
    assert art.current_revision_id == ext.id
    # Agent can now revise on top of the captured external revision.
    rev3 = await service.revise(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=ext.id,
        data=b"agent-merge",
    )
    assert rev3.revision_number == 3


async def test_restore_creates_a_new_revision(db, workspace, artifact_storage):
    """Restoring v2 after v5 produces v6 — history is never rewritten."""
    from agentos.artifacts import service

    art, rev1 = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="doc.docx",
        data=b"v1",
        created_by="agent-1",
    )
    last = rev1
    for i in range(2, 6):
        last = await service.revise(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=last.id,
            data=f"v{i}".encode(),
        )
    assert last.revision_number == 5

    rev6 = await service.restore(db, art.id, workspace_path=workspace, revision_id=rev1.id)

    assert rev6.revision_number == 6
    assert rev6.content_hash == rev1.content_hash
    assert rev6.base_revision_id == last.id
    assert (Path(workspace) / "doc.docx").read_bytes() == b"v1"
    await db.refresh(art)
    assert art.current_revision_id == rev6.id


async def test_paths_cannot_escape_the_workspace(db, workspace, artifact_storage):
    from agentos.artifacts import service

    with pytest.raises(Exception):
        await service.create(
            db,
            workspace_id="agent-1",
            workspace_path=workspace,
            rel_path="../outside.docx",
            data=b"evil",
            created_by="agent-1",
        )
    assert not (Path(workspace).parent / "outside.docx").exists()


async def test_relocate_preserves_artifact_identity(db, workspace, artifact_storage):
    """Rename/move keeps the same Artifact + revision history."""
    from agentos.artifacts import service

    art, rev1 = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="drafts/old.docx",
        data=b"v1",
        created_by="agent-1",
    )

    await service.relocate(db, art.id, workspace_path=workspace, new_rel_path="final/report.docx")

    await db.refresh(art)
    assert art.current_path == "final/report.docx"
    assert art.current_revision_id == rev1.id  # same revision, not a new one
    assert (Path(workspace) / "final/report.docx").read_bytes() == b"v1"
    assert not (Path(workspace) / "drafts/old.docx").exists()


async def test_adopt_tracks_an_existing_workspace_file(db, workspace, artifact_storage):
    """Files the user/browser drops into the workspace become tracked."""
    from agentos.artifacts import service

    (Path(workspace) / "download.pdf").write_bytes(b"pdf-v1")

    art, rev = await service.adopt(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="download.pdf",
        created_by="agent-1",
    )

    assert art.format == "pdf"
    assert rev.revision_number == 1
    assert rev.content_hash == hashlib.sha256(b"pdf-v1").hexdigest()
    assert await service.revision_bytes(db, rev.id) == b"pdf-v1"


async def test_archive_tombstones_without_destroying_history(db, workspace, artifact_storage):
    from agentos.artifacts import service

    art, rev1 = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="old.docx",
        data=b"v1",
        created_by="agent-1",
    )

    await service.archive(db, art.id)

    await db.refresh(art)
    assert art.archived_at is not None
    # Revisions survive the tombstone — restore/audit stay possible.
    assert await service.revision_bytes(db, rev1.id) == b"v1"
