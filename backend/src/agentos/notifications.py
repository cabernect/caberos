"""Persistent operator notification helpers."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models.notification import Notification


async def create_notification(
    db: AsyncSession,
    *,
    notification_type: str,
    severity: str,
    title: str,
    message: str,
    action_path: str | None = None,
    entity_id: str | None = None,
) -> Notification:
    existing = await db.scalar(
        select(Notification)
        .where(
            Notification.notification_type == notification_type,
            Notification.entity_id == entity_id,
            Notification.read.is_(False),
        )
        .limit(1)
    )
    if existing:
        return existing

    item = Notification(
        notification_type=notification_type,
        severity=severity,
        title=title,
        message=message,
        action_path=action_path,
        entity_id=entity_id,
    )
    db.add(item)
    await db.flush()
    return item
