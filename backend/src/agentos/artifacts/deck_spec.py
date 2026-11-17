"""The presentation model shared by HTML playback and native PPTX rendering."""

import json
import math
import re

MAX_SLIDES = 100
SPEC_VERSION = 1
LAYOUTS = {"title", "content", "two_content", "section"}
BLOCK_TYPES = {"heading", "paragraph", "bullets", "table", "image", "divider", "chart"}
_MAX_CONTENT_CHARS = 200_000
_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")
_BLOCK_FIELDS = {
    "heading": {"text"},
    "paragraph": {"text"},
    "bullets": {"items"},
    "table": {"rows"},
    "image": {"src", "alt"},
    "divider": set(),
    "chart": {"chart_type", "categories", "series"},
}


def _validate_block(block: dict) -> None:
    common = {"type", "id", "column", "reveal", "animation"}
    unknown = set(block) - common - _BLOCK_FIELDS[block["type"]]
    if unknown:
        raise ValueError(f"unknown {block['type']} fields: {sorted(unknown)}")
    if "column" in block and (type(block["column"]) is not int or block["column"] not in (0, 1)):
        raise ValueError("block column must be 0 or 1")
    for field in ("text", "alt"):
        if field in block and not isinstance(block[field], str):
            raise ValueError(f"block {field} must be plain text")
    if block["type"] == "bullets":
        items = block.get("items", [])
        if (
            not isinstance(items, list)
            or len(items) > 100
            or any(not isinstance(v, str) for v in items)
        ):
            raise ValueError("bullets need at most 100 plain text items")
    if block["type"] == "table":
        rows = block.get("rows")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError("table needs 1-100 rows")
        for row in rows:
            if not isinstance(row, list) or not 1 <= len(row) <= 12:
                raise ValueError("table rows need 1-12 cells")
            if any(
                not isinstance(v, (str, int, float, bool, type(None)))
                or (isinstance(v, float) and not math.isfinite(v))
                for v in row
            ):
                raise ValueError("table cells must be finite scalar values")
    if block["type"] == "image":
        src = block.get("src")
        if not isinstance(src, str) or not src:
            raise ValueError("image needs a workspace-relative src")
        if src.startswith("data:") and not any(
            src.startswith(f"data:image/{fmt};base64,") for fmt in ("png", "jpeg", "gif", "webp")
        ):
            raise ValueError("only embedded raster images are supported")
        if "://" in src:
            raise ValueError("external image URLs are not supported")
    if block["type"] == "chart":
        kind = block.get("chart_type", "bar")
        categories, series = block.get("categories"), block.get("series")
        if kind not in {"bar", "line", "pie"}:
            raise ValueError("chart_type must be bar, line, or pie")
        if (
            not isinstance(categories, list)
            or not 1 <= len(categories) <= 24
            or any(not isinstance(c, str) for c in categories)
        ):
            raise ValueError("charts need 1-24 text categories")
        if not isinstance(series, list) or not 1 <= len(series) <= (1 if kind == "pie" else 6):
            raise ValueError("chart series count is unsupported")
        for entry in series:
            if not isinstance(entry, dict) or set(entry) - {"name", "values"}:
                raise ValueError("chart series need name and values")
            values = entry.get("values")
            if (
                not isinstance(entry.get("name"), str)
                or not isinstance(values, list)
                or len(values) != len(categories)
            ):
                raise ValueError("chart series must match the categories")
            if any(
                type(v) not in (float, int) or not math.isfinite(v) or (kind == "pie" and v < 0)
                for v in values
            ):
                raise ValueError("chart values must be finite numbers (nonnegative for pie)")
        if kind == "pie" and sum(series[0]["values"]) <= 0:
            raise ValueError("pie charts need a positive total")
        if kind == "pie" and len(categories) > 12:
            raise ValueError("pie charts support at most 12 categories")


def _effect(value, *, transition=False) -> dict:
    types = {"none", "fade", "slide"} if transition else {"none", "fade", "rise"}
    if not isinstance(value, dict) or set(value) - {"type", "duration_ms"}:
        raise ValueError("motion effect must contain only type and duration_ms")
    kind = value.get("type", "fade")
    duration = value.get("duration_ms", 300)
    if not isinstance(kind, str) or kind not in types:
        raise ValueError(f"unsupported motion effect: {kind!r}")
    if type(duration) is not int or not 0 <= duration <= 2000:
        raise ValueError("motion duration_ms must be an integer from 0 to 2000")
    return {"type": kind, "duration_ms": duration}


def normalize_theme(spec: dict) -> dict[str, str]:
    theme = spec.get("theme") or {}
    if not isinstance(theme, dict):
        raise ValueError("theme must be an object")
    unknown = set(theme) - {"background", "accent", "text", "font"}
    if unknown:
        raise ValueError(f"unknown theme keys: {sorted(unknown)}")
    out = {}
    for key, value in theme.items():
        if not isinstance(value, str):
            continue
        if key == "font":
            if value not in {"sans", "serif", "mono"}:
                raise ValueError(f"unknown theme font: {value!r} (sans|serif|mono)")
        else:
            if not _HEX.fullmatch(value.strip()):
                raise ValueError(f"theme.{key} must be RRGGBB hex, got {value!r}")
            value = "#" + value.strip().lstrip("#").lower()
        out[key] = value
    return out


def normalize(spec: dict) -> dict:
    """Normalize content, not per-format geometry. Asset bytes have separate budgets."""
    if not isinstance(spec, dict):
        raise ValueError("deck spec must be an object")
    if spec.get("kind", "deck") != "deck":
        raise ValueError("presentation kind must be deck")
    version = spec.get("version", SPEC_VERSION)
    if type(version) is not int or version != SPEC_VERSION:
        raise ValueError(f"unsupported deck spec version: {version!r} (supported: {SPEC_VERSION})")
    content = {key: value for key, value in spec.items() if key != "assets"}
    if len(json.dumps(content, default=str)) > _MAX_CONTENT_CHARS:
        raise ValueError("deck spec exceeds size limit")
    assets = spec.get("assets") or []
    if not isinstance(assets, list) or len(assets) > 20:
        raise ValueError("deck assets must be a list of at most 20 snapshots")
    seen_paths = set()
    encoded_bytes = 0
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            raise ValueError("deck asset needs a path")
        if asset["path"] in seen_paths:
            raise ValueError("duplicate deck asset path")
        seen_paths.add(asset["path"])
        uri = asset.get("data_uri", "")
        if not isinstance(uri, str) or len(uri) > 6 * 1024 * 1024:
            raise ValueError("deck asset snapshot exceeds encoding budget")
        encoded_bytes += len(uri)
    if encoded_bytes > 36 * 1024 * 1024:
        raise ValueError("deck asset snapshots exceed total encoding budget")
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("deck spec needs a non-empty slides[]")
    if len(slides) > MAX_SLIDES:
        raise ValueError(f"deck exceeds {MAX_SLIDES} slides")
    normalized = []
    seen = set()
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            raise ValueError(f"slide {index} must be an object")
        if set(slide) - {"id", "title", "layout", "blocks", "notes", "transition"}:
            raise ValueError(f"slide {index} has unknown fields")
        if any(key in slide and not isinstance(slide[key], str) for key in ("title", "notes")):
            raise ValueError("slide title and notes must be plain text")
        sid = str(slide.get("id") or f"s{index + 1}")
        if sid in seen:
            raise ValueError(f"duplicate slide id: {sid}")
        layout = slide.get("layout", "content")
        if layout not in LAYOUTS:
            raise ValueError(f"slide {index} unknown layout: {layout!r}")
        blocks = slide.get("blocks") or []
        if not isinstance(blocks, list):
            raise ValueError(f"slide {index} blocks must be a list")
        normalized_blocks = []
        block_ids = set()
        for bi, block in enumerate(blocks):
            if not isinstance(block, dict) or block.get("type") not in BLOCK_TYPES:
                raise ValueError(f"slide {index} has an unsupported block")
            block = dict(block)
            _validate_block(block)
            bid = str(block.get("id") or f"{sid}.b{bi + 1}")
            if bid in block_ids:
                raise ValueError(f"slide {index} duplicate block id: {bid}")
            block_ids.add(bid)
            block["id"] = bid
            reveal = block.get("reveal", False)
            if not isinstance(reveal, bool) and reveal != "items":
                raise ValueError("block reveal must be true, false, or 'items'")
            if reveal == "items" and block["type"] != "bullets":
                raise ValueError("reveal 'items' is only supported on bullets")
            if "animation" in block:
                block["animation"] = _effect(block["animation"])
            normalized_blocks.append(block)
        seen.add(sid)
        normalized_slide = {**slide, "id": sid, "layout": layout, "blocks": normalized_blocks}
        if "transition" in slide:
            normalized_slide["transition"] = _effect(slide["transition"], transition=True)
        normalized.append(normalized_slide)
    motion = spec.get("motion", {})
    if not isinstance(motion, dict) or set(motion) - {"transition", "entrance"}:
        raise ValueError("motion accepts only transition and entrance")
    normalized_motion = {
        key: _effect(value, transition=key == "transition") for key, value in motion.items()
    }
    return {
        "kind": "deck",
        "version": SPEC_VERSION,
        "title": str(spec.get("title") or "Untitled deck"),
        "theme": normalize_theme(spec),
        "slides": normalized,
        **({"motion": normalized_motion} if "motion" in spec else {}),
    }
