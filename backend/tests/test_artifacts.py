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


# --- W2b: DOCX structured generation ---


async def test_docx_create_inspect_roundtrip(db, workspace, artifact_storage):
    """Structured spec → valid DOCX → inspectable structure."""
    from agentos.artifacts import service

    spec = {
        "title": "Q3 Report",
        "blocks": [
            {"type": "heading", "level": 1, "text": "Summary"},
            {"type": "paragraph", "text": "Revenue grew 12%."},
            {"type": "list", "style": "bullet", "items": ["alpha", "beta"]},
            {"type": "table", "header": ["Metric", "Value"], "rows": [["ARR", "4.2"]]},
        ],
    }
    art, _rev = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="q3.docx",
        format="docx",
        spec=spec,
        created_by="agent-1",
    )

    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert info["valid"] is True
    assert "Summary" in info["structure"]["headings"]
    assert info["structure"]["tables"] == 1
    assert info["structure"]["list_items"] == 2
    # Agent-facing inspect declares the same preview fidelity the operator
    # preview payload does — structure is exact, previews are approximate.
    assert info["preview"]["mode"] == "approximate"
    assert info["preview"]["limitations"] == ["layout", "fonts", "fields", "omitted_features"]


async def test_docx_revise_applies_ops_as_new_revision(db, workspace, artifact_storage):
    from agentos.artifacts import service

    spec = {"blocks": [{"type": "paragraph", "text": "draft"}]}
    art, rev1 = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="memo.docx",
        format="docx",
        spec=spec,
        created_by="agent-1",
    )

    rev2 = await service.revise_structured(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=rev1.id,
        ops=[
            {"op": "replace_paragraph", "index": 0, "text": "final"},
            {"op": "append_blocks", "blocks": [{"type": "heading", "level": 1, "text": "Done"}]},
        ],
        change_summary="finalize memo",
    )

    assert rev2.revision_number == 2
    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert "Done" in info["structure"]["headings"]
    # Old revision still inspectable — messages link to exact revisions.
    old = await service.revision_bytes(db, rev1.id)
    assert b"draft" not in old  # zip is binary; verify via structure below
    from agentos.artifacts.formats import docx as docx_fmt

    assert "Done" not in docx_fmt.inspect(old)["structure"]["headings"]


async def test_failed_generation_creates_no_revision(db, workspace, artifact_storage):
    """A build that blows up leaves no artifact rows and no workspace file."""
    from sqlalchemy import func, select

    from agentos.artifacts import service
    from agentos.models.artifact import Artifact, ArtifactRevision

    with pytest.raises(Exception):
        await service.create_structured(
            db,
            workspace_id="agent-1",
            workspace_path=workspace,
            rel_path="bad.docx",
            format="docx",
            spec={"blocks": [{"type": "bogus"}]},
            created_by="agent-1",
        )

    for model in (Artifact, ArtifactRevision):
        n = (await db.execute(select(func.count(model.id)))).scalar_one()
        assert n == 0
    assert not (Path(workspace) / "bad.docx").exists()


async def test_corrupt_file_reports_invalid_not_crash(db, workspace, artifact_storage):
    from agentos.artifacts import service

    # Write garbage where a docx should be, then inspect.
    (Path(workspace) / "corrupt.docx").write_bytes(b"not-a-zip")
    art, _ = await service.adopt(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="corrupt.docx",
        created_by="agent-1",
    )

    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert info["valid"] is False
    assert info["errors"]
    # Fidelity metadata survives invalid files — same as preview payloads.
    assert info["preview"]["mode"] == "approximate"


async def test_inspect_zip_bomb_refuses_safely(db, workspace, artifact_storage, monkeypatch):
    """A package exceeding expansion bounds is refused with an explicit
    error — never misreported as valid or corrupt."""
    import docx as docx_lib

    from agentos import previews
    from agentos.artifacts import service
    from agentos.artifacts.service import ArtifactError

    doc = docx_lib.Document()
    doc.add_paragraph("hi")
    doc.save(Path(workspace) / "bomb.docx")
    art, _ = await service.adopt(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="bomb.docx",
        created_by="agent-1",
    )

    monkeypatch.setattr(previews, "OFFICE_ZIP_MAX_ENTRY_BYTES", 10)
    with pytest.raises(ArtifactError, match="exceeds safe bounds"):
        await service.inspect(db, art.id, workspace_path=workspace)


async def test_revise_zip_bomb_refuses_safely(db, workspace, artifact_storage, monkeypatch):
    """Structured revise hits the same expansion guard before parsing."""
    import docx as docx_lib

    from agentos import previews
    from agentos.artifacts import service
    from agentos.artifacts.service import ArtifactError

    doc = docx_lib.Document()
    doc.add_paragraph("hi")
    doc.save(Path(workspace) / "memo.docx")
    art, rev = await service.adopt(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="memo.docx",
        created_by="agent-1",
    )

    monkeypatch.setattr(previews, "OFFICE_ZIP_MAX_TOTAL_BYTES", 10)
    with pytest.raises(ArtifactError, match="exceeds safe bounds"):
        await service.revise_structured(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=rev.id,
            ops=[{"op": "append_blocks", "blocks": [{"type": "paragraph", "text": "x"}]}],
        )


# --- W2c: XLSX structured generation ---


async def test_xlsx_create_inspect_with_honest_formula_status(db, workspace, artifact_storage):
    from agentos.artifacts import service

    spec = {
        "sheets": [
            {
                "name": "Summary",
                "rows": [["Metric", "Value"], ["ARR", 4.2], ["MRR", 0.35]],
                "cells": {"B5": {"formula": "=SUM(B2:B3)"}},
                "freeze": "A2",
            }
        ]
    }
    art, _ = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="model.xlsx",
        format="xlsx",
        spec=spec,
        created_by="agent-1",
    )

    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert info["valid"] is True
    s = info["structure"]
    assert s["sheets"] == ["Summary"]
    assert s["formulas"] == 1
    # openpyxl writes formulas but never computes — report honestly.
    assert info["formulas_recalculated"] is False


async def test_xlsx_revise_set_cell_and_append(db, workspace, artifact_storage):
    from agentos.artifacts import service

    spec = {"sheets": [{"name": "Data", "rows": [["a", 1]]}]}
    art, rev1 = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="book.xlsx",
        format="xlsx",
        spec=spec,
        created_by="agent-1",
    )

    await service.revise_structured(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=rev1.id,
        ops=[
            {"op": "set_cell", "sheet": "Data", "cell": "B2", "value": 2},
            {"op": "set_cell", "sheet": "Data", "cell": "B3", "formula": "=SUM(B1:B2)"},
            {"op": "append_rows", "sheet": "Data", "rows": [["b", 3]]},
        ],
    )

    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert info["structure"]["formulas"] == 1
    assert info["structure"]["cells"] == 6  # 2 original + B2 + B3 + appended row


# --- W2d: PPTX structured generation ---


async def test_pptx_create_inspect_roundtrip(db, workspace, artifact_storage):
    from agentos.artifacts import service

    spec = {
        "slides": [
            {"layout": "title", "title": "Q3 Review", "subtitle": "Engineering"},
            {
                "layout": "title_content",
                "title": "Highlights",
                "blocks": [{"type": "bullets", "items": ["ship W1", "start W2"]}],
            },
            {
                "layout": "title_content",
                "title": "Numbers",
                "blocks": [
                    {
                        "type": "chart",
                        "chart_type": "bar",
                        "categories": ["Q1", "Q2", "Q3"],
                        "series": [{"name": "ARR", "values": [3.1, 3.8, 4.2]}],
                    },
                    {"type": "notes", "text": "emphasize Q3 acceleration"},
                ],
            },
        ]
    }
    art, _ = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="q3.pptx",
        format="pptx",
        spec=spec,
        created_by="agent-1",
    )

    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert info["valid"] is True
    s = info["structure"]
    assert s["slides"] == 3
    assert s["charts"] == 1


# --- W2H: HTML deck artifacts ---


def _deck_spec(**over):
    spec = {
        "version": 1,
        "title": "Q3 Review",
        "theme": {"background": "#FAFAF7", "accent": "#3F6212", "text": "#1C1917"},
        "slides": [
            {
                "id": "intro",
                "title": "Welcome",
                "blocks": [{"type": "paragraph", "text": "Hello team"}],
            },
            {
                "id": "evil",
                "html": '<p onclick="alert(1)">safe</p><script>alert(2)</script>'
                '<img src="https://evil.example/x.png">'
                '<img src="data:image/png;base64,iVBORw0KGgo=">',
            },
        ],
    }
    spec.update(over)
    return spec


async def test_html_deck_create_inspect_roundtrip(db, workspace, artifact_storage):
    from agentos.artifacts import service

    art, _ = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="deck.html",
        format="html",
        spec=_deck_spec(),
        created_by="agent-1",
    )

    assert art.format == "html"
    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert info["valid"] is True
    s = info["structure"]
    assert s["title"] == "Q3 Review"
    assert s["slides"] == 2
    assert s["slide_ids"] == ["intro", "evil"]
    assert s["runtime"] == "deck-rt3"
    assert s["theme"] == ["accent", "background", "text"]
    assert s["assets"] == []

    # The stored bytes are self-contained: one runtime script + spec JSON,
    # sanitized fragments (no onclick/external img), platform nav present.
    text = (Path(workspace) / art.current_path).read_text()
    body = text.split('id="deck-spec"')[0]
    assert "onclick" not in body
    assert "evil.example" not in body
    assert "<script>alert" not in text
    assert "data:image/png;base64" in body
    assert text.count("<script") == 2  # embedded spec JSON + runtime only


async def test_html_deck_revise_by_slide_id_and_index(db, workspace, artifact_storage):
    from agentos.artifacts import service

    art, rev = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="deck.html",
        format="html",
        spec=_deck_spec(),
        created_by="agent-1",
    )

    await service.revise_structured(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=rev.id,
        ops=[
            {"op": "set_title", "title": "Q3 Review v2"},
            {"op": "set_slide", "slide": "evil", "title": "Numbers"},
            {
                "op": "add_slide",
                "slide": {"blocks": [{"type": "divider"}]},
                "at": 1,
            },
        ],
        created_by="agent-1",
    )

    info = await service.inspect(db, art.id, workspace_path=workspace)
    s = info["structure"]
    assert s["title"] == "Q3 Review v2"
    assert s["slide_ids"] == ["intro", "s3", "evil"]
    assert s["slides"] == 3

    # Unaffected slide content survives verbatim; ids are stable.
    text = (Path(workspace) / art.current_path).read_text()
    assert "Hello team" in text
    assert 'data-slide-id="evil"' in text


async def test_html_deck_revise_missing_id_fails(db, workspace, artifact_storage):
    from agentos.artifacts import service

    art, rev = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="deck.html",
        format="html",
        spec=_deck_spec(),
        created_by="agent-1",
    )

    with pytest.raises(ValueError, match="unknown slide id"):
        await service.revise_structured(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=rev.id,
            ops=[{"op": "remove_slide", "slide": "nope"}],
            created_by="agent-1",
        )


def test_html_deck_spec_validation():
    from agentos.artifacts.formats import html

    # Unknown spec version rejected, not silently downgraded.
    with pytest.raises(ValueError, match="version"):
        html.build({**_deck_spec(), "version": 99}, "/tmp")
    # Theme hex validated.
    with pytest.raises(ValueError, match="hex"):
        html.build({**_deck_spec(), "theme": {"accent": "red"}}, "/tmp")
    # Slide budget enforced.
    with pytest.raises(ValueError, match="100 slides"):
        html.build(
            {**_deck_spec(), "slides": [{"blocks": [{"type": "divider"}]}] * 101},
            "/tmp",
        )
    # Duplicate slide ids rejected.
    with pytest.raises(ValueError, match="duplicate slide id"):
        html.build(
            {
                **_deck_spec(),
                "slides": [
                    {"id": "a", "blocks": [{"type": "divider"}]},
                    {"id": "a", "blocks": [{"type": "divider"}]},
                ],
            },
            "/tmp",
        )
    # html + blocks on one slide rejected.
    with pytest.raises(ValueError, match="not both"):
        html.build(
            {
                **_deck_spec(),
                "slides": [{"html": "<p>x</p>", "blocks": [{"type": "divider"}]}],
            },
            "/tmp",
        )
    # Fragment that sanitizes to nothing rejected.
    with pytest.raises(ValueError, match="sanitized to nothing"):
        html.build({"title": "x", "slides": [{"html": "<script>x</script>"}]}, "/tmp")
    # Unknown slide layout / theme font rejected.
    with pytest.raises(ValueError, match="layout"):
        html.build({"slides": [{"layout": "carousel", "blocks": [{"type": "divider"}]}]}, "/tmp")
    with pytest.raises(ValueError, match="font"):
        html.build({**_deck_spec(), "theme": {"font": "comic-sans"}}, "/tmp")


def test_html_deck_layout_reveal_font_features():
    from agentos.artifacts.formats import html

    spec = {
        "title": "Launch",
        "theme": {"font": "serif", "accent": "#7C3AED"},
        "slides": [
            {"id": "cover", "layout": "title", "title": "Big reveal", "notes": "open strong"},
            {
                "id": "body",
                "title": "Agenda",
                "blocks": [
                    {"type": "paragraph", "text": "always visible"},
                    {"type": "bullets", "items": ["one", "two"], "reveal": True},
                    {"type": "bullets", "items": ["three"], "reveal": True},
                ],
            },
        ],
    }
    data = html.build(spec, "/tmp")
    text = data.decode()
    assert 'class="slide layout-title"' in text
    assert "--deck-font:" in text and "Georgia" in text
    assert text.count('class="blk rv"') == 2
    assert 'class="blk"' in text
    # Slide furniture: progress bar, per-slide footer, notes overlay.
    assert 'id="deck-progress"' in text and 'class="slide-foot"' in text
    assert 'id="deck-notes-overlay"' in text
    # Bridge supports step/goto; state reports reveal progress.
    assert "'step'" in text and "gotoSlide" in text
    assert "canPrev" in text and "pending" in text
    info = html.inspect(data)
    assert info["structure"]["reveal_blocks"] == 2
    assert info["structure"]["section_ids_match"] is True
    assert html.validate(data)["valid"] is True
    assert html.admission(data) is not None


def test_html_deck_validate_rejects_foreign_html():
    from agentos.artifacts.formats import html

    assert html.validate(b"<html><body>hello</body></html>")["valid"] is False
    assert html.validate(b"not html at all")["valid"] is False


def test_html_deck_admission_and_crafted_refusal():
    from agentos.artifacts.formats import html

    data = html.build(_deck_spec(), "/tmp")
    info = html.admission(data)
    assert info is not None
    assert info["runtime"] == "deck-rt3"
    assert info["title"] == "Q3 Review"
    assert info["slides"] == 2

    # Legacy decks stay playable — runtime upgrades must not strand portable
    # files (each embeds its own runtime; admission accepts every known
    # platform runtime, CSP hash-pins each).
    for ver, js in (("deck-rt2", html._RUNTIME_JS_V2), ("deck-rt1", html._RUNTIME_JS_V1)):
        old = html.admission(data.decode().replace(html._RUNTIME_JS, js, 1).encode())
        assert old is not None and old["runtime"] == ver
    assert "script-src" in html.DECK_CSP and html.DECK_CSP.count("sha256-") == 3

    # Foreign html and crafted extra scripts are never admitted.
    assert html.admission(b"<p>hi</p>") is None
    crafted = data.decode().replace("</body>", "<script>alert(1)</script></body>").encode()
    assert html.admission(crafted) is None

    # Spec text with &, quotes and a literal "</script>" still round-trips —
    # the embedded spec JSON escapes `<` so it can't break the element.
    tricky = html.build(
        {
            "title": "R&D",
            "slides": [
                {
                    "notes": "x </script> y",
                    "blocks": [{"type": "paragraph", "text": "a & b"}],
                }
            ],
        },
        "/tmp",
    )
    assert html.admission(tricky) is not None
    assert html.inspect(tricky)["structure"]["title"] == "R&D"


def test_html_deck_csp_pins_runtime_only():
    from agentos.artifacts.formats import html

    assert "script-src 'sha256-" in html.DECK_CSP
    script_src = html.DECK_CSP.split("script-src")[1].split(";")[0]
    assert "unsafe-inline" not in script_src
    assert "connect-src 'none'" in html.DECK_CSP
    assert "sandbox allow-scripts" in html.DECK_CSP


_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # magic bytes are the type check


def _asset_spec():
    return {
        "title": "Assets",
        "slides": [
            {
                "id": "s1",
                "blocks": [
                    {"type": "image", "src": "assets/logo.png", "alt": "Logo"},
                    {"type": "paragraph", "text": "below"},
                ],
            },
            {
                "id": "s2",
                "html": '<p>shot</p><img src="assets/shot.png" alt="s">',
            },
        ],
    }


def test_html_deck_workspace_assets_embed(tmp_path):
    from agentos.artifacts.formats import html

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/logo.png").write_bytes(_PNG)
    (tmp_path / "assets/shot.png").write_bytes(_PNG + b"x")

    data = html.build(_asset_spec(), tmp_path)
    text = data.decode()
    # Both refs became embedded data URIs; no workspace path survives.
    assert text.count("data:image/png;base64,") == 2
    assert 'assets/logo.png"' not in text.split('id="deck-spec"')[0]
    info = html.inspect(data)
    assets = info["structure"]["assets"]
    assert [a["path"] for a in assets] == ["assets/logo.png", "assets/shot.png"]
    assert all(a["mime"] == "image/png" and a["sha256"] for a in assets)
    assert html.admission(data) is not None

    # Revise re-resolves refs against the CURRENT workspace file.
    (tmp_path / "assets/logo.png").write_bytes(_PNG + b"changed")
    out = html.revise(data, [{"op": "set_title", "title": "v2"}], tmp_path)
    assert html.inspect(out)["structure"]["title"] == "v2"
    assert len(html.inspect(out)["structure"]["assets"]) == 2


def test_html_deck_asset_rejections(tmp_path):
    from agentos.artifacts.formats import html

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/ok.png").write_bytes(_PNG)
    (tmp_path / "assets/evil.svg").write_text("<svg xmlns='x'><script/></svg>")
    (tmp_path / "assets/notimg.txt").write_text("hello")
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(_PNG)

    def build_with(src, slide=None):
        spec = slide or {"slides": [{"blocks": [{"type": "image", "src": src}]}]}
        return html.build(spec, tmp_path)

    # Traversal / absolute / missing / non-raster all refused.
    with pytest.raises(ValueError):
        build_with("../outside.png")
    with pytest.raises(ValueError):
        build_with(str(outside))
    with pytest.raises(ValueError, match="not found"):
        build_with("assets/missing.png")
    with pytest.raises(ValueError, match="not a raster"):
        build_with("assets/evil.svg")
    with pytest.raises(ValueError, match="not a raster"):
        build_with("assets/notimg.txt")
    # Same rules inside html fragments — bad refs are stripped by the
    # sanitizer (never resolved), good refs embed.
    frag = {"slides": [{"html": '<img src="../outside.png"><img src="assets/ok.png">'}]}
    data = html.build(frag, tmp_path)
    assert data.decode().count("data:image/png;base64,") == 1
    assert "outside.png" not in data.decode().split("<body>")[1].split("<script")[0]


# --- W2e: PDF export + read-only imported PDFs ---


def _pdf_bytes(pages: int = 2) -> bytes:
    from io import BytesIO

    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


async def test_imported_pdf_is_readable_but_not_editable(db, workspace, artifact_storage):
    from agentos.artifacts import service

    (Path(workspace) / "scan.pdf").write_bytes(_pdf_bytes())
    art, _ = await service.adopt(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="scan.pdf",
        created_by="agent-1",
    )

    info = await service.inspect(db, art.id, workspace_path=workspace)
    assert info["valid"] is True
    assert info["structure"]["pages"] == 2

    # Read-only: no structured revision path for pdf.
    with pytest.raises(service.ArtifactError):
        await service.revise_structured(
            db, art.id, workspace_path=workspace, base_revision_id=art.current_revision_id, ops=[]
        )


async def test_create_pdf_directly_from_spec(db, workspace, artifact_storage):
    """spec → PDF bytes — pdf is now a creatable (write-once) format."""
    from io import BytesIO

    from pypdf import PdfReader

    from agentos.artifacts import service

    art, rev = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="brief.pdf",
        format="pdf",
        spec={
            "title": "Brief",
            "blocks": [{"type": "paragraph", "text": "direct pdf"}],
        },
        created_by="agent-1",
    )

    assert art.format == "pdf"
    data = await service.revision_bytes(db, rev.id)
    reader = PdfReader(BytesIO(data))
    assert "Brief" in reader.pages[0].extract_text()

    # Still write-once: no structured revision path.
    with pytest.raises(service.ArtifactError):
        await service.revise_structured(
            db, art.id, workspace_path=workspace, base_revision_id=rev.id, ops=[]
        )


# --- W2f: mediated capability path ---


def _agent_config(caps: list[str]):
    from agentos.config_schema import AgentConfig, CapabilityGrant, ModelConfig

    return AgentConfig(
        id="art-agent",
        name="Artifact Agent",
        model=ModelConfig(provider_id="test", name="test-model"),
        capabilities=[CapabilityGrant(name=c, require_approval=False) for c in caps],
    )


def _session_stub():
    from types import SimpleNamespace

    return SimpleNamespace(contact_id="c1", id="sess-1", channel=None)


async def test_mediated_artifact_roundtrip_with_provenance(db, workspace, artifact_storage):
    """artifact_create → inspect → revise → history through the mediator,
    with run/message provenance captured on revisions."""
    from sqlalchemy import select

    from agentos.artifacts.service import storage_root  # noqa: F401 — fixture touch
    from agentos.models.artifact import ArtifactRevision
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    handler = SyscallHandler(db=db, workspace_path=workspace)
    config = _agent_config(
        ["artifact_create", "artifact_inspect", "artifact_revise", "artifact_history"]
    )
    session = _session_stub()

    spec = {"blocks": [{"type": "heading", "level": 1, "text": "Hi"}]}
    created = await handler.mediate(
        call=ToolCall(
            id="call-1",
            name="artifact_create",
            args={"path": "out.docx", "format": "docx", "spec": spec},
        ),
        session=session,
        agent_config=config,
        run_id="run-art",
    )
    assert created.allowed is True
    art_id = created.output["artifact_id"]
    rev1 = created.output["revision_id"]

    # Provenance captured on the revision row.
    rev_row = (
        await db.execute(select(ArtifactRevision).where(ArtifactRevision.id == rev1))
    ).scalar_one()
    assert rev_row.source_run_id == "run-art"
    # W10: the tool call's correlation id lands on call_id — a call id is
    # not a message id, so source_message_id stays empty.
    assert rev_row.call_id == "call-1"
    assert rev_row.source_message_id is None

    info = await handler.mediate(
        call=ToolCall(id="call-2", name="artifact_inspect", args={"artifact_id": art_id}),
        session=session,
        agent_config=config,
        run_id="run-art",
    )
    assert info.output["valid"] is True

    revised = await handler.mediate(
        call=ToolCall(
            id="call-3",
            name="artifact_revise",
            args={
                "artifact_id": art_id,
                "base_revision_id": rev1,
                "ops": [{"op": "append_blocks", "blocks": [{"type": "paragraph", "text": "body"}]}],
            },
        ),
        session=session,
        agent_config=config,
        run_id="run-art",
    )
    assert revised.output["revision_number"] == 2

    hist = await handler.mediate(
        call=ToolCall(id="call-4", name="artifact_history", args={"artifact_id": art_id}),
        session=session,
        agent_config=config,
        run_id="run-art",
    )
    assert len(hist.output["revisions"]) == 2
    assert hist.output["revisions"][0]["current"] is True


async def test_ungranted_artifact_call_is_denied(db, workspace, artifact_storage):
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    handler = SyscallHandler(db=db, workspace_path=workspace)
    result = await handler.mediate(
        call=ToolCall(
            id="c1",
            name="artifact_create",
            args={"path": "x.docx", "format": "docx", "spec": {}},
        ),
        session=_session_stub(),
        agent_config=_agent_config(["read_file"]),  # no artifact grants
        run_id="run-art",
    )
    assert result.allowed is False


def test_pptx_build_uses_widescreen_canvas():
    """artifact_create decks default to 16:9 — the modern slide standard,
    not python-pptx's dated 4:3 template. Placeholder widths stretch to the
    canvas so content doesn't bunch left."""
    from io import BytesIO

    from pptx import Presentation

    from agentos.artifacts.formats import pptx

    data = pptx.build(
        {
            "slides": [
                {
                    "layout": "title_content",
                    "title": "T",
                    "blocks": [{"type": "bullets", "items": ["a"]}],
                }
            ]
        },
        ".",
    )
    prs = Presentation(BytesIO(data))
    assert prs.slide_width == 12192000
    assert prs.slide_height == 6858000
    for ph in prs.slides[0].placeholders:
        assert ph.width == prs.slide_width - 2 * ph.left


def test_docx_build_sets_letter_geometry():
    """Page geometry is a deliberate default — US Letter, uniform 1" margins."""
    from io import BytesIO

    import docx

    from agentos.artifacts.formats import docx as docx_fmt

    data = docx_fmt.build({"blocks": [{"type": "paragraph", "text": "hi"}]}, ".")
    section = docx.Document(BytesIO(data)).sections[0]
    assert section.page_width == docx.shared.Inches(8.5)
    assert section.page_height == docx.shared.Inches(11)
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        assert getattr(section, m) == docx.shared.Inches(1)


def test_xlsx_build_sets_print_defaults():
    """Sheets paginate sanely: landscape, fit-to-width, modest margins."""
    from io import BytesIO

    from openpyxl import load_workbook

    from agentos.artifacts.formats import xlsx as xlsx_fmt

    data = xlsx_fmt.build({"sheets": [{"name": "S", "rows": [["a"]]}]}, ".")
    ws = load_workbook(BytesIO(data)).active
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1
    assert ws.page_setup.fitToHeight == 0
    assert ws.page_margins.left == 0.5


def test_xlsx_build_rich_styles_merges_and_filter():
    """Rich cell/sheet styling survives a build → reopen round trip."""
    from io import BytesIO

    from openpyxl import load_workbook

    from agentos.artifacts.formats import xlsx as xlsx_fmt

    data = xlsx_fmt.build(
        {
            "sheets": [
                {
                    "name": "Budget",
                    "rows": [["Item", "Q1"], ["Hosting", 120]],
                    "cells": {
                        "A1": {
                            "value": "Item",
                            "bold": True,
                            "fill": "#1F4E79",
                            "color": "FFFFFF",
                            "align": "center",
                            "border": {"style": "thin", "color": "#CCCCCC"},
                        }
                    },
                    "formats": {"B2": {"number_format": "#,##0.00", "align": "right"}},
                    "merges": ["D1:E1"],
                    "auto_filter": "A1:B2",
                    "row_heights": {"1": 28},
                    "column_widths": {"A": 24},
                    "freeze": "A2",
                }
            ]
        },
        ".",
    )
    wb = load_workbook(BytesIO(data))
    ws = wb["Budget"]
    a1 = ws["A1"]
    assert a1.font.bold is True
    assert a1.font.color.rgb == "00FFFFFF"
    assert a1.fill.fgColor.rgb == "001F4E79"
    assert a1.alignment.horizontal == "center"
    assert a1.border.left.style == "thin"
    assert ws["B2"].number_format == "#,##0.00"
    assert ws["B2"].alignment.horizontal == "right"
    assert "D1:E1" in [str(r) for r in ws.merged_cells.ranges]
    assert ws.auto_filter.ref == "A1:B2"
    assert ws.row_dimensions[1].height == 28
    assert ws.column_dimensions["A"].width == 24
    assert ws.freeze_panes == "A2"


def test_xlsx_revise_style_and_layout_ops():
    from io import BytesIO

    from openpyxl import load_workbook

    from agentos.artifacts.formats import xlsx as xlsx_fmt

    data = xlsx_fmt.build({"sheets": [{"name": "S", "rows": [["h", "v"], [1, 2]]}]}, ".")
    out = xlsx_fmt.revise(
        data,
        [
            {
                "op": "style_range",
                "sheet": "S",
                "range": "A1:B1",
                "style": {"bold": True, "fill": "#EEEEEE", "border": "thin"},
            },
            {"op": "merge_cells", "sheet": "S", "range": "C1:D1"},
            {"op": "set_column_width", "sheet": "S", "col": "A", "width": 30},
            {"op": "set_row_height", "sheet": "S", "row": 3, "height": 22},
            {"op": "set_auto_filter", "sheet": "S", "ref": "A1:B2"},
            {"op": "set_freeze", "sheet": "S", "ref": "A2"},
        ],
        ".",
    )
    ws = load_workbook(BytesIO(out))["S"]
    assert ws["A1"].font.bold is True
    assert ws["B1"].fill.fgColor.rgb == "00EEEEEE"
    assert ws["B1"].border.top.style == "thin"
    assert "C1:D1" in [str(r) for r in ws.merged_cells.ranges]
    assert ws.column_dimensions["A"].width == 30
    assert ws.row_dimensions[3].height == 22
    assert ws.auto_filter.ref == "A1:B2"
    assert ws.freeze_panes == "A2"


def test_xlsx_rejects_invalid_style_values():
    from agentos.artifacts.formats import xlsx as xlsx_fmt

    data = xlsx_fmt.build({"sheets": [{"name": "S", "rows": [["x"]]}]}, ".")
    for bad in (
        {"op": "style_range", "sheet": "S", "range": "A1:A1", "style": {"align": "diagonal"}},
        {"op": "style_range", "sheet": "S", "range": "A1:A1", "style": {"border": "wavy"}},
        {"op": "style_range", "sheet": "S", "range": "A1:A1", "style": {"fill": "not-a-color"}},
    ):
        try:
            xlsx_fmt.revise(data, [bad], ".")
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad}")


async def test_create_structured_lands_under_artifacts_dir(db, workspace, artifact_storage):
    """artifact_create paths are rooted at artifacts/ — the deliverables dir,
    mirroring attachments/ for inputs."""
    from agentos.artifacts import service

    spec = {"blocks": [{"type": "paragraph", "text": "hi"}]}
    art, _ = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="report.docx",
        format="docx",
        spec=spec,
    )
    assert art.current_path == "artifacts/report.docx"
    assert (Path(workspace) / "artifacts/report.docx").exists()


async def test_create_structured_preserves_subdirs_and_prefix(db, workspace, artifact_storage):
    from agentos.artifacts import service

    spec = {"blocks": [{"type": "paragraph", "text": "hi"}]}
    nested, _ = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="reports/q3.docx",
        format="docx",
        spec=spec,
    )
    assert nested.current_path == "artifacts/reports/q3.docx"

    already, _ = await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="artifacts/explicit.docx",
        format="docx",
        spec=spec,
    )
    assert already.current_path == "artifacts/explicit.docx"


async def test_create_structured_refuses_attachments_dir(db, workspace, artifact_storage):
    from agentos.artifacts import service

    with pytest.raises(service.ArtifactError, match="attachments"):
        await service.create_structured(
            db,
            workspace_id="agent-1",
            workspace_path=workspace,
            rel_path="attachments/upload.docx",
            format="docx",
            spec={"blocks": [{"type": "paragraph", "text": "hi"}]},
        )


async def test_mediated_restore_adopt_carry_provenance(db, workspace, artifact_storage):
    """Regression: artifact_restore used to TypeError on the
    source_message_id provenance key; adopt also drops run/call
    without the threading. Every mediated writer must carry
    run/call/subagent onto its revisions."""
    from sqlalchemy import select

    from agentos.models.artifact import ArtifactRevision
    from agentos.syscall.mediator import SyscallHandler
    from agentos.syscall.protocol import ToolCall

    handler = SyscallHandler(db=db, workspace_path=workspace)
    config = _agent_config(
        [
            "artifact_create",
            "artifact_revise",
            "artifact_restore",
            "artifact_adopt",
            "write_file",
        ]
    )
    session = _session_stub()

    created = await handler.mediate(
        call=ToolCall(
            id="call-c",
            name="artifact_create",
            args={
                "path": "out.docx",
                "format": "docx",
                "spec": {"blocks": [{"type": "heading", "level": 1, "text": "Hi"}]},
            },
        ),
        session=session,
        agent_config=config,
        run_id="run-prov",
        sub_agent_id="sub-p",
    )
    art_id = created.output["artifact_id"]
    rev1 = created.output["revision_id"]

    revised = await handler.mediate(
        call=ToolCall(
            id="call-r",
            name="artifact_revise",
            args={
                "artifact_id": art_id,
                "base_revision_id": rev1,
                "ops": [{"op": "append_blocks", "blocks": [{"type": "paragraph", "text": "b"}]}],
            },
        ),
        session=session,
        agent_config=config,
        run_id="run-prov",
        sub_agent_id="sub-p",
    )
    rev2 = revised.output["revision_id"]

    restored = await handler.mediate(
        call=ToolCall(
            id="call-rest",
            name="artifact_restore",
            args={"artifact_id": art_id, "revision_id": rev1},
        ),
        session=session,
        agent_config=config,
        run_id="run-prov",
        sub_agent_id="sub-p",
    )
    assert restored.allowed, restored
    rev3 = restored.output["revision_id"]

    # Adopt an existing workspace file.
    import pathlib

    (pathlib.Path(workspace) / "plain.txt").write_text("plain")
    adopted = await handler.mediate(
        call=ToolCall(
            id="call-a",
            name="artifact_adopt",
            args={"path": "plain.txt"},
        ),
        session=session,
        agent_config=config,
        run_id="run-prov",
    )
    assert adopted.allowed
    adopt_rev = adopted.output["revision_id"]

    revs = {
        r.id: r
        for r in (
            await db.execute(
                select(ArtifactRevision).where(
                    ArtifactRevision.id.in_([rev1, rev2, rev3, adopt_rev])
                )
            )
        ).scalars()
    }
    assert revs[rev1].call_id == "call-c" and revs[rev1].sub_agent_id == "sub-p"
    assert revs[rev2].call_id == "call-r" and revs[rev2].sub_agent_id == "sub-p"
    assert revs[rev3].call_id == "call-rest" and revs[rev3].source_run_id == "run-prov"
    assert revs[adopt_rev].call_id == "call-a" and revs[adopt_rev].source_run_id == "run-prov"


FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_fixture_pptx_decks_inspect_cleanly():
    from agentos.artifacts.formats import pptx

    for name in (
        "analysis-deck.pptx",
        "analysis-deck-longtitle.pptx",
        "deck-vietnamese.pptx",
        "analysis-deck-external-edit.pptx",
    ):
        info = pptx.inspect(_fixture_bytes(name))
        assert info["structure"]["slides"] > 0, name


def test_fixture_docx_reports_inspect_cleanly():
    from agentos.artifacts.formats import docx

    for name in ("report.docx", "report-vietnamese.docx"):
        info = docx.inspect(_fixture_bytes(name))
        assert info["structure"]["headings"], name
        assert docx.validate(_fixture_bytes(name))["valid"], name


def test_fixture_xlsx_inspect_reports_sheets_and_formulas():
    from agentos.artifacts.formats import xlsx

    info = xlsx.inspect(_fixture_bytes("workbook.xlsx"))
    assert info["structure"]["sheets"] == ["Summary", "Weekly", "Notes"]
    assert info["structure"]["formulas"] > 0


def test_fixture_manifest_covers_all_files():
    import json

    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    on_disk = {p.name for p in FIXTURES.iterdir() if p.is_file() and p.name != "manifest.json"}
    recorded = {f["file"] for f in manifest["files"]}
    assert on_disk == recorded | {"generate.py", "fixture_variants.py", "README.md"}
    for entry in manifest["files"]:
        data = (FIXTURES / entry["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["file"]
        assert len(data) == entry["bytes"], entry["file"]
    asset = manifest["asset"]
    assert hashlib.sha256((FIXTURES / asset["file"]).read_bytes()).hexdigest() == asset["sha256"]


async def test_fixture_external_deck_conflict_preserves_both_byte_versions(
    db, workspace, artifact_storage
):
    from agentos.artifacts import service

    original = _fixture_bytes("analysis-deck.pptx")
    external = _fixture_bytes("analysis-deck-external-edit.pptx")
    art, revision = await service.create(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="deck.pptx",
        data=original,
    )
    target = Path(workspace) / "deck.pptx"
    target.write_bytes(external)
    with pytest.raises(service.ArtifactConflictError):
        await service.revise_structured(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=revision.id,
            ops=[{"op": "set_title", "slide": 0, "text": "Agent draft must not overwrite"}],
        )
    assert target.read_bytes() == external
    assert await service.revision_bytes(db, revision.id) == original
    assert len(await service.history(db, art.id)) == 1


async def test_fixture_uploaded_workbook_adoption_retains_exact_original(
    db, workspace, artifact_storage
):
    from io import BytesIO

    from openpyxl import load_workbook

    from agentos.artifacts import service

    original = _fixture_bytes("uploaded-features.xlsx")
    target = Path(workspace) / "uploaded.xlsx"
    target.write_bytes(original)
    art, base = await service.adopt(
        db, workspace_id="agent-1", workspace_path=workspace, rel_path="uploaded.xlsx"
    )
    revised = await service.revise_structured(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=base.id,
        ops=[{"op": "set_cell", "sheet": "Summary", "cell": "B2", "value": 60}],
    )
    assert await service.revision_bytes(db, base.id) == original
    book = load_workbook(BytesIO(await service.revision_bytes(db, revised.id)))
    assert book["Summary"]["B2"].value == 60
    assert book["Notes"]["B3"].value == "=SUM(Summary!B2:C2)"
    assert "WeeklyMetrics" in book["Weekly"].tables
    assert len(book["Weekly"].data_validations.dataValidation) == 1
    assert len(book["Weekly"].conditional_formatting) == 1
