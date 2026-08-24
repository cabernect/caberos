"""OperatorSession model — persistent authentication sessions (v0.1.3).

Sessions are stored in the DB so they survive backend restarts and desktop
updates. Only the token hash is stored — never the raw session token.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, delete
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class OperatorSession(Base, IdMixin, TimestampMixin):
    """A persisted operator session token.

    The raw token is never stored — only its SHA-256 hash.
    """

    __tablename__ = "operator_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    operator_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


async def cleanup_expired_sessions(engine: AsyncEngine) -> int:
    """Delete all expired session rows. Returns the count deleted."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    now = datetime.now(UTC)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        result = await db.execute(delete(OperatorSession).where(OperatorSession.expires_at < now))
        await db.commit()
        return result.rowcount
