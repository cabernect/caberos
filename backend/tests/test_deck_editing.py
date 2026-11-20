"""Agent-only edits: targeted transactions, base checks, and history."""

import copy
import json
from pathlib import Path

import pytest

from agentos.artifacts import service
from agentos.artifacts.formats import deck


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    from agentos.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")


def spec():
    return {
        "title": "Editing",
        "slides": [
            {
                "id": "intro",
                "title": "Before",
                "blocks": [
                    {"id": "lead", "type": "paragraph", "text": "Original"},
                    {"id": "keep", "type": "bullets", "items": ["Untouched"]},
                ],
                "notes": "Private speaker note",
            },
            {"id": "second", "title": "Second", "blocks": []},
        ],
    }


async def make(db, workspace):
    return await service.create_structured(
        db,
        workspace_id="agent-1",
        workspace_path=workspace,
        rel_path="editing.deck.json",
        format="deck",
        spec=spec(),
        created_by="agent-1",
    )


def text_op(text):
    return {"op": "set_text", "slide_id": "intro", "block_id": "lead", "value": text}


async def test_targeted_batch_is_atomic_and_preserves_unrelated_content(db, workspace):
    art, first = await make(db, workspace)
    before = await service.revision_bytes(db, first.id)
    revision = await service.revise_structured(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=first.id,
        created_by="agent-1",
        ops=[text_op("Edited")],
    )
    expected = copy.deepcopy(json.loads(before))
    expected["slides"][0]["blocks"][0]["text"] = "Edited"
    assert json.loads(await service.revision_bytes(db, revision.id)) == expected
    with pytest.raises(ValueError):
        await service.revise_structured(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=revision.id,
            ops=[
                text_op("Must not save"),
                {"op": "remove_block", "slide_id": "intro", "block_id": "missing"},
            ],
        )
    assert (Path(workspace) / art.current_path).read_bytes() == await service.revision_bytes(
        db, revision.id
    )
    assert len(await service.history(db, art.id)) == 2


async def test_stale_edits_and_restores_fail_after_identical_bytes_are_restored(db, workspace):
    art, first = await make(db, workspace)
    artifact_id = art.id
    second = await service.revise_structured(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=first.id,
        ops=[text_op("New wording")],
    )
    with pytest.raises(service.ArtifactConflictError):
        await service.revise_structured(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=first.id,
            ops=[text_op("Stale wording")],
        )
    restored = await service.restore(
        db,
        art.id,
        workspace_path=workspace,
        revision_id=first.id,
        base_revision_id=second.id,
    )
    assert restored.revision_number == 3
    assert restored.base_revision_id == second.id
    assert await service.revision_bytes(db, restored.id) == await service.revision_bytes(
        db, first.id
    )
    with pytest.raises(service.ArtifactConflictError):
        await service.revise_structured(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=first.id,
            ops=[text_op("Old base, same bytes")],
        )
    with pytest.raises(service.ArtifactConflictError):
        await service.restore(
            db,
            art.id,
            workspace_path=workspace,
            revision_id=second.id,
            base_revision_id=first.id,
        )
    assert len(await service.history(db, artifact_id)) == 3


async def test_external_file_edits_are_not_overwritten(db, workspace):
    art, first = await make(db, workspace)
    target = Path(workspace) / art.current_path
    external = target.read_text().replace("Original", "External wording")
    target.write_text(external)
    with pytest.raises(service.ArtifactConflictError):
        await service.revise_structured(
            db,
            art.id,
            workspace_path=workspace,
            base_revision_id=first.id,
            ops=[text_op("Agent wording")],
        )
    assert target.read_text() == external
    assert len(await service.history(db, art.id)) == 1


async def test_agent_with_current_base_applies_edit_without_proposal_gate(db, workspace):
    from agentos.capabilities.tools.artifact import artifact_revise

    art, first = await make(db, workspace)
    latest = await service.revise_structured(
        db,
        art.id,
        workspace_path=workspace,
        base_revision_id=first.id,
        created_by="operator:owner",
        ops=[text_op("Current wording")],
    )
    result = await artifact_revise(
        {
            "artifact_id": art.id,
            "base_revision_id": latest.id,
            "ops": [text_op("Requested wording")],
        },
        workspace,
        db=db,
        agent_id="agent-1",
    )
    assert result["revision_number"] == 3
    assert "error" not in result and "review_required" not in result
    assert "Requested wording" in (Path(workspace) / art.current_path).read_text()


def test_revision_reuses_pinned_images_after_workspace_image_is_removed(tmp_path):
    from PIL import Image

    image = tmp_path / "image.png"
    Image.new("RGB", (8, 8), "blue").save(image)
    source = deck.build(
        {
            "slides": [
                {
                    "id": "s",
                    "blocks": [
                        {"id": "image", "type": "image", "src": "image.png"},
                    ],
                }
            ]
        },
        tmp_path,
    )
    image.unlink()
    changed = deck.revise(source, [{"op": "set_title", "title": "Same image"}], tmp_path)
    assert json.loads(changed)["assets"] == json.loads(source)["assets"]


def test_hash_precondition_and_unknown_fields_fail_without_mutating_input(tmp_path):
    source = deck.build(spec(), tmp_path)
    with pytest.raises(ValueError, match="block changed"):
        deck.revise(source, [{**text_op("No"), "expected_block_hash": "stale"}], tmp_path)
    with pytest.raises(ValueError, match="unknown"):
        deck.revise(
            source,
            [
                {
                    "op": "set_block",
                    "slide_id": "intro",
                    "block_id": "lead",
                    "value": {"html": "<script>"},
                }
            ],
            tmp_path,
        )
    assert json.loads(source)["slides"][0]["blocks"][0]["text"] == "Original"
