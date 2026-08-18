"""Channel registry — process-global registry of active channel instances.

On startup, all enabled ChannelConfig rows are loaded and instantiated.
The registry is keyed by (platform, agent_id) for delivery lookups.
"""

import logging
from typing import Any

from sqlalchemy import select

from ..db import async_session_factory
from ..models.channel_config import ChannelConfig
from ..secret_store import decrypt
from .base import Channel

log = logging.getLogger(__name__)

# Platform → Channel class registry (for instantiation)
_channel_classes: dict[str, type[Channel]] = {}

# Active channel instances: (platform, agent_id) → Channel
_active_channels: dict[tuple[str, str], Channel] = {}


def register_channel_class(platform: str, cls: type[Channel]) -> None:
    """Register a Channel subclass for a platform name."""
    _channel_classes[platform] = cls


def get_channel(platform: str, agent_id: str) -> Channel | None:
    """Look up an active channel instance for delivery."""
    return _active_channels.get((platform, agent_id))


def list_active_channels() -> list[dict[str, Any]]:
    """List all active channels (for status reporting)."""
    return [{"platform": p, "agent_id": a, "connected": True} for (p, a) in _active_channels]


async def load_all_channels() -> None:
    """Load all enabled channel configs from DB and instantiate them.

    Called on startup (after init_db).
    """
    async with async_session_factory() as db:
        result = await db.execute(select(ChannelConfig).where(ChannelConfig.enabled))
        configs = result.scalars().all()

    for config in configs:
        await _instantiate_channel(config)


async def _instantiate_channel(config: ChannelConfig) -> Channel | None:
    """Create and register a Channel instance from a ChannelConfig row."""
    cls = _channel_classes.get(config.platform)
    if cls is None:
        log.warning("No channel class registered for platform: %s", config.platform)
        return None

    try:
        bot_token = decrypt(config.encrypted_bot_token)
        channel = cls(
            bot_token=bot_token,
            agent_id=config.agent_id,
            webhook_secret=config.webhook_secret,
        )
        _active_channels[(config.platform, config.agent_id)] = channel
        log.info(
            "Loaded channel: %s → agent %s (mode=%s)", config.platform, config.agent_id, config.mode
        )

        # Start polling if the channel supports it and mode is "polling"
        if config.mode == "polling" and hasattr(channel, "start_polling"):
            await channel.start_polling()

        return channel
    except Exception:
        log.error(
            "Failed to load channel %s for agent %s",
            config.platform,
            config.agent_id,
            exc_info=True,
        )
        return None


async def reload_channel(config: ChannelConfig) -> Channel | None:
    """Reload a single channel (after config update)."""
    # Stop the old channel (including polling tasks)
    old = _active_channels.pop((config.platform, config.agent_id), None)
    if old and hasattr(old, "stop_polling"):
        await old.stop_polling()

    if config.enabled:
        return await _instantiate_channel(config)
    return None


async def remove_channel(platform: str, agent_id: str) -> None:
    """Remove a channel from the active registry (after deletion)."""
    old = _active_channels.pop((platform, agent_id), None)
    if old and hasattr(old, "stop_polling"):
        await old.stop_polling()


async def stop_all_channels() -> None:
    """Stop all active channels (polling tasks, etc.) on shutdown."""
    for (platform, agent_id), channel in list(_active_channels.items()):
        if hasattr(channel, "stop_polling"):
            await channel.stop_polling()
        _active_channels.pop((platform, agent_id), None)
