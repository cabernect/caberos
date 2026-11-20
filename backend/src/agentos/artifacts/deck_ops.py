"""ID-addressed presentation transactions. No database or DOM dependencies."""

import copy
import hashlib
import json
import uuid

from .deck_spec import normalize

_FIELDS = {
    "set_title": {"title"},
    "set_theme": {"theme"},
    "set_motion": {"motion"},
    "add_slide": {"slide", "value", "index", "new_id"},
    "move_slide": {"from", "to"},
    "duplicate_slide": {"new_id"},
    "set_slide": {"value"},
    "remove_slide": set(),
    "set_slide_title": {"value"},
    "set_slide_layout": {"value"},
    "set_notes": {"value"},
    "add_block": {"value", "after", "new_id"},
    "remove_block": set(),
    "move_block": {"to"},
    "replace_block": {"value"},
    "set_block": {"value"},
    "set_text": {"value"},
    "set_bullets": {"value"},
    "set_table": {"value"},
}


def content_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def index_of(items: list, ref) -> int:
    if type(ref) is int and 0 <= ref < len(items):
        return ref
    matches = [i for i, item in enumerate(items) if item.get("id") == ref]
    if len(matches) != 1:
        raise ValueError(f"unknown slide id or block id: {ref}")
    return matches[0]


def prepare_ops(ops: list[dict]) -> list[dict]:
    if not isinstance(ops, list) or not 1 <= len(ops) <= 200:
        raise ValueError("an edit transaction needs 1-200 operations")
    result = copy.deepcopy(ops)
    for op in result:
        if not isinstance(op, dict):
            raise ValueError("each operation must be an object")
        kind = op.get("op")
        if kind not in _FIELDS:
            raise ValueError(f"unknown deck op: {kind}")
        allowed = {"op", "slide", "slide_id", "block", "block_id", "expected_block_hash"}
        if set(op) - allowed - _FIELDS[kind]:
            raise ValueError(f"unknown fields for {kind}")
        if op.get("op") in {"add_slide", "add_block", "duplicate_slide"}:
            op.setdefault("new_id", uuid.uuid4().hex)
    return result


def apply_ops(spec: dict, ops: list[dict]) -> dict:
    result = copy.deepcopy(spec)
    for op in prepare_ops(ops):
        kind = op.get("op")
        if kind == "set_title":
            result["title"] = op["title"]
            continue
        if kind == "set_theme":
            result["theme"] = op["theme"]
            continue
        if kind == "set_motion":
            result["motion"] = op["motion"]
            continue
        slides = result["slides"]
        if kind == "add_slide":
            slide = copy.deepcopy(op.get("value", op.get("slide")))
            if not isinstance(slide, dict):
                raise ValueError("add_slide requires a slide object")
            slide.setdefault("id", op["new_id"])
            position = len(slides) if op.get("index") is None else index_of(slides, op["index"]) + 1
            slides.insert(position, slide)
            continue
        if kind == "move_slide":
            slide = slides.pop(index_of(slides, op["from"]))
            to = op["to"]
            slides.insert(
                min(max(to, 0), len(slides)) if type(to) is int else index_of(slides, to), slide
            )
            continue
        si = index_of(slides, op.get("slide_id", op.get("slide")))
        slide = slides[si]
        if kind == "remove_slide":
            slides.pop(si)
        elif kind == "duplicate_slide":
            duplicate = copy.deepcopy(slide)
            duplicate["id"] = op["new_id"]
            for bi, block in enumerate(duplicate.get("blocks", [])):
                block["id"] = f"{op['new_id']}.b{bi + 1}"
            slides.insert(si + 1, duplicate)
        elif kind == "set_slide":
            value = copy.deepcopy(op["value"])
            if value.get("id", slide["id"]) != slide["id"]:
                raise ValueError("set_slide cannot change a slide identity")
            value["id"] = slide["id"]
            slides[si] = value
        elif kind in {"set_slide_title", "set_slide_layout", "set_notes"}:
            field = {
                "set_slide_title": "title",
                "set_slide_layout": "layout",
                "set_notes": "notes",
            }[kind]
            slide[field] = op["value"]
        else:
            blocks = slide.setdefault("blocks", [])
            if kind == "add_block":
                block = copy.deepcopy(op["value"])
                block.setdefault("id", op["new_id"])
                position = (
                    len(blocks) if op.get("after") is None else index_of(blocks, op["after"]) + 1
                )
                blocks.insert(position, block)
                continue
            bi = index_of(blocks, op.get("block_id", op.get("block")))
            block = blocks[bi]
            if op.get("expected_block_hash") and content_hash(block) != op["expected_block_hash"]:
                raise ValueError(f"block changed: {block['id']}")
            if kind == "remove_block":
                blocks.pop(bi)
            elif kind == "move_block":
                block = blocks.pop(bi)
                to = op["to"]
                position = min(max(to, 0), len(blocks)) if type(to) is int else index_of(blocks, to)
                blocks.insert(position, block)
            elif kind == "replace_block":
                replacement = copy.deepcopy(op["value"])
                if replacement.get("id", block["id"]) != block["id"]:
                    raise ValueError("replace_block cannot change a block identity")
                replacement["id"] = block["id"]
                blocks[bi] = replacement
            elif kind == "set_block":
                changes = op["value"]
                if not isinstance(changes, dict) or {"id", "type"} & changes.keys():
                    raise ValueError("set_block cannot change identity or type")
                block.update(copy.deepcopy(changes))
            elif kind == "set_text" and block["type"] in {"heading", "paragraph"}:
                block["text"] = op["value"]
            elif kind == "set_bullets" and block["type"] == "bullets":
                block["items"] = op["value"]
            elif kind == "set_table" and block["type"] == "table":
                block["rows"] = op["value"]
            else:
                raise ValueError(f"unsupported deck operation or block type: {kind}")
    assets = result.get("assets", [])
    return {**normalize(result), "assets": assets}
