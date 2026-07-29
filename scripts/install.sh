#!/bin/bash
# Install script — checks deps and sets up the environment.
set -e

cd "$(dirname "$0")/.."

echo "[install] Checking dependencies..."

# Check Python 3.12
if ! python3 --version 2>&1 | grep -q "3.12"; then
    echo "[install] Python 3.12 not found as default, but uv will manage it."
fi

# Check uv
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "[install] uv: $(uv --version)"

# Check Node.js
if ! command -v node &>/dev/null; then
    echo "ERROR: Node.js not found. Install: https://nodejs.org/"
    exit 1
fi
echo "[install] Node.js: $(node --version)"

# Check sandbox tool
if [[ "$OSTYPE" == "darwin"* ]]; then
    if command -v sandbox-exec &>/dev/null; then
        echo "[install] Sandbox: sandbox-exec (macOS) ✓"
    else
        echo "ERROR: sandbox-exec not found (should be built into macOS)"
        exit 1
    fi
elif [[ "$OSTYPE" == "linux"* ]]; then
    if command -v bwrap &>/dev/null; then
        echo "[install] Sandbox: bwrap (Linux) ✓"
    else
        echo "ERROR: bwrap not found. Install: apt install bubblewrap"
        exit 1
    fi
else
    echo "ERROR: Unsupported platform. Use WSL2 on Windows."
    exit 1
fi

# Setup backend
echo "[install] Setting up backend..."
cd backend
uv sync
echo "[install] Backend dependencies installed."

# Setup frontend (when it exists)
cd ..
if [ -f "frontend/package.json" ]; then
    echo "[install] Setting up frontend..."
    cd frontend
    npm install
    cd ..
    echo "[install] Frontend dependencies installed."
fi

# Create data directories
mkdir -p data/workspaces
echo "[install] Created data/ and data/workspaces/"

# Run seed
echo "[install] Seeding database..."
cd backend
uv run python -m agentos.seed
cd ..

echo ""
echo "[install] Done! Next steps:"
echo "  1. Start dev server: ./scripts/dev.sh"
echo "  2. Run smoke test: python scripts/smoke.py test-agent \"echo hello\""
