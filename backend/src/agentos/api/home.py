"""Today home aggregate (W13) — one payload for the landing page + sidebar badges.

Composes existing list surfaces into a single read model:
- counts: what powers the sidebar badges (running/total per section)
- agents: per-agent status for the "Your agents" card
- needs_you: unread notifications verified against live state where a
  live state exists (pending approvals, pending elicitations) so a stale
  inbox can't produce phantom cards. Dismiss = mark notification read.
- happened: terminal runs grouped by agent x day x outcome (7-day window)
- egress: what can leave this machine — providers, connected MCPs, channels
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_service import get_active_config
from ..auth import require_operator
from ..channels.registry import list_active_channels
from ..db import get_db
from ..mcp.registry import is_server_connected
from ..models.agent import Agent
from ..models.approval import ApprovalRequest
from ..models.channel_config import ChannelConfig
from ..models.document import Document
from ..models.elicitation import ElicitationRequest
from ..models.mcp import McpServer
from ..models.notification import Notification
from ..models.provider import Provider
from ..models.run import Run
from ..models.skill import Skill

router = APIRouter(prefix="/api/home", tags=["home"])

LIVE_RUN_STATES = ("running", "awaiting_approval")
TERMINAL_STATES = ("completed", "failed", "stopped", "interrupted")
HAPPENED_LOOKBACK_DAYS = 7
NEEDS_YOU_CAP = 20


class HomeAgent(BaseModel):
    id: str
    name: str
    status: str  # running | idle | paused | needs_setup
    last_run_at: datetime | None


class NeedsYouItem(BaseModel):
    notification_id: str
    kind: str
    title: str
    detail: str
    action_path: str | None
    agent_id: str | None
    agent_name: str | None
    created_at: datetime


class HappenedGroup(BaseModel):
    agent_id: str
    agent_name: str
    outcome: str  # completed | failed | stopped
    count: int
    window_start: datetime
    window_end: datetime


class HomeOut(BaseModel):
    counts: dict[str, int]
    agents: list[HomeAgent]
    needs_you: list[NeedsYouItem]
    happened: list[HappenedGroup]
    egress: dict


async def _notification_is_live(db: AsyncSession, n: Notification) -> bool:
    """Verify an unread notification still points at something actionable.

    Kinds with a real pending state are checked against it; pure event
    records (run_failed, schedule_failed, ...) pass through — their
    resolution is the operator dismissing them.
    """
    # entity_id is the run id on both kinds — live means the run still has
    # a pending request attached.
    if n.notification_type == "approval_required" and n.entity_id:
        row = await db.execute(
            select(ApprovalRequest.id).where(
                ApprovalRequest.run_id == n.entity_id,
                ApprovalRequest.status == "pending",
            )
        )
        return row.first() is not None
    if n.notification_type == "elicitation_required" and n.entity_id:
        row = await db.execute(
            select(ElicitationRequest.id).where(
                ElicitationRequest.run_id == n.entity_id,
                ElicitationRequest.status == "pending",
            )
        )
        return row.first() is not None
    return True


@router.get("")
async def get_home(
    db: AsyncSession = Depends(get_db),
    _op=Depends(require_operator),
) -> HomeOut:
    # -- agents + live-run state ------------------------------------------
    agents = (await db.execute(select(Agent).order_by(Agent.name))).scalars().all()

    running_rows = (
        (await db.execute(select(Run.agent_id).where(Run.status.in_(LIVE_RUN_STATES)).distinct()))
        .scalars()
        .all()
    )
    running_agents = set(running_rows)

    last_run_rows = await db.execute(
        select(Run.agent_id, func.max(Run.started_at))
        .where(Run.is_test.is_(False), Run.trigger != "reflection")
        .group_by(Run.agent_id)
    )
    last_run_by_agent = {agent_id: ts for agent_id, ts in last_run_rows.all()}

    home_agents: list[HomeAgent] = []
    for agent in agents:
        if agent.id in running_agents:
            status = "running"
        elif not agent.enabled:
            status = "paused"
        else:
            config = await get_active_config(db, agent.id)
            status = "idle" if (config and config.model.is_configured) else "needs_setup"
        home_agents.append(
            HomeAgent(
                id=agent.id,
                name=agent.name,
                status=status,
                last_run_at=last_run_by_agent.get(agent.id),
            )
        )

    # Recency ordering: live agents first, then whoever ran most recently;
    # never-run agents sink to the bottom. The ask bar defaults to index 0.
    status_rank = {"running": 0, "idle": 1, "needs_setup": 2, "paused": 3}
    home_agents.sort(
        key=lambda a: (
            status_rank.get(a.status, 4),
            -(a.last_run_at.timestamp() if a.last_run_at else 0),
        )
    )

    # -- section counts ----------------------------------------------------
    mcp_servers = (await db.execute(select(McpServer))).scalars().all()
    mcps_connected = sum(1 for s in mcp_servers if is_server_connected(s.id))

    skills_published = (
        await db.execute(select(func.count()).select_from(Skill).where(Skill.status == "published"))
    ).scalar_one()

    channel_configs = (await db.execute(select(ChannelConfig))).scalars().all()
    active_channels = {(c["platform"], c["agent_id"]) for c in list_active_channels()}

    vault_documents = (await db.execute(select(func.count()).select_from(Document))).scalar_one()

    counts = {
        "agents_running": len(running_agents),
        "agents_total": len(agents),
        "mcps_connected": mcps_connected,
        "mcps_total": len(mcp_servers),
        "skills_published": skills_published,
        "channels_active": len(active_channels),
        "channels_total": len(channel_configs),
        "vault_documents": vault_documents,
    }

    # -- needs you ---------------------------------------------------------
    unread = (
        (
            await db.execute(
                select(Notification)
                .where(Notification.read.is_(False))
                .order_by(Notification.created_at.desc())
                .limit(NEEDS_YOU_CAP * 2)
            )
        )
        .scalars()
        .all()
    )
    needs_you: list[NeedsYouItem] = []
    for n in unread:
        if len(needs_you) >= NEEDS_YOU_CAP:
            break
        if not await _notification_is_live(db, n):
            continue
        needs_you.append(
            NeedsYouItem(
                notification_id=n.id,
                kind=n.notification_type,
                title=n.title,
                detail=n.message,
                action_path=n.action_path,
                agent_id=n.agent_id,
                agent_name=n.agent_name,
                created_at=n.created_at,
            )
        )

    # -- what happened ------------------------------------------------------
    since = datetime.now(UTC) - timedelta(days=HAPPENED_LOOKBACK_DAYS)
    terminal_runs = (
        await db.execute(
            select(Run.agent_id, Run.status, Run.started_at, Run.completed_at)
            .where(
                Run.status.in_(TERMINAL_STATES),
                Run.is_test.is_(False),
                Run.trigger != "reflection",
                Run.started_at >= since,
            )
            .order_by(Run.started_at)
        )
    ).all()

    agent_names = {a.id: a.name for a in agents}
    groups: dict[tuple[str, str, str], HappenedGroup] = {}
    for agent_id, status, started_at, completed_at in terminal_runs:
        day = started_at.date().isoformat()
        outcome = (
            "completed"
            if status == "completed"
            else ("failed" if status == "failed" else "stopped")
        )
        key = (agent_id, day, outcome)
        end = completed_at or started_at
        if key not in groups:
            groups[key] = HappenedGroup(
                agent_id=agent_id,
                agent_name=agent_names.get(agent_id, agent_id),
                outcome=outcome,
                count=0,
                window_start=started_at,
                window_end=end,
            )
        g = groups[key]
        g.count += 1
        g.window_start = min(g.window_start, started_at)
        g.window_end = max(g.window_end, end)

    happened = sorted(groups.values(), key=lambda g: g.window_end, reverse=True)

    # -- what can leave this machine ----------------------------------------
    providers = (await db.execute(select(Provider).order_by(Provider.name))).scalars().all()
    egress = {
        "providers": [{"id": p.id, "name": p.name, "type": p.type} for p in providers],
        "mcps": [{"id": s.id, "name": s.name} for s in mcp_servers if is_server_connected(s.id)],
        "channels": [
            {
                "platform": c.platform,
                "agent_id": c.agent_id,
                "agent_name": agent_names.get(c.agent_id, c.agent_id),
                "connected": (c.platform, c.agent_id) in active_channels,
            }
            for c in channel_configs
        ],
    }

    return HomeOut(
        counts=counts,
        agents=home_agents,
        needs_you=needs_you,
        happened=happened,
        egress=egress,
    )
