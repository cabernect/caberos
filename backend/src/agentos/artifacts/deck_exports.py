"""Revision-snapshot export policy shared by HTTP adapters and tests."""

import hashlib
import json
from io import BytesIO

from . import deck_pptx, deck_render
from .deck_spec import normalize

RENDERER_VERSION = "caberos-deck-3"


def plan(spec: dict, source_sha256: str) -> dict:
    normalized = normalize(spec)
    for index, slide in enumerate(normalized["slides"], 1):
        for block in slide.get("blocks", []):
            if block["type"] == "image":
                try:
                    deck_pptx._image_bytes(block, spec, None)
                except (ValueError, OSError) as exc:
                    raise ValueError(f"slide {index}: {exc}") from exc
    reasons = {}
    for index, slide in enumerate(normalized["slides"]):
        single = {**spec, "slides": [slide]}
        try:
            deck_pptx.build(single)
        except deck_pptx.NativeLayoutError as exc:
            reasons[index] = exc.reason
        except ValueError as exc:
            reasons[index] = str(exc)
    declared_motion = bool(normalized.get("motion")) or any(
        slide.get("transition")
        or any(block.get("animation") or block.get("reveal") for block in slide.get("blocks", []))
        for slide in normalized["slides"]
    )
    result = {
        "source_sha256": source_sha256,
        "renderer_version": RENDERER_VERSION,
        "image_fallbacks": [{"slide": i + 1, "reason": reason} for i, reason in reasons.items()],
        "browser_motion_exported": False,
        "declared_motion": declared_motion,
    }
    result["plan_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


async def pptx(spec, *, source_sha256, revision_id, allow_fallback=False, expected_plan=None):
    import asyncio

    assessment = await asyncio.to_thread(plan, spec, source_sha256)
    reasons = {row["slide"] - 1: row["reason"] for row in assessment["image_fallbacks"]}
    if reasons and (not allow_fallback or expected_plan != assessment["plan_hash"]):
        raise ValueError("Image slides require approval of the current export plan before download")
    images = await deck_render.render(spec, slides=list(reasons)) if reasons else {}
    content = await asyncio.to_thread(
        deck_pptx.export_pptx,
        spec,
        source_sha256=source_sha256,
        revision_id=revision_id,
        fallback_images=images,
        fallback_reasons=reasons,
    )
    return content, assessment


async def pdf(spec, *, source_sha256, revision_id):
    from pypdf import PdfReader, PdfWriter

    content = await deck_render.render(spec, pdf=True)
    reader = PdfReader(BytesIO(content))
    if len(reader.pages) != len(spec["slides"]):
        raise ValueError("PDF page count does not match this presentation revision")
    if any(abs(float(p.mediabox.width / p.mediabox.height) - 16 / 9) > 0.005 for p in reader.pages):
        raise ValueError("PDF pages do not match the fixed 16:9 canvas")
    writer = PdfWriter(clone_from=reader)
    writer.add_metadata(
        {
            "/Title": spec["title"],
            "/CaberOSSourceSHA256": source_sha256,
            "/CaberOSRevision": revision_id or "live snapshot",
            "/CaberOSRenderer": RENDERER_VERSION,
        }
    )
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
