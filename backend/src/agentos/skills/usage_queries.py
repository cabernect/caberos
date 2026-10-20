"""Activation aggregates; manifest availability is deliberately not usage."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.run import Run
from ..models.skill_usage import SkillActivation


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()


def _recorded_task_activations():
    return (
        select(SkillActivation)
        .join(Run, Run.id == SkillActivation.run_id)
        .where(
            Run.is_test.is_(False),
            Run.trigger != "reflection",
            Run.agent_id == SkillActivation.agent_id,
        )
    )


async def skill_usage_totals(db: AsyncSession, skill_ids: list[str]) -> dict[str, dict]:
    """All retained activations for each stable skill, not a recent-page count."""
    if not skill_ids:
        return {}
    statement = (
        _recorded_task_activations()
        .with_only_columns(
            SkillActivation.skill_id,
            func.count(SkillActivation.id).label("activation_count"),
            func.max(SkillActivation.created_at).label("last_used_at"),
        )
        .where(SkillActivation.skill_id.in_(skill_ids))
        .group_by(SkillActivation.skill_id)
    )
    return {
        row.skill_id: {
            "activation_count": row.activation_count,
            "last_used_at": _iso_utc(row.last_used_at),
        }
        for row in (await db.execute(statement)).all()
    }


async def scoped_skill_usage(
    db: AsyncSession,
    *,
    skill_id: str,
    agent_id: str,
    contact_id: str,
) -> dict:
    """Minimal revision evidence, restricted to the caller's own subject."""
    scoped = _recorded_task_activations().where(
        SkillActivation.skill_id == skill_id,
        SkillActivation.agent_id == agent_id,
        Run.contact_id == contact_id,
    )
    totals = (
        await db.execute(
            scoped.with_only_columns(
                func.count(SkillActivation.id).label("activation_count"),
                func.max(SkillActivation.created_at).label("last_used_at"),
            )
        )
    ).one()
    records = (
        await db.scalars(
            scoped.order_by(SkillActivation.created_at.desc(), SkillActivation.id.desc()).limit(20)
        )
    ).all()
    run_ids = {record.run_id for record in records}
    runs = (
        {
            run.id: run
            for run in await db.scalars(
                select(Run).where(
                    Run.id.in_(run_ids),
                    Run.agent_id == agent_id,
                    Run.contact_id == contact_id,
                    Run.is_test.is_(False),
                    Run.trigger != "reflection",
                )
            )
        }
        if run_ids
        else {}
    )
    return {
        "activation_count": totals.activation_count,
        "last_used_at": _iso_utc(totals.last_used_at),
        "coverage": "recorded activations only; older use is unknown",
        "recent": [
            {
                "run_id": record.run_id,
                "session_id": runs[record.run_id].session_id,
                "status": runs[record.run_id].status,
                "created_at": _iso_utc(record.created_at),
            }
            for record in records
            if record.run_id in runs
        ],
    }
