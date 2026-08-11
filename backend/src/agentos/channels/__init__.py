"""External messaging channels (Ticket 08c).

Each channel implementation (Telegram, Discord, Zalo, ...) parses inbound
webhooks into InboundMessage and delivers replies via the platform's API.
The pipeline is channel-agnostic — it runs the same way regardless of which
channel triggered the run.
"""

from .base import Channel, OutboundMessage, OutputConstraints
from .registry import (
    get_channel,
    load_all_channels,
    register_channel_class,
    reload_channel,
    remove_channel,
    stop_all_channels,
    list_active_channels,
)

# Import channel implementations to trigger auto-registration
from . import telegram  # noqa: F401 — registers TelegramChannel
from . import discord  # noqa: F401 — registers DiscordChannel
from . import zalo_oa  # noqa: F401 — registers ZaloOAChannel
from . import zalo_bot  # noqa: F401 — registers ZaloBotChannel

__all__ = [
    "Channel",
    "OutboundMessage",
    "OutputConstraints",
    "get_channel",
    "load_all_channels",
    "register_channel_class",
    "reload_channel",
    "remove_channel",
    "stop_all_channels",
    "list_active_channels",
]
