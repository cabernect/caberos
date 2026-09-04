#!/usr/bin/env bash
# Set a single release version across all CaberOS version manifests.
#
# Usage: ./scripts/set-version.sh 0.1.3
#
# Updates:
# - backend/pyproject.toml
# - frontend/package.json
# - frontend/package-lock.json (version + package.version)
# - frontend/src-tauri/Cargo.toml
# - frontend/src-tauri/tauri.conf.json
#
# After running, verify with: ./scripts/check-version.sh
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <version>"
  echo "Example: $0 0.1.3"
  exit 1
fi

VERSION="$1"

# Validate semver-ish format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$'; then
  echo "Error: version must be in semver format (e.g. 0.1.3 or 0.1.3-beta)"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "Setting version to $VERSION across all manifests..."

# 1. backend/pyproject.toml
sed -i.bak "s/^version = \".*\"/version = \"$VERSION\"/" backend/pyproject.toml
rm -f backend/pyproject.toml.bak
echo "  ✓ backend/pyproject.toml"

# backend/src/agentos/__init__.py — the gateway reports this over /health and the
# desktop shell compares against it to detect a stale bundled gateway.
sed -i.bak "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" backend/src/agentos/__init__.py
rm -f backend/src/agentos/__init__.py.bak
echo "  ✓ backend/src/agentos/__init__.py"

# 2. frontend/package.json
sed -i.bak "s/\"version\": \".*\"/\"version\": \"$VERSION\"/" frontend/package.json
rm -f frontend/package.json.bak
echo "  ✓ frontend/package.json"

# 3. frontend/package-lock.json (if it exists)
if [ -f frontend/package-lock.json ]; then
  # Update the root package version
  python3 -c "
import json, sys
with open('frontend/package-lock.json', 'r') as f:
    lock = json.load(f)
# Update root lockfile version
if 'version' in lock:
    lock['version'] = '$VERSION'
# Update the root package entry's version
if 'packages' in lock and '' in lock['packages']:
    lock['packages']['']['version'] = '$VERSION'
with open('frontend/package-lock.json', 'w') as f:
    json.dump(lock, f, indent=2)
    f.write('\n')
"
  echo "  ✓ frontend/package-lock.json"
fi

# 4. frontend/src-tauri/Cargo.toml
sed -i.bak "s/^version = \".*\"/version = \"$VERSION\"/" frontend/src-tauri/Cargo.toml
rm -f frontend/src-tauri/Cargo.toml.bak
echo "  ✓ frontend/src-tauri/Cargo.toml"

# 5. frontend/src-tauri/tauri.conf.json
sed -i.bak "s/\"version\": \".*\"/\"version\": \"$VERSION\"/" frontend/src-tauri/tauri.conf.json
rm -f frontend/src-tauri/tauri.conf.json.bak
echo "  ✓ frontend/src-tauri/tauri.conf.json"

echo ""
echo "All manifests updated to $VERSION"
echo "Run ./scripts/check-version.sh to verify consistency."
