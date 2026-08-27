"""FastAPI app entry point (D3, D4 — control plane on 127.0.0.1:8081)."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

# Enable INFO-level logging for agentos modules so channel loading, polling,
# and other startup activity is visible in the console.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

# Fix SSL certificate verification for LiteLLM's remote model catalog fetch
# and httpx requests. On macOS behind a corporate firewall/proxy, the system
# cert store (/etc/ssl/cert.pem) includes the proxy's CA, but Python's
# certifi bundle does not. Use the system cert store when available.
if "SSL_CERT_FILE" not in os.environ:
    if os.path.exists("/etc/ssl/cert.pem"):
        os.environ["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"
    else:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .api import (  # noqa: E402
    agent_files,
    agents,
    approvals,
    channels,
    chat,
    data,
    elicitation,
    knowledge,
    mcp,
    observability,
    providers,
    scheduler,
    settings,
    skills,
)
from .auth import router as auth_router  # noqa: E402
from .capabilities.builtin import register_builtin_capabilities  # noqa: E402
from .db import init_db  # noqa: E402

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
            from .agent_service import get_active_config
            from .memory.episodic import close_session, find_idle_sessions

            async with async_session_factory() as db:
                idle = await find_idle_sessions(db, idle_minutes=30)
                for session in idle:
                    agent_config = await get_active_config(db, session.agent_id)
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

    # Set a global exception handler so unhandled exceptions in background
    # tasks (e.g. MCP client internals) don't crash the process
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(
        lambda _loop, ctx: logging.getLogger("agentos.main").exception(
            f"Unhandled async exception: {ctx.get('exception', ctx.get('message', 'unknown'))}"
        )
    )

    register_builtin_capabilities()
    await init_db()
    # Seed default operator if none exists
    from .seed import seed_default_agents, seed_operator_if_needed

    await seed_operator_if_needed()
    await seed_default_agents()

    # Clean up runs stuck in "running" from a previous server crash.
    # Without this, the contact lock would block future runs for that contact.
    from sqlalchemy import update

    from .db import async_session_factory, engine
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

    # Clean up expired auth sessions from previous runs
    from .auth import cleanup_expired_sessions

    deleted = await cleanup_expired_sessions(engine)
    if deleted > 0:
        print(f"[startup] Cleaned up {deleted} expired session(s)")

    # Start the periodic session sweeper (Trigger 2 — backstop for abandoned sessions)
    _sweeper_task = asyncio.create_task(_session_sweeper())

    # Start the heartbeat scheduler
    from . import scheduler as scheduler_service

    await scheduler_service.start_scheduler()

    # Connect to all enabled MCP servers.
    # Run in a background task so slow MCP connections (e.g. npx downloading
    # packages) don't block the API from starting. Each connection is fully
    # isolated — failures are logged and skipped, and the client runs each
    # connection in its own asyncio task so anyio cancel scope errors can
    # never crash the process.
    from .mcp import registry as mcp_registry

    # Load tool definitions from DB first (so tools are available even
    # if a server fails to connect), then auto-connect all enabled servers
    # in the background.
    try:
        await mcp_registry.load_tools_from_db()
    except Exception:
        logging.getLogger("agentos.main").exception("MCP load_tools_from_db failed")

    async def _connect_mcp():
        try:
            await mcp_registry.connect_all()
        except Exception:
            logging.getLogger("agentos.main").exception(
                "MCP connect_all failed — some servers may be unavailable"
            )

    mcp_task = asyncio.create_task(_connect_mcp())
    mcp_task.add_done_callback(
        lambda t: t.exception() if not t.cancelled() and t.exception() else None
    )

    # Load all enabled external channels (Telegram, Discord, etc.) in the
    # background — channel startup involves network calls (webhook deletion,
    # API polls) that should not block the API from becoming available.
    from .channels import load_all_channels

    async def _load_channels():
        try:
            await load_all_channels()
        except Exception:
            logging.getLogger("agentos.main").exception(
                "Channel loading failed — some channels may be unavailable"
            )

    channel_task = asyncio.create_task(_load_channels())
    channel_task.add_done_callback(
        lambda t: t.exception() if not t.cancelled() and t.exception() else None
    )

    yield

    # Shutdown: disconnect all MCP servers
    await mcp_registry.disconnect_all()

    # Shutdown: stop all channel polling tasks
    from .channels import stop_all_channels

    await stop_all_channels()

    # Shutdown: stop the scheduler
    await scheduler_service.stop_scheduler()

    # Shutdown: cancel the sweeper
    if _sweeper_task:
        _sweeper_task.cancel()


app = FastAPI(
    title="CaberOS",
    description="Local-first AI Agent Operating System",
    version="0.1.5",
    lifespan=lifespan,
)

# CORS — allow the Vite dev server (localhost:5173) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://tauri.localhost",
        "tauri://localhost",
    ],
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
app.include_router(knowledge.router)
app.include_router(skills.router)
app.include_router(scheduler.router)
app.include_router(mcp.router)
app.include_router(channels.router)
app.include_router(observability.router)
app.include_router(settings.router)
app.include_router(data.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _get_app_version() -> str:
    """Get the application version from package metadata."""
    try:
        from importlib.metadata import version

        return version("agentos")
    except Exception:
        return "0.1.5"


@app.get("/api/version")
async def get_version() -> dict[str, str]:
    """Return the application version.

    Used by the About page in web mode to display the runtime version
    without importing Tauri APIs.
    """
    return {"version": _get_app_version()}
