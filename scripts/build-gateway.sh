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
  --collect-all pydantic_ai \
  --collect-all tiktoken \
  --collect-submodules tiktoken_ext \
  --add-data "${BACKEND_DIR}/src/agentos/defaults:agentos/defaults" \
  src/agentos/gateway_entry.py

chmod +x "${GATEWAY_OUTPUT_DIR}/caberos-gateway/caberos-gateway"
echo "Built ${GATEWAY_OUTPUT_DIR}/caberos-gateway"
