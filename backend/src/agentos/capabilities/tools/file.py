"""File capability implementations — read_file, write_file, search_files.

All paths are validated against the workspace boundary before execution (D29).
search_files merges the old file_search (grep), file_glob (find by pattern),
and file_list (list directory) into one tool with a `mode` parameter.
"""

import base64
import fnmatch
import io
import mimetypes
import os
import re
from typing import Any

from ...previews import classify
from ...sandbox.workspace import WorkspaceManager

# Hard ceiling on text returned to the model — same budget as web_fetch's
# 50k char cap. Larger inputs must be paged (line/page ranges) or the run
# risks a context-window overflow the harness cannot recover from.
_READ_MAX_CHARS = 50_000

# Vision-input guards: providers commonly cap ~20 MB/request and work best
# near ~1.5k px. Images beyond this are downscaled, not sent raw.
_IMAGE_MAX_EDGE = 1568
_IMAGE_MAX_INPUT_BYTES = 15 * 1024 * 1024

_DOC_FORMATS = {"document": "docx", "slides": "pptx", "workbook": "xlsx"}


def _looks_binary(head: bytes) -> bool:
    """Sniff the first chunk for NUL bytes / heavy control characters."""
    if b"\x00" in head:
        return True
    if not head:
        return False
    controls = sum(1 for b in head if b < 9 or (13 < b < 32))
    return controls / len(head) > 0.05


def _elements_to_text(elements: list[dict]) -> str:
    """Normalized render elements → plain text the model can read."""
    lines: list[str] = []
    for el in elements:
        t = el["type"]
        if t == "heading":
            lines.append("#" * min(el.get("level", 1), 6) + " " + el.get("text", ""))
        elif t == "paragraph":
            lines.append(el.get("text", ""))
        elif t == "list":
            for i, item in enumerate(el.get("items", []), 1):
                marker = f"{i}." if el.get("style") == "number" else "-"
                lines.append(f"{marker} {item}")
        elif t == "table":
            if el.get("header"):
                lines.append(" | ".join(str(c) for c in el["header"]))
            for row in el.get("rows", []):
                lines.append(" | ".join(str(c) for c in row))
        elif t == "image":
            lines.append("[image]")
        elif t == "chart":
            series = el.get("series") or []
            lines.append(f"[chart: {len(series)} series]")
        elif t == "notes":
            lines.append(f"[notes] {el.get('text', '')}")
        elif t == "page_break":
            lines.append("\n---\n")
    return "\n".join(lines)


def _read_office(path: str, rel: str, fmt: str) -> dict[str, Any]:
    """DOCX/PPTX/XLSX → extracted text via the artifact element pipeline —
    never raw binary, always capped."""
    from ...artifacts import formats

    with open(path, "rb") as f:
        data = f.read()
    try:
        elements = formats.get_handler(fmt).to_elements(data, "")
    except Exception as e:
        return {"error": f"{fmt.upper()} unreadable: {e}", "path": rel}
    text = _elements_to_text(elements)
    result: dict[str, Any] = {
        "content": text[:_READ_MAX_CHARS],
        "path": rel,
        "format": fmt,
        "extracted": "text",
    }
    if len(text) > _READ_MAX_CHARS:
        result["truncated"] = True
        result["total_chars"] = len(text)
    return result


def _read_pdf(path: str, rel: str, args: dict[str, Any]) -> dict[str, Any]:
    """PDF → per-page text extraction with page-range paging. Image-only
    pages report honestly instead of dumping binary."""
    import pypdfium2 as pdfium

    with open(path, "rb") as f:
        data = f.read()
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:
        return {"error": f"PDF unreadable: {e}", "path": rel}

    page_count = len(pdf)
    start_page = args.get("start_page") or 1
    end_page = args.get("end_page") or page_count
    if not isinstance(start_page, int) or not isinstance(end_page, int):
        pdf.close()
        return {"error": "start_page and end_page must be integers"}
    if start_page < 1 or end_page < 1:
        pdf.close()
        return {"error": "start_page and end_page must be at least 1"}
    if start_page > page_count:
        pdf.close()
        return {
            "error": f"start_page {start_page} is beyond the document's {page_count} pages",
            "path": rel,
            "page_count": page_count,
        }
    if end_page < start_page:
        pdf.close()
        return {"error": "end_page must not be before start_page"}

    parts: list[str] = []
    total = 0
    last_page = min(end_page, page_count)
    reached = start_page - 1
    for i in range(start_page - 1, last_page):
        reached = i
        page = pdf[i]
        tp = page.get_textpage()
        text = tp.get_text_range().strip()
        tp.close()
        page.close()
        if not text:
            continue
        chunk = f"--- page {i + 1} ---\n{text}"
        remaining = _READ_MAX_CHARS - total
        if len(chunk) > remaining:
            if remaining > 64:
                parts.append(chunk[:remaining] + "\n…[page text truncated]")
                reached = i + 1
            break
        parts.append(chunk)
        total += len(chunk)
    else:
        reached = last_page
    pdf.close()

    result: dict[str, Any] = {
        "content": "\n\n".join(parts),
        "path": rel,
        "format": "pdf",
        "extracted": "text",
        "page_count": page_count,
        "start_page": start_page,
        "end_page": reached,
    }
    truncated = reached < last_page or last_page < page_count
    if truncated:
        result["truncated"] = True
        result["next_start_page"] = reached + 1
    if not parts:
        result["note"] = (
            "No extractable text in this page range — the PDF is likely "
            "image-based. Use a vision-capable model on rendered pages, or "
            "OCR it via terminal."
        )
    return result


async def read_file(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict[str, Any]:
    """Read a complete file or an inclusive line range from the workspace."""
    wm = WorkspaceManager()
    path = wm.validate_path(workspace_path, args["path"], kwargs.get("sandbox_mode", "strict"))
    if not os.path.isfile(path):
        return {"error": f"File not found: {args['path']}"}

    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image/"):
        if not kwargs.get("supports_vision", False):
            return {
                "error": "The selected model cannot inspect image files.",
                "path": args["path"],
                "mime_type": mime_type,
            }
        size = os.path.getsize(path)
        if size > _IMAGE_MAX_INPUT_BYTES:
            return {
                "error": (
                    f"Image too large to send to the model ({size} bytes). "
                    "Downscale it below 15 MB first (e.g. via terminal)."
                ),
                "path": args["path"],
                "mime_type": mime_type,
            }
        with open(path, "rb") as f:
            data = f.read()
        resized = False
        try:
            from PIL import Image

            im = Image.open(io.BytesIO(data))
            if max(im.size) > _IMAGE_MAX_EDGE or size > 2 * 1024 * 1024:
                im.thumbnail((_IMAGE_MAX_EDGE, _IMAGE_MAX_EDGE))
                buf = io.BytesIO()
                if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                    im.save(buf, format="PNG", optimize=True)
                else:
                    im.convert("RGB").save(buf, format="JPEG", quality=85)
                data = buf.getvalue()
                mime_type = "image/png" if buf and data[:4] == b"\x89PNG" else "image/jpeg"
                resized = True
        except Exception:
            pass  # undecodable image bytes still go through; the model decides
        encoded = base64.b64encode(data).decode("ascii")
        result: dict[str, Any] = {
            "path": args["path"],
            "mime_type": mime_type,
            "bytes": size,
            "_model_content": [
                {"type": "text", "text": f"Image file: {args['path']}"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        }
        if resized:
            result["resized"] = True
            result["sent_bytes"] = len(data)
        return result

    kind = classify(path)
    if kind == "pdf":
        return _read_pdf(path, args["path"], args)
    if kind in _DOC_FORMATS:
        return _read_office(path, args["path"], _DOC_FORMATS[kind])
    if kind == "media":
        return {
            "error": (
                f"Cannot read {mime_type or 'media'} files as text. "
                "Transcribe or process it via terminal/skills."
            ),
            "path": args["path"],
            "mime_type": mime_type,
        }

    if kind == "unknown":
        with open(path, "rb") as f:
            if _looks_binary(f.read(8192)):
                return {
                    "error": (
                        "Binary file — cannot be read as text. Process it via "
                        "terminal/skills, or attach it for a preview."
                    ),
                    "path": args["path"],
                    "mime_type": mime_type,
                    "bytes": os.path.getsize(path),
                }

    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if start_line is None and end_line is None:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(_READ_MAX_CHARS + 1)
        result_full: dict[str, Any] = {
            "content": text[:_READ_MAX_CHARS],
            "path": args["path"],
        }
        if len(text) > _READ_MAX_CHARS:
            result_full["truncated"] = True
            result_full["hint"] = (
                f"File exceeds {_READ_MAX_CHARS} chars — re-read with "
                "start_line/end_line to page through it."
            )
        return result_full

    if start_line is None:
        start_line = 1
    if end_line is None:
        end_line = 2**31 - 1
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return {"error": "start_line and end_line must be integers"}
    if start_line < 1 or end_line < start_line:
        return {"error": "start_line must be at least 1 and end_line must not be before start_line"}

    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total_lines = len(lines)
    selected_end = min(end_line, total_lines)
    content = "".join(lines[start_line - 1 : selected_end]) if start_line <= total_lines else ""
    content_truncated = len(content) > _READ_MAX_CHARS
    result: dict[str, Any] = {
        "content": content[:_READ_MAX_CHARS],
        "path": args["path"],
        "start_line": start_line,
        "end_line": selected_end,
        "total_lines": total_lines,
        "has_more": selected_end < total_lines,
    }
    if content_truncated:
        result["truncated"] = True
        result["hint"] = (
            f"Range output exceeds {_READ_MAX_CHARS} chars — narrow the start_line/end_line range."
        )
    if result["has_more"]:
        result["next_start_line"] = selected_end + 1
    return result


async def write_file(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict[str, Any]:
    """Write a file to the workspace (or anywhere if sandbox is open). Returns a unified diff if the file existed."""
    import difflib

    wm = WorkspaceManager()
    path = wm.validate_path(workspace_path, args["path"], kwargs.get("sandbox_mode", "strict"))
    os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None

    # Capture before content for diff (if file exists)
    before_content = None
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            before_content = f.read()

    # Write the new content
    with open(path, "w", encoding="utf-8") as f:
        f.write(args["content"])

    result: dict[str, Any] = {
        "success": True,
        "path": args["path"],
        "bytes": len(args["content"]),
    }

    # Generate unified diff if the file existed and changed
    if before_content is not None:
        if before_content != args["content"]:
            diff_lines = list(
                difflib.unified_diff(
                    before_content.splitlines(keepends=True),
                    args["content"].splitlines(keepends=True),
                    fromfile=f"a/{args['path']}",
                    tofile=f"b/{args['path']}",
                )
            )
            result["diff"] = "".join(diff_lines)
            result["action"] = "modified"
        else:
            result["action"] = "unchanged"
    else:
        result["action"] = "created"

    return result


async def search_files(args: dict[str, Any], workspace_path: str, **kwargs: Any) -> dict[str, Any]:
    """Search files in the workspace — three modes:

    - mode="content" (default): grep-like content search. Requires `pattern` (regex).
      Optional: `glob` filter, `ignore_case`, `max_results`.
    - mode="name": find files by glob pattern. Requires `pattern` (glob like "*.py").
      Optional: `max_results`.
    - mode="list": list directory contents. Optional: `path` (default ".").
    """
    wm = WorkspaceManager()
    sandbox_mode = kwargs.get("sandbox_mode", "strict")
    mode = args.get("mode", "content")

    if mode == "list":
        rel_path = args.get("path", ".")
        path = wm.validate_path(workspace_path, rel_path, sandbox_mode)
        if not os.path.isdir(path):
            return {"error": f"Directory not found: {rel_path}"}
        entries = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            entries.append(
                {
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                }
            )
        return {"entries": entries, "path": rel_path, "mode": "list"}

    rel_path = args.get("path", ".")
    root = wm.validate_path(workspace_path, rel_path, sandbox_mode)
    pattern = args.get("pattern", "")
    max_results = args.get("max_results", 50)

    if mode == "name":
        results: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                rel = os.path.relpath(full_path, workspace_path)
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(filename, pattern):
                    results.append(rel)
                    if len(results) >= max_results:
                        return {
                            "files": results,
                            "truncated": True,
                            "count": len(results),
                            "mode": "name",
                        }
        return {"files": results, "truncated": False, "count": len(results), "mode": "name"}

    # mode == "content" (grep)
    glob_filter = args.get("glob", "*")
    ignore_case = args.get("ignore_case", False)
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}

    matches: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if not fnmatch.fnmatch(filename, glob_filter):
                continue
            full_path = os.path.join(dirpath, filename)
            rel = os.path.relpath(full_path, workspace_path)
            try:
                with open(full_path, encoding="utf-8", errors="replace") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append(
                                {
                                    "file": rel,
                                    "line": line_num,
                                    "text": line.rstrip()[:200],
                                }
                            )
                            if len(matches) >= max_results:
                                return {
                                    "matches": matches,
                                    "truncated": True,
                                    "count": len(matches),
                                    "mode": "content",
                                }
            except (OSError, UnicodeDecodeError):
                continue

    return {"matches": matches, "truncated": False, "count": len(matches), "mode": "content"}
