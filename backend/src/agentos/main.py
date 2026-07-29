"""FastAPI app entry point (D3, D4 — control plane on 127.0.0.1:8081)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import agents, chat, providers
from .auth import router as auth_router
from .capabilities.builtin import register_builtin_capabilities
from .db import init_db

# In-memory session store (token -> operator_id).
# TODO: persist in DB for restart survival (D4).
_sessions: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    register_builtin_capabilities()
    await init_db()
    # Seed default operator if none exists
    from .seed import seed_operator_if_needed

    await seed_operator_if_needed()
    yield


app = FastAPI(
    title="CaberOS",
    description="Local-first AI Agent Operating System",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server (localhost:5173) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(providers.router)
app.include_router(agents.router)
app.include_router(chat.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
