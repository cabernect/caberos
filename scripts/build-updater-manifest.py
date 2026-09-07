"""Build the Tauri updater manifest (latest.json) from per-platform artifacts.

Why this is a separate step rather than part of each platform's build job:

The updater reads one manifest from a fixed URL. If each platform job wrote
that file, the last job to finish would overwrite the others, and the manifest
would describe only that platform. Users on every *other* platform would then
silently stop receiving updates — no error in CI, none in the app, and nothing
the user could see. The failure is only noticed when somebody checks manually.

So the manifest is built once, after all platform builds, from all of their
artifacts, and it refuses to emit a manifest that is missing a platform the
release was supposed to contain.

Usage:
    python scripts/build-updater-manifest.py \
        --version 0.3.0 \
        --repo cabernect/caberos \
        --tag v0.3.0 \
        --platform darwin-aarch64=dist/CaberOS.app.tar.gz \
        --platform windows-x86_64=dist/CaberOS_0.3.0_x64-setup.nsis.zip \
        --out latest.json

Each artifact must have a sibling `<artifact>.sig` produced by the same build.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Tauri platform keys are OS-ARCH. Guard against typos reaching a release, since
# a key the updater does not recognise is silently ignored by clients.
KNOWN_PLATFORMS = {
    "darwin-aarch64",
    "darwin-x86_64",
    "linux-x86_64",
    "linux-aarch64",
    "windows-x86_64",
    "windows-aarch64",
    "windows-i686",
}


class ManifestError(RuntimeError):
    """Raised when the manifest cannot be built correctly."""


def read_signature(artifact: Path) -> str:
    """Read the detached signature that belongs to `artifact`.

    Tauri regenerates the signature on every build, so it must come from the
    same run as the archive it describes — never from a cache.
    """
    sig_path = artifact.with_name(artifact.name + ".sig")
    if not sig_path.is_file():
        raise ManifestError(f"Missing signature for {artifact.name}: expected {sig_path}")
    signature = sig_path.read_text(encoding="utf-8").strip()
    if not signature:
        raise ManifestError(f"Signature file is empty: {sig_path}")
    return signature


def build_manifest(
    version: str,
    repo: str,
    tag: str,
    artifacts: dict[str, Path],
    expected_platforms: set[str] | None = None,
    now: datetime | None = None,
) -> dict:
    """Assemble the manifest, or raise if it would be incomplete or malformed."""
    if not artifacts:
        raise ManifestError("No platform artifacts supplied — refusing to write an empty manifest.")

    unknown = set(artifacts) - KNOWN_PLATFORMS
    if unknown:
        raise ManifestError(
            f"Unknown Tauri platform key(s): {', '.join(sorted(unknown))}. "
            f"Known keys: {', '.join(sorted(KNOWN_PLATFORMS))}"
        )

    if expected_platforms:
        missing = expected_platforms - set(artifacts)
        if missing:
            raise ManifestError(
                f"Manifest is missing expected platform(s): {', '.join(sorted(missing))}. "
                "Publishing it would stop updates for users on those platforms. "
                "Fix the failing build, or drop the platform from --expect deliberately."
            )

    platforms = {}
    for key, artifact in sorted(artifacts.items()):
        if not artifact.is_file():
            raise ManifestError(f"Artifact for {key} does not exist: {artifact}")
        platforms[key] = {
            "signature": read_signature(artifact),
            "url": f"https://github.com/{repo}/releases/download/{tag}/{artifact.name}",
        }

    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "version": version,
        "notes": f"CaberOS {version}",
        "pub_date": stamp,
        "platforms": platforms,
    }


def _parse_platform(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"--platform expects KEY=PATH (got {value!r}), e.g. windows-x86_64=dist/setup.nsis.zip"
        )
    key, _, path = value.partition("=")
    return key.strip(), Path(path.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version, without a leading v")
    parser.add_argument("--repo", required=True, help="owner/name of the GitHub repository")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v0.3.0")
    parser.add_argument(
        "--platform",
        action="append",
        required=True,
        type=_parse_platform,
        metavar="KEY=PATH",
        help="Platform key and its updater archive. Repeat per platform.",
    )
    parser.add_argument(
        "--expect",
        default="",
        help="Comma-separated platform keys this release must contain. Build fails if any is absent.",
    )
    parser.add_argument("--out", default="latest.json", help="Where to write the manifest")
    args = parser.parse_args(argv)

    expected = {p.strip() for p in args.expect.split(",") if p.strip()}

    try:
        manifest = build_manifest(
            version=args.version,
            repo=args.repo,
            tag=args.tag,
            artifacts=dict(args.platform),
            expected_platforms=expected or None,
        )
    except ManifestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    Path(args.out).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} covering: {', '.join(sorted(manifest['platforms']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
