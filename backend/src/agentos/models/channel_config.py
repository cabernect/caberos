"""ChannelConfig model — external messaging channel configuration (Ticket 08c)."""

from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

# Valid approval policy values for external channels (v0.1.3).
# - auto_approve: execute approval-required tools without waiting
# - operator: create a pending approval for the dashboard operator
# - deny: block approval-required tools and audit the denial
VALID_APPROVAL_POLICIES = ("auto_approve", "operator", "deny")


class ChannelConfig(Base, IdMixin, TimestampMixin):
    """Configuration for an external messaging channel (Telegram, Discord, Zalo, ...).

    Each row represents one bot on one platform connected to one agent.
    The bot_token is encrypted via the Fernet secret store.
    """

    __tablename__ = "channel_configs"
    __table_args__ = (UniqueConstraint("platform", "agent_id", name="uq_channel_platform_agent"),)

    platform: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # telegram, discord, zalo, ...
    agent_id: Mapped[str] = mapped_column(
        String(36), nullable=False
    )  # which agent handles this channel
    encrypted_bot_token: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet-encrypted
    webhook_secret: Mapped[str] = mapped_column(
        String(255), default=""
    )  # optional secret for webhook validation
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # "polling" (bot polls platform — works from localhost) or "webhook" (platform pushes to public URL)
    mode: Mapped[str] = mapped_column(String(20), default="polling")
    # Extra config as JSON (e.g. Discord guild_id, Zalo OA ID, etc.)
    extra_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Approval policy for approval-required tools triggered by this channel.
    # v0.1.3: replaces the hardcoded channel bypass.
    # Existing channels default to "auto_approve" to preserve behavior.
    # New channels default to "deny" for safety.
    approval_policy: Mapped[str] = mapped_column(String(20), default="deny")
