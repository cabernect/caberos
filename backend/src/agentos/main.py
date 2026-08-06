"""FastAPI app entry point (D3, D4 — control plane on 127.0.0.1:8081)."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import agent_files, agents, approvals, chat, elicitation, providers, scheduler, skills
from .auth import router as auth_router
from .capabilities.builtin import register_builtin_capabilities
from .db import init_db

# In-memory session store (token -> operator_id).
# TODO: persist in DB for restart survival (D4).
_sessions: dict[str, str] = {}

# Background sweeper task handle
_sweeper_task: asyncio.Task | None = None


async def _session_sweeper() -> None:
    """Periodic sweeper (Trigger 2): close idle sessions every 5 minutes.

    Catches sessions that were abandoned (user never came back) — the case
    the lazy trigger at run start can't handle. Costs one indexed query
    per sweep; does real work only when it finds stale sessions.
    """
    from .db import async_session_factory

    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            from .agent_service import AgentService
            from .memory.episodic import close_session, find_idle_sessions

            async with async_session_factory() as db:
                idle = await find_idle_sessions(db, idle_minutes=30)
                for session in idle:
                    service = AgentService(db)
                    agent_config = await service.get_agent(session.agent_id)
                    if agent_config:
                        await close_session(db, agent_config, session, session.contact_id)
                await db.commit()
                if idle:
                    print(f"[sweeper] Closed {len(idle)} idle session(s)")
        except Exception as e:
            print(f"[sweeper] Error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    global _sweeper_task

    register_builtin_capabilities()
    await init_db()
    # Seed default operator if none exists
    from .seed import seed_default_agents, seed_operator_if_needed

    await seed_operator_if_needed()
    await seed_default_agents()

    # Clean up runs stuck in "running" from a previous server crash.
    # Without this, the contact lock would block future runs for that contact.
    from sqlalchemy import update

    from .db import async_session_factory
    from .models.run import Run

    async with async_session_factory() as db:
        result = await db.execute(
            update(Run)
            .where(Run.status == "running")
            .values(status="failed", error="Server restarted — run was interrupted")
        )
        if result.rowcount > 0:
            print(f"[startup] Cleaned up {result.rowcount} stuck run(s)")
        await db.commit()

    # Start the periodic session sweeper (Trigger 2 — backstop for abandoned sessions)
    _sweeper_task = asyncio.create_task(_session_sweeper())

    # Start the heartbeat scheduler
    from . import scheduler as scheduler_service

    await scheduler_service.start_scheduler()

    yield

    # Shutdown: stop the scheduler
    await scheduler_service.stop_scheduler()

    # Shutdown: cancel the sweeper
    if _sweeper_task:
        _sweeper_task.cancel()


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
app.include_router(agent_files.router)
app.include_router(chat.router)
app.include_router(approvals.router)
app.include_router(elicitation.router)
app.include_router(skills.router)
app.include_router(scheduler.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
