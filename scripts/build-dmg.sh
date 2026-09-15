#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "DMG packaging is currently supported on macOS only." >&2
  exit 1
fi

APP_DIR="${ROOT_DIR}/frontend/src-tauri/target/release/bundle/macos/CaberOS.app"
OUTPUT_DIR="${ROOT_DIR}/frontend/src-tauri/target/release/bundle/dmg"
VERSION="$(sed -n 's/.*"version": "\([^"]*\)".*/\1/p' "${ROOT_DIR}/frontend/src-tauri/tauri.conf.json" | head -n 1)"
ARCH="$(uname -m)"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/caberos-dmg.XXXXXX")"
OUTPUT_FILE="${OUTPUT_DIR}/CaberOS_${VERSION}_${ARCH}.dmg"

cleanup() {
  rm -rf "${STAGING_DIR}"
}
trap cleanup EXIT

if [[ ! -d "${APP_DIR}" ]]; then
  echo "CaberOS.app not found. Run npm run desktop:build first." >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"
cp -R "${APP_DIR}" "${STAGING_DIR}/CaberOS.app"
ln -s /Applications "${STAGING_DIR}/Applications"

# hdiutil intermittently fails with "Resource busy" when a stale mount or a
# leftover DMG is still attached/referenced. Detach any stale volume and
# remove the previous artifact, then retry with a short backoff.
hdiutil detach "/Volumes/CaberOS" -quiet 2>/dev/null || true
rm -f "${OUTPUT_FILE}"

for attempt in 1 2 3 4; do
  if hdiutil create -volname "CaberOS" -srcfolder "${STAGING_DIR}" -ov -format UDZO "${OUTPUT_FILE}"; then
    break
  fi
  if [[ "${attempt}" -eq 4 ]]; then
    echo "hdiutil create failed after ${attempt} attempts" >&2
    exit 1
  fi
  echo "hdiutil attempt ${attempt} failed; cleaning up and retrying..." >&2
  hdiutil detach "/Volumes/CaberOS" -quiet 2>/dev/null || true
  rm -f "${OUTPUT_FILE}"
  sleep $((attempt * 2))
done
echo "Created ${OUTPUT_FILE}"
