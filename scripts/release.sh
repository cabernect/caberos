#!/usr/bin/env bash
# Two-phase release for a protected `main`.
#
#   ./scripts/release.sh 0.1.10
#
# Phase 1 (bump not on main yet): main is protected, so the version bump goes
# through a PR like everything else. Creates `release/vX.Y.Z`, bumps all
# manifests, commits, pushes the branch, and prints the compare URL to open.
#
# Phase 2 (re-run after the PR merges): detects the bump already on origin/main
# and tags the merge commit `vX.Y.Z`, pushing the tag — which triggers
# .github/workflows/release.yml to build the DMG + website.
#
# The version stays a committed literal (uv_build can't do VCS versioning), but
# this script makes bump+tag atomic so you never hand-edit manifests.

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

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: working tree is dirty — commit or stash first." >&2
  git status --short >&2
  exit 1
fi

ORIG_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

if git rev-parse "v${VERSION}" >/dev/null 2>&1 \
  || git ls-remote --exit-code --tags origin "v${VERSION}" >/dev/null 2>&1; then
  echo "Error: tag v${VERSION} already exists." >&2
  exit 1
fi

git fetch origin main --quiet
MAIN_VER="$(git show origin/main:backend/pyproject.toml \
  | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)"

# Phase 2 — the bump is already merged to main: tag it and push the tag.
if [[ "$MAIN_VER" == "$VERSION" ]]; then
  git tag -a "v${VERSION}" -m "v${VERSION}" origin/main
  git push origin "v${VERSION}"
  echo "✅ Tagged v${VERSION} on origin/main — release.yml is building the DMG + website."
  exit 0
fi

# Phase 1 — bump not on main: ship it via a release PR.
BRANCH="release/v${VERSION}"
if git show-ref --verify --quiet "refs/heads/${BRANCH}" \
  || git ls-remote --exit-code --heads origin "${BRANCH}" >/dev/null 2>&1; then
  echo "Error: branch ${BRANCH} already exists." >&2
  exit 1
fi

echo "→ main is at ${MAIN_VER}; creating ${BRANCH} with the bump to ${VERSION}"
git checkout -b "$BRANCH" origin/main

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

echo "→ Pushing ${BRANCH}"
git push -u origin "$BRANCH"
git checkout "$ORIG_BRANCH" --quiet

cat <<EOF

✅ Release branch pushed. Next:
   1. Open the PR and merge it:
      https://github.com/cabernect/caberos/compare/main...${BRANCH}
   2. Then finish the release:
      ./scripts/release.sh ${VERSION}
EOF
