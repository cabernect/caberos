#!/usr/bin/env bash
# One-command release.
#
#   ./scripts/release.sh 0.1.10
#
# Bumps every version manifest to <X.Y.Z>, commits "Bump version to X.Y.Z" on
# the current branch (must be main), tags v<X.Y.Z>, and pushes main + the tag.
# Pushing the tag triggers .github/workflows/release.yml, which re-verifies the
# manifests match and builds the DMG + website.
#
# Why a script and not bare `git tag`? The version has to be a literal the
# builders read — uv_build rejects dynamic versioning, and Tauri/Cargo/npm all
# read committed literals. This script makes the bump atomic with the tag so
# you never hand-edit manifests or tag a commit whose version is stale.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: ./scripts/release.sh <X.Y.Z>" >&2
  exit 1
fi
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: version must look like X.Y.Z (got '$VERSION')" >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
  echo "Error: releases are cut from main (currently on '$BRANCH')." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: working tree is dirty — commit or stash first." >&2
  git status --short >&2
  exit 1
fi

if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
  echo "Error: tag v${VERSION} already exists." >&2
  exit 1
fi

echo "→ Bumping manifests to ${VERSION}"
./scripts/set-version.sh "$VERSION"
./scripts/check-version.sh

# Only stage the manifest files set-version.sh touched — never sweep in
# unrelated working-tree changes.
MANIFESTS=(
  backend/pyproject.toml
  frontend/package.json
  frontend/package-lock.json
  frontend/src-tauri/Cargo.toml
  frontend/src-tauri/tauri.conf.json
  website/package.json
  website/package-lock.json
)
git add -- "${MANIFESTS[@]}"
git commit -m "Bump version to ${VERSION}"

echo "→ Tagging v${VERSION}"
git tag -a "v${VERSION}" -m "v${VERSION}"

echo "→ Pushing main + v${VERSION}"
git push origin main "v${VERSION}"

echo "✅ Released v${VERSION} — release.yml is building the DMG + website."
