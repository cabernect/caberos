"""Deck handler — canonical .deck.json presentation source.

The spec IS the deliverable: agents and operators edit this JSON; the HTML
player and the PPTX renderer are derived views. Image blocks reference
workspace-relative raster files which are embedded here as pinned data-URI
snapshots so revisions never reread mutable workspace bytes.
"""

import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from ...sandbox.workspace import resolve_within
from ..deck_ops import apply_ops, content_hash
from ..deck_spec import normalize

MAX_ASSETS = 20
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_ASSET_TOTAL = 25 * 1024 * 1024
_RASTER = {"PNG", "JPEG", "GIF", "WEBP"}
_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}


def _asset_refs(spec: dict) -> list[str]:
    refs = []
    for slide in spec.get("slides") or []:
        for block in slide.get("blocks") or []:
            if block.get("type") == "image":
                src = str(block.get("src", ""))
                if src and not src.startswith("data:") and src not in refs:
                    refs.append(src)
    return refs


def _snapshot(src: str, workspace_path) -> dict:
    path = resolve_within(workspace_path, src)
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(f"image exceeds 4MB: {src}")
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"image exceeds 4MB: {src}")
    try:
        with Image.open(BytesIO(data)) as image:
            fmt = image.format
            image.verify()
    except Exception as e:
        raise ValueError(f"image unreadable: {src}") from e
    if fmt not in _RASTER:
        raise ValueError(f"unsupported image format for {src}: {fmt}")
    return {
        "path": src,
        "mime": _MIME[fmt],
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_uri": "data:" + _MIME[fmt] + ";base64," + base64.b64encode(data).decode(),
    }


def _with_assets(spec: dict, workspace_path) -> dict:
    """Normalize + pin every referenced image as an embedded snapshot."""
    norm = normalize(spec)
    refs = _asset_refs(norm)
    if len(refs) > MAX_ASSETS:
        raise ValueError(f"deck exceeds {MAX_ASSETS} image assets")
    assets = []
    total = 0
    snapshots = {a["path"]: a for a in spec.get("assets", [])}
    for src in refs:
        entry = snapshots.get(src)
        if entry is None:
            entry = _snapshot(src, workspace_path)
        else:
            from ..deck_pptx import _image_bytes

            _image_bytes({"src": src}, {"assets": [entry]}, None)
        total += entry["bytes"]
        if total > MAX_ASSET_TOTAL:
            raise ValueError("deck images exceed 25MB total")
        assets.append(entry)
    norm["assets"] = assets
    return norm


def _canonical(spec: dict) -> bytes:
    return (json.dumps(spec, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _load(data: bytes) -> dict:
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"not a readable deck spec: {e}") from e
    spec = normalize(raw)
    spec["assets"] = raw.get("assets") or []
    return spec


def build(spec: dict, workspace_path: str | Path) -> bytes:
    return _canonical(_with_assets(spec, workspace_path))


def _slide_index(slides: list, ref) -> int:
    if isinstance(ref, int) and not isinstance(ref, bool):
        if 0 <= ref < len(slides):
            return ref
        raise ValueError(f"slide index out of range: {ref}")
    sid = str(ref)
    for i, slide in enumerate(slides):
        if slide.get("id") == sid:
            return i
    raise ValueError(f"unknown slide id: {sid}")


def revise(data: bytes, ops: list[dict], workspace_path: str | Path) -> bytes:
    """Apply targeted ops to the canonical spec — never a DOM round-trip."""
    return _canonical(_with_assets(apply_ops(_load(data), ops), workspace_path))


def inspect(data: bytes) -> dict:
    spec = _load(data)
    return {
        "structure": {
            "title": spec["title"],
            "slides": len(spec["slides"]),
            "slide_ids": [s["id"] for s in spec["slides"]],
            "layouts": [s.get("layout", "content") for s in spec["slides"]],
            "blocks": [
                {
                    "slide_id": s["id"],
                    "blocks": [
                        {"id": b["id"], "type": b["type"], "hash": content_hash(b)}
                        for b in s.get("blocks", [])
                    ],
                }
                for s in spec["slides"]
            ],
            "theme": sorted(spec["theme"]) if spec["theme"] else None,
            "assets": [
                {k: a[k] for k in ("path", "mime", "bytes", "sha256")}
                for a in spec.get("assets") or []
            ],
            "notes": sum(1 for s in spec["slides"] if s.get("notes")),
            "reveal_blocks": sum(
                1
                for s in spec["slides"]
                for b in s.get("blocks") or []
                if isinstance(b, dict) and b.get("reveal")
            ),
        }
    }


def validate(data: bytes) -> dict:
    try:
        _load(data)
    except ValueError as e:
        return {"valid": False, "errors": [str(e)]}
    return {"valid": True, "errors": []}
