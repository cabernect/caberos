#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="${CABEROS_GATEWAY_URL:-http://127.0.0.1:8081}"
LOG_FILE="${TMPDIR:-/tmp}/caberos-desktop-backend.log"
BACKEND_PID=""
STARTED_BACKEND=0

is_gateway_ready() {
  curl --silent --fail --max-time 1 "${GATEWAY_URL}/health" >/dev/null 2>&1
}

cleanup() {
  if [[ "${STARTED_BACKEND}" == "1" && -n "${BACKEND_PID}" ]]; then
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

if ! is_gateway_ready; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "CaberOS gateway is unavailable and uv is not installed." >&2
    exit 1
  fi

  (
    cd "${ROOT_DIR}/backend"
    exec uv run uvicorn agentos.main:app --port 8081 --host 127.0.0.1
  ) >"${LOG_FILE}" 2>&1 &
  BACKEND_PID=$!
  STARTED_BACKEND=1

  for _ in $(seq 1 60); do
    if is_gateway_ready; then
      break
    fi
    sleep 0.25
  done
fi

if ! is_gateway_ready; then
  echo "CaberOS gateway did not become ready. Backend log: ${LOG_FILE}" >&2
  tail -n 30 "${LOG_FILE}" >&2 || true
  exit 1
fi

cd "${ROOT_DIR}/frontend"

if curl --silent --fail --max-time 1 "http://localhost:5173" >/dev/null 2>&1; then
  echo "Reusing the existing Vite server on :5173."
  while true; do
    sleep 3600
  done
fi

npm run dev
