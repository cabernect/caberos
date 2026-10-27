#!/usr/bin/env python3
"""Compose the GitHub release body for a CaberOS tag.

Reads the matching section from CHANGELOG.md and combines it with the
install instructions block. Fails when the tag has no changelog entry —
a release without curated notes should not ship silently.

Usage:
    python3 scripts/release-body.py --version 0.2.0 --out release-body.md
"""

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

INSTALL_BLOCK = """\
### Download

- **macOS Apple Silicon (ARM64)** — the `.dmg` file below.
- **Windows x64** — the `-setup.exe` file below.

> macOS Intel, Windows on ARM, and Linux builds are not yet available.
> See `docs/platform-support.md` for the full support matrix.

### Install — macOS

1. Open the `.dmg` and drag **CaberOS** to Applications
2. If macOS reports that CaberOS is damaged, verify the download came
   from this release, then run:
   `xattr -dr com.apple.quarantine /Applications/CaberOS.app`
3. Launch CaberOS — the gateway starts automatically

### Install — Windows

1. Run the `-setup.exe` installer (installs for the current user, no admin needed)
2. Windows SmartScreen may warn on first run while the signature builds
   reputation — choose **More info → Run anyway**
3. Launch CaberOS — the gateway starts automatically

**Shell commands on Windows need no Docker and no WSL.** The installer
bundles Microsoft Execution Containers (MXC). The first time, open
Observability → Health and click **Enable shell sandbox** — Windows asks
for permission once, then agent commands run in a restricted container.
MXC is experimental: Microsoft does not yet call it a security boundary,
and it can only reach workspaces on the system drive. Until it is
enabled, shell is off with a clear reason; every other capability still
works. See `docs/platform-support.md` for details.

### First login

Default credentials: `admin` / `admin` — change them immediately.

---
**License:** MIT — Copyright (c) 2025 HoangPH25
"""


def extract_section(changelog: str, version: str) -> str | None:
    """Return the changelog body under the heading for `version`.

    Prefers `## [X.Y.Z]`; falls back to `## [Unreleased] — X.Y.Z` so the
    entry works both while pending and once renamed at release.
    """
    headings = list(
        re.compile(r"^## \[[^\]\n]+\][^\n]*$", re.MULTILINE).finditer(changelog)
    )
    match = None
    for candidate in headings:
        text = candidate.group(0)
        if re.match(rf"^## \[{re.escape(version)}\]", text):
            match = candidate
            break
        if "unreleased" in text.lower() and version in text and match is None:
            match = candidate
    if match is None:
        return None
    start = match.end()
    nxt = next((h for h in headings if h.start() >= start), None)
    section = changelog[start : nxt.start() if nxt else len(changelog)]
    return section.strip() or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Tag version without the v prefix")
    parser.add_argument("--out", required=True, help="Output file for the release body")
    args = parser.parse_args()

    changelog = CHANGELOG.read_text(encoding="utf-8")
    section = extract_section(changelog, args.version)
    if section is None:
        print(
            f"CHANGELOG.md has no entry for {args.version}. "
            "Add the release notes section (or rename [Unreleased] — X.Y.Z) before tagging.",
            file=sys.stderr,
        )
        return 1

    body = (
        "**Local-first AI Agent Operating System.**\n\n"
        f"{section}\n\n---\n\n{INSTALL_BLOCK}"
    )
    Path(args.out).write_text(body, encoding="utf-8")
    print(f"Wrote release body for {args.version} ({len(section)} chars of notes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
