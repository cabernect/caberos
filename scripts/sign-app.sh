#!/usr/bin/env bash
# Post-build re-sign: Tauri's linker ad-hoc signature gives each binary a
# hash-derived identifier (caberos-<cdhash>), which fails usernotificationsd's
# bundle-identifier entitlement check — UNUserNotificationCenter calls are
# rejected and notification authorization reports permanently denied (B41).
# Re-signing ad-hoc with an explicit --identifier matching CFBundleIdentifier
# makes modern macOS notifications work without a paid signing identity.
set -euo pipefail

APP="${1:-$(dirname "$0")/../frontend/src-tauri/target/release/bundle/macos/CaberOS.app}"
IDENTIFIER="com.caberos.desktop"

if [ ! -d "$APP" ]; then
  echo "sign-app: $APP not found — run 'npm run desktop:build' first" >&2
  exit 1
fi

if ! codesign --force --deep --sign - --identifier "$IDENTIFIER" "$APP"; then
  echo "sign-app: codesign failed" >&2
  exit 1
fi

echo "sign-app: $(codesign -dv "$APP" 2>&1 | grep -E 'Signature|Identifier' | tr '\n' ' ')"
