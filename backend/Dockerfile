# CaberOS backend — Python 3.12 + uv + bwrap (Linux sandbox)
# Build from repo root:  docker build -f backend/Dockerfile -t caberos-backend .
FROM python:3.12-slim AS base

# Install system dependencies:
# - bubblewrap (bwrap) for shell sandboxing (D28)
# - ca-certificates for HTTPS
# - git for workspace operations
# - curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    bubblewrap \
    ca-certificates \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# Copy backend source code
COPY backend/src/ ./src/
COPY backend/README.md ./

# Copy system-level skills (read-only, baked into image)
COPY skills/ /opt/caberos/skills/

# Create data directories (mounted as volumes at runtime)
RUN mkdir -p /data /data/workspaces /data/agents

ENV AGENTOS_CONTROL_PLANE_HOST=0.0.0.0 \
    AGENTOS_CONTROL_PLANE_PORT=8081 \
    AGENTOS_DB_PATH=/data/agentos.db \
    AGENTOS_SECRET_KEY_PATH=/data/secret.key \
    AGENTOS_WORKSPACE_ROOT=/data/workspaces \
    AGENTOS_AGENT_HOME_ROOT=/data/agents \
    AGENTOS_SKILLS_DIR=/opt/caberos/skills \
    PYDANTIC_DISABLE_PLUGINS=1

EXPOSE 8081

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -fsS http://localhost:8081/health || exit 1

CMD ["uv", "run", "uvicorn", "agentos.main:app", "--host", "0.0.0.0", "--port", "8081"]
