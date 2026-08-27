"""Operator notification API."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_operator
from ..db import get_db
from ..models.notification import Notification

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    notification_type: str
    severity: str
    title: str
    message: str
    action_path: str | None
    entity_id: str | None
    read: bool
    created_at: datetime


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    query = select(Notification).order_by(Notification.created_at.desc()).limit(100)
    if unread_only:
        query = query.where(Notification.read.is_(False))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    await db.execute(update(Notification).where(Notification.read.is_(False)).values(read=True))
    await db.commit()
    return {"updated": True}


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    _operator=Depends(require_operator),
):
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    await db.commit()
    return {"updated": True}
