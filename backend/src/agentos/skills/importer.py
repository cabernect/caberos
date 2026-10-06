"""Skill archive import pipeline (W6) — shared hardening for ZIP upload and
repo-URL installs.

Both entry points produce a zip; this module detects every directory
containing SKILL.md (monorepo-style repos hold many skills → the operator
gets a pick-list) and extracts selected subtrees under these guarantees:

- path traversal rejected (resolved containment)
- symlink entries rejected outright
- uncompressed-size, file-count, and per-file caps enforced on *actual*
  streamed bytes, not just declared headers
- `__MACOSX`/dotfile junk skipped
- remote fetches are https-only, streamed with a download cap + timeout

Nothing here publishes — callers land results as drafts.
"""

import io
import re
import stat
import zipfile
from pathlib import Path

import httpx

from .loader import _parse_frontmatter
from .validate import MAX_FILE_BYTES, MAX_FILE_COUNT, MAX_TOTAL_BYTES

# Compressed-archive download cap for remote installs.
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
ARCHIVE_TIMEOUT = 30.0

_JUNK_PARTS = {"__MACOSX", ".git", "__pycache__", ".DS_Store"}


class ImportRejected(ValueError):
    """The archive failed validation or hardening — the API maps it to 400."""


def _open_zip(archive: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as e:
        raise ImportRejected("not a valid zip archive") from e


def _is_junk(member_name: str) -> bool:
    parts = member_name.split("/")
    return any(p in _JUNK_PARTS or p.startswith("._") for p in parts)


def skill_candidates(archive: bytes) -> list[dict]:
    """Detect every directory containing SKILL.md. Returns a pick-list of
    {path, name, description} — path is the skill's dir prefix inside the
    archive ("" for a root-level SKILL.md)."""
    zf = _open_zip(archive)
    candidates: list[dict] = []
    for name in zf.namelist():
        if _is_junk(name) or not name.endswith("SKILL.md"):
            continue
        prefix = name[: -len("SKILL.md")]
        fm, _ = _parse_frontmatter(zf.read(name).decode("utf-8", errors="replace"))
        candidates.append(
            {
                "path": prefix,
                "dir_name": prefix.rstrip("/").rsplit("/", 1)[-1] or "",
                "name": fm.get("name", ""),
                "description": fm.get("description", ""),
            }
        )
    return sorted(candidates, key=lambda c: c["path"])


def extract_skill_subtree(archive: bytes, prefix: str, dest: Path) -> int:
    """Extract one skill subtree from `archive` into `dest`.

    `prefix` is the candidate path from skill_candidates ("" = the archive
    itself is the skill). Returns the number of files written.
    """
    zf = _open_zip(archive)
    members = [
        info
        for info in zf.infolist()
        if not info.is_dir()
        and not _is_junk(info.filename)
        and (not prefix or info.filename.startswith(prefix))
    ]
    if not members:
        raise ImportRejected("selected skill directory is empty")
    if len(members) > MAX_FILE_COUNT:
        raise ImportRejected(f"archive has too many files ({len(members)} > {MAX_FILE_COUNT})")
    declared = sum(info.file_size for info in members)
    if declared > MAX_TOTAL_BYTES:
        raise ImportRejected(
            f"archive decompresses to too much data "
            f"({declared // 1024} KB > {MAX_TOTAL_BYTES // 1024} KB)"
        )

    dest_resolved = dest.resolve()
    written = 0
    for info in members:
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise ImportRejected(f"archive contains a symlink ({info.filename})")
        if info.file_size > MAX_FILE_BYTES:
            raise ImportRejected(f"{info.filename} exceeds the single-file cap")

        rel = info.filename[len(prefix) :] if prefix else info.filename
        if not rel:
            continue
        target = (dest / rel).resolve()
        try:
            target.relative_to(dest_resolved)
        except ValueError:
            raise ImportRejected(f"path traversal entry ({info.filename})")

        target.parent.mkdir(parents=True, exist_ok=True)
        # Stream actual bytes with the real cap — declared size can lie.
        with zf.open(info) as src, open(target, "wb") as out:
            remaining = MAX_FILE_BYTES
            while True:
                chunk = src.read(min(65536, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)
                if remaining <= 0:
                    raise ImportRejected(f"{info.filename} exceeds the single-file cap")
        written += 1
    return written


# --- Repository URL installs -------------------------------------------------
#
# No git exec — a host URL is normalized to the host's HTTP archive endpoint.

_GITHUB_RE = re.compile(
    r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+))?(?:/.*)?$"
)
_BITBUCKET_RE = re.compile(
    r"^https://bitbucket\.org/([^/]+)/([^/]+?)(?:\.git)?(?:/src/([^/]+))?(?:/.*)?$"
)


_GITHUB_SHORTHAND_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def archive_url_for(repo_url: str) -> str:
    """Normalize a repo/branch URL to a downloadable zip archive URL.

    Accepts full https URLs plus `owner/repo` shorthand (GitHub)."""
    url = repo_url.strip().rstrip("/")
    if _GITHUB_SHORTHAND_RE.match(url):
        url = f"https://github.com/{url}"
    if not url.startswith("https://"):
        raise ImportRejected("only https:// URLs are supported")
    if url.endswith(".zip"):
        return url  # already a direct archive link

    if m := _GITHUB_RE.match(url):
        owner, repo, ref = m.group(1), m.group(2), m.group(3) or "HEAD"
        return f"https://codeload.github.com/{owner}/{repo}/zip/{ref}"
    if url.startswith("https://gitlab.com/"):
        path = url[len("https://gitlab.com/") :]
        # Split off GitLab's -/ routes: {project}/-/tree/{ref}[/subpath]
        project, sep, rest = path.partition("/-/")
        ref = "HEAD"
        if sep:
            route, _, tail = rest.partition("/")
            if route in ("tree", "src", "blob") and tail:
                ref = tail.split("/", 1)[0]
            elif route == "archive":
                # -/archive/{ref}/{name}.zip — almost a direct link; append .zip
                ref = tail.split("/", 1)[0] or "HEAD"
        project = project.removesuffix(".git")
        name = project.rsplit("/", 1)[-1]
        return f"https://gitlab.com/{project}/-/archive/{ref}/{name}-{ref}.zip"
    if m := _BITBUCKET_RE.match(url):
        owner, repo, ref = m.group(1), m.group(2), m.group(3) or "HEAD"
        return f"https://bitbucket.org/{owner}/{repo}/get/{ref}.zip"

    raise ImportRejected(
        "unrecognized repo URL — use owner/repo, a GitHub/GitLab/Bitbucket URL, "
        "or a direct .zip archive link"
    )


async def fetch_archive(repo_url: str) -> bytes:
    """Download a repo archive over HTTP with a size cap + timeout."""
    url = archive_url_for(repo_url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=ARCHIVE_TIMEOUT) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise ImportRejected(
                        f"archive fetch failed (HTTP {resp.status_code}) — "
                        "check the URL/branch, or the repo may be private"
                    )
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes(65536):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise ImportRejected(
                            f"archive exceeds the {MAX_ARCHIVE_BYTES // 1024 // 1024} MB "
                            "download cap"
                        )
                    chunks.append(chunk)
    except httpx.HTTPError as e:
        raise ImportRejected(f"archive fetch failed: {e}") from e
    return b"".join(chunks)
