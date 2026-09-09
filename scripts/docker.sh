#!/usr/bin/env bash
# CaberOS Docker/Podman — build and run the full stack
# Usage:
#   ./scripts/docker.sh         # build + up
#   ./scripts/docker.sh down     # stop + remove
#   ./scripts/docker.sh logs     # tail logs
#   ./scripts/docker.sh rebuild  # force rebuild images
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env.docker}"
if [ ! -f "$ENV_FILE" ]; then
  ENV_FILE=".env.docker.example"
fi

# Auto-detect container runtime: prefer docker, fall back to podman
if command -v docker &>/dev/null; then
  COMPOSE="docker compose"
elif command -v podman &>/dev/null; then
  # podman-compose is the Python-based compose provider
  COMPOSE="podman-compose"
else
  echo "ERROR: Neither docker nor podman found."
  echo "  Docker: https://docs.docker.com/get-docker/"
  echo "  Podman: https://podman.io/docs/installation"
  exit 1
fi

echo "[docker] Using: $COMPOSE"

CMD="${1:-up}"

case "$CMD" in
  up)
    $COMPOSE --env-file "$ENV_FILE" up --build -d
    echo ""
    echo "CaberOS is running at http://localhost:${CABEROS_PORT:-8080}"
    echo "Default login: admin / admin"
    echo ""
    echo "Logs: ./scripts/docker.sh logs"
    echo "Stop: ./scripts/docker.sh down"
    ;;
  down)
    $COMPOSE --env-file "$ENV_FILE" down
    ;;
  logs)
    $COMPOSE --env-file "$ENV_FILE" logs -f
    ;;
  rebuild)
    $COMPOSE --env-file "$ENV_FILE" build --no-cache
    $COMPOSE --env-file "$ENV_FILE" up -d
    ;;
  *)
    echo "Usage: $0 {up|down|logs|rebuild}"
    exit 1
    ;;
esac
