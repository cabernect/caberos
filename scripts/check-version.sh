#!/usr/bin/env bash
# Verify that all CaberOS version manifests agree.
#
# Usage: ./scripts/check-version.sh
# Exit 0 if all versions match, exit 1 if they drift.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Windows ships "python", not "python3", and also plants App Execution Alias
# stubs that exist on PATH but fail when run. So probe by executing, not by
# looking the name up. This script runs on the Windows release runner too.
PY=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "pass" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "No working python interpreter found on PATH." >&2
  exit 1
fi

# Extract versions from each manifest
BACKEND_VERSION=$(grep '^version = ' backend/pyproject.toml | head -1 | sed 's/version = "\(.*\)"/\1/')
PACKAGE_VERSION=$($PY -c "import json; print(json.load(open('frontend/package.json'))['version'])")
CARGO_VERSION=$(grep '^version = ' frontend/src-tauri/Cargo.toml | head -1 | sed 's/version = "\(.*\)"/\1/')
TAURI_VERSION=$($PY -c "import json; print(json.load(open('frontend/src-tauri/tauri.conf.json'))['version'])")
# The gateway reports this one over /health; the desktop shell compares against
# it to catch an update that replaced the shell but not the bundled gateway.
INIT_VERSION=$(grep '^__version__ = ' backend/src/agentos/__init__.py | cut -d'"' -f2)

echo "  backend/pyproject.toml:       $BACKEND_VERSION"
echo "  frontend/package.json:        $PACKAGE_VERSION"
echo "  frontend/src-tauri/Cargo.toml: $CARGO_VERSION"
echo "  frontend/src-tauri/tauri.conf: $TAURI_VERSION"
echo "  agentos/__init__.py:          $INIT_VERSION"

# Check if they all agree
VERSIONS="$BACKEND_VERSION $PACKAGE_VERSION $CARGO_VERSION $TAURI_VERSION $INIT_VERSION"
UNIQUE=$(echo "$VERSIONS" | tr ' ' '\n' | sort -u | wc -l | tr -d ' ')

if [ "$UNIQUE" -ne 1 ]; then
  echo ""
  echo "❌ Version drift detected! Manifests do not agree."
  echo "Run ./scripts/set-version.sh <version> to fix."
  exit 1
fi

echo ""
echo "✅ All manifests agree: $BACKEND_VERSION"
