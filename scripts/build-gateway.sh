#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
RESOURCE_DIR="${ROOT_DIR}/frontend/src-tauri/resources"
GATEWAY_OUTPUT_DIR="${RESOURCE_DIR}/gateway"
BUILD_DIR="${BACKEND_DIR}/build/pyinstaller"

mkdir -p "${RESOURCE_DIR}" "${GATEWAY_OUTPUT_DIR}" "${BUILD_DIR}/work" "${BUILD_DIR}/spec"

cd "${BACKEND_DIR}"
uv run pyinstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name caberos-gateway \
  --paths src \
  --distpath "${GATEWAY_OUTPUT_DIR}" \
  --workpath "${BUILD_DIR}/work" \
  --specpath "${BUILD_DIR}/spec" \
  --collect-submodules agentos \
  --collect-all aiosqlite \
  --collect-all litellm \
  --collect-all tiktoken \
  --collect-all ddgs \
  --collect-all primp \
  --collect-submodules tiktoken_ext \
  --add-data "${BACKEND_DIR}/src/agentos/defaults:agentos/defaults" \
  --add-data "${BACKEND_DIR}/src/agentos/mcp/catalog.yaml:agentos/mcp" \
  src/agentos/gateway_entry.py

chmod +x "${GATEWAY_OUTPUT_DIR}/caberos-gateway/caberos-gateway"
echo "Built ${GATEWAY_OUTPUT_DIR}/caberos-gateway"

# Copy system-level skills into the Tauri resources directory so they get
# bundled into the desktop app and AGENTOS_SKILLS_DIR can point at them.
SKILLS_RESOURCE_DIR="${RESOURCE_DIR}/skills"
if [[ -d "${ROOT_DIR}/skills" ]]; then
  rm -rf "${SKILLS_RESOURCE_DIR}"
  cp -R "${ROOT_DIR}/skills" "${SKILLS_RESOURCE_DIR}"
  echo "Copied skills to ${SKILLS_RESOURCE_DIR}"
fi
