#!/usr/bin/env bash
# Verify that all CaberOS version manifests agree.
#
# Usage: ./scripts/check-version.sh
# Exit 0 if all versions match, exit 1 if they drift.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Extract versions from each manifest
BACKEND_VERSION=$(grep '^version = ' backend/pyproject.toml | head -1 | sed 's/version = "\(.*\)"/\1/')
PACKAGE_VERSION=$(python3 -c "import json; print(json.load(open('frontend/package.json'))['version'])")
CARGO_VERSION=$(grep '^version = ' frontend/src-tauri/Cargo.toml | head -1 | sed 's/version = "\(.*\)"/\1/')
TAURI_VERSION=$(python3 -c "import json; print(json.load(open('frontend/src-tauri/tauri.conf.json'))['version'])")

echo "  backend/pyproject.toml:       $BACKEND_VERSION"
echo "  frontend/package.json:        $PACKAGE_VERSION"
echo "  frontend/src-tauri/Cargo.toml: $CARGO_VERSION"
echo "  frontend/src-tauri/tauri.conf: $TAURI_VERSION"

# Check if they all agree
VERSIONS="$BACKEND_VERSION $PACKAGE_VERSION $CARGO_VERSION $TAURI_VERSION"
UNIQUE=$(echo "$VERSIONS" | tr ' ' '\n' | sort -u | wc -l | tr -d ' ')

if [ "$UNIQUE" -ne 1 ]; then
  echo ""
  echo "❌ Version drift detected! Manifests do not agree."
  echo "Run ./scripts/set-version.sh <version> to fix."
  exit 1
fi

echo ""
echo "✅ All manifests agree: $BACKEND_VERSION"
