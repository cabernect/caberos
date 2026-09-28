"""Skill validation (W6).

Errors block publish; warnings ride along on the card. Runs at draft-save,
import, and as the publish gate — `validation_result` is stored on the row so
the UI shows it without re-running.
"""

import ast
import re
import subprocess
from pathlib import Path
from typing import Any

from .loader import _parse_frontmatter

# Agent Skills spec: lowercase letters, numbers, hyphens; max 64 chars.
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_NAME = 64
_MAX_DESCRIPTION = 1024
# Import/size sanity caps — the same limits guard ZIP and URL installs.
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILE_COUNT = 500
MAX_FILE_BYTES = 10 * 1024 * 1024
# Body token estimate beyond which we warn (the menu is names+descriptions,
# but a loaded skill's body still costs context).
_WARN_BODY_TOKENS = 5000

# Resource references in the body: `scripts/x.py`, references/y.md,
# assets/z.png (backticked or markdown-linked). Only these conventional dirs
# are checked — anything else is too ambiguous to flag.
_RESOURCE_REF_RE = re.compile(
    r"(?:`|\]\()(?:\./)?((?:scripts|references|assets)/[^`\)\s'\"]+)", re.IGNORECASE
)
# markdown link targets like [label](some/path)
_MD_LINK_RE = re.compile(r"\]\((?!https?://|#|/)([^)\s]+)\)")


def validate_skill_dir(
    skill_dir: Path,
    *,
    known_capabilities: set[str] | None = None,
    granted_capabilities: set[str] | None = None,
) -> dict[str, Any]:
    """Validate a skill directory. Returns {errors, warnings, stats}.

    `known_capabilities`: names that exist at all (unknown → error).
    `granted_capabilities`: names granted to the relevant agent(s); existing
    but ungranted names → warning.
    """
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, Any] = {"files": 0, "bytes": 0, "body_tokens": 0}

    if not skill_dir.is_dir():
        return {"errors": ["skill directory does not exist"], "warnings": [], "stats": stats}

    files = [p for p in skill_dir.rglob("*") if p.is_file()]
    stats["files"] = len(files)
    stats["bytes"] = sum(p.stat().st_size for p in files)
    if stats["files"] > MAX_FILE_COUNT:
        errors.append(f"too many files ({stats['files']} > {MAX_FILE_COUNT})")
    if stats["bytes"] > MAX_TOTAL_BYTES:
        errors.append(
            f"skill too large ({stats['bytes'] // 1024} KB > {MAX_TOTAL_BYTES // 1024} KB)"
        )
    for p in files:
        if p.stat().st_size > MAX_FILE_BYTES:
            errors.append(f"{p.relative_to(skill_dir)} exceeds single-file cap")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append("SKILL.md missing")
        return {"errors": errors, "warnings": warnings, "stats": stats}

    content = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, body = _parse_frontmatter(content)
    if not fm:
        errors.append("SKILL.md frontmatter missing or unparseable")

    name = fm.get("name", "")
    if not name:
        errors.append("frontmatter 'name' missing")
    elif not _NAME_RE.match(name) or len(name) > _MAX_NAME:
        errors.append(f"name '{name}' must be lowercase letters, numbers, hyphens (≤64 chars)")
    elif name != skill_dir.name:
        errors.append(f"name '{name}' must match directory '{skill_dir.name}'")

    description = fm.get("description", "")
    if not description:
        errors.append("frontmatter 'description' missing")
    elif len(description) > _MAX_DESCRIPTION:
        errors.append(f"description exceeds {_MAX_DESCRIPTION} chars")

    if not fm.get("license"):
        warnings.append("no license field")
    if not fm.get("compatibility"):
        warnings.append("no compatibility field")

    stats["body_tokens"] = len(body.split())
    if stats["body_tokens"] > _WARN_BODY_TOKENS:
        warnings.append(f"large body (~{stats['body_tokens']} tokens)")

    # Resource references must resolve inside the skill dir.
    declared_dirs = {p.name for p in skill_dir.iterdir() if p.is_dir()}
    for ref in sorted(set(_RESOURCE_REF_RE.findall(body)) | set(_MD_LINK_RE.findall(body))):
        target = (skill_dir / ref).resolve()
        try:
            target.relative_to(skill_dir.resolve())
        except ValueError:
            errors.append(f"reference '{ref}' escapes the skill directory")
            continue
        if not target.exists():
            errors.append(f"referenced resource '{ref}' does not exist")
    for d in ("scripts", "references", "assets"):
        if d in declared_dirs and not any(p.is_file() for p in (skill_dir / d).rglob("*")):
            warnings.append(f"declared '{d}/' directory is empty")

    # Script syntax — parse only, never execute.
    for script in files:
        rel = script.relative_to(skill_dir).as_posix()
        if script.suffix == ".py":
            try:
                ast.parse(script.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as e:
                errors.append(f"{rel}: python syntax error ({e.msg} line {e.lineno})")
        elif script.suffix == ".sh":
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, timeout=10)
            if result.returncode != 0:
                detail = result.stderr.decode(errors="replace").strip().splitlines()
                errors.append(f"{rel}: bash syntax error ({detail[0] if detail else 'invalid'})")

    # allowed-tools: unknown names are errors; existing-but-ungranted warn.
    allowed_tools = fm.get("allowed-tools") or ""
    requested = [t.strip() for t in re.split(r"[,\s]+", str(allowed_tools)) if t.strip()]
    for tool in requested:
        if known_capabilities is not None and tool not in known_capabilities:
            errors.append(f"allowed-tools references unknown capability '{tool}'")
        elif granted_capabilities is not None and tool not in granted_capabilities:
            warnings.append(f"allowed-tools '{tool}' is not granted to the owner/assigned agents")

    return {"errors": errors, "warnings": warnings, "stats": stats}
