"""FastAPI app entry point (D3, D4 — control plane on 127.0.0.1:8081)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .capabilities.builtin import register_builtin_capabilities
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    register_builtin_capabilities()
    await init_db()
    yield


app = FastAPI(
    title="CaberOS",
    description="Local-first AI Agent Operating System",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
