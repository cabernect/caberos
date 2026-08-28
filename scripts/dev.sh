#!/bin/bash
# Dev script — starts backend (and frontend when it exists) in dev mode.
set -e

cd "$(dirname "$0")/.."

# Check sandbox tool
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! command -v sandbox-exec &>/dev/null; then
        echo "ERROR: sandbox-exec not found (should be built into macOS)"
        exit 1
    fi
    echo "[dev] Sandbox: sandbox-exec (macOS)"
elif [[ "$OSTYPE" == "linux"* ]]; then
    if ! command -v bwrap &>/dev/null; then
        echo "ERROR: bwrap not found. Install with: apt install bubblewrap"
        exit 1
    fi
    echo "[dev] Sandbox: bwrap (Linux)"
fi

# Start backend
echo "[dev] Starting backend on :8081..."
cd backend
AGENTOS_RELOAD=true uv run python -m agentos.gateway_entry &
BACKEND_PID=$!

# Start frontend (when it exists)
if [ -f "../frontend/package.json" ]; then
    echo "[dev] Starting frontend on :5173..."
    cd ../frontend
    npm run dev &
    FRONTEND_PID=$!
else
    echo "[dev] No frontend yet — skipping (will be added in ticket 02)"
    FRONTEND_PID=""
fi

# Cleanup on exit
trap 'kill $BACKEND_PID 2>/dev/null; [ -n "$FRONTEND_PID" ] && kill $FRONTEND_PID 2>/dev/null' EXIT

echo "[dev] Press Ctrl+C to stop"
wait
