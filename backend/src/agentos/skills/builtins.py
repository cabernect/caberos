"""Built-in skill manifest + content hashing (W6).

`skills/` ships the built-in set and is read-only at runtime. The manifest is
the boundary between shipped resources and user data: any directory in
`skills/` NOT listed here is a legacy user import and migrates to the
skills-store on startup. A dev-side test asserts the manifest stays in sync
with the directory.
"""

import hashlib
from pathlib import Path

# Names of the built-in skills shipped in skills/. Tests pin this list to the
# actual directory contents — add here when shipping a new built-in.
BUILTIN_SKILLS: frozenset[str] = frozenset(
    {
        "algorithmic-art",
        "brand-guidelines",
        "canvas-design",
        "claude-api",
        "doc-coauthoring",
        "docx",
        "frontend-design",
        "internal-comms",
        "mcp-builder",
        "pdf",
        "pptx",
        "skill-creator",
        "slack-gif-creator",
        "theme-factory",
        "web-artifacts-builder",
        "webapp-testing",
        "xlsx",
    }
)

# Filenames/dirs that never participate in a skill's content identity.
_IGNORED_NAMES = frozenset({".DS_Store", "__MACOSX", "__pycache__", ".git"})


def hash_skill_dir(skill_dir: Path) -> str:
    """Deterministic hash of a skill directory's contents.

    Covers relative paths + bytes of every file; ignored junk and empty dirs
    don't affect the hash. Used for built-in reseed detection and agent-local
    run pinning (provenance for a live, mutable copy).
    """
    digest = hashlib.sha256()
    if not skill_dir.is_dir():
        return digest.hexdigest()
    for path in sorted(skill_dir.rglob("*")):
        rel = path.relative_to(skill_dir).as_posix()
        if any(part in _IGNORED_NAMES for part in path.parts):
            continue
        if not path.is_file():
            continue
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
