"""External messaging channels (Ticket 08c).

Each channel implementation (Telegram, Discord, Zalo, ...) parses inbound
webhooks into InboundMessage and delivers replies via the platform's API.
The pipeline is channel-agnostic — it runs the same way regardless of which
channel triggered the run.
"""

# Import channel implementations to trigger auto-registration
from . import (
    discord,  # noqa: F401 — registers DiscordChannel
    telegram,  # noqa: F401 — registers TelegramChannel
    zalo_bot,  # noqa: F401 — registers ZaloBotChannel
    zalo_oa,  # noqa: F401 — registers ZaloOAChannel
)
from .base import Channel, OutboundMessage, OutputConstraints
from .registry import (
    get_channel,
    list_active_channels,
    load_all_channels,
    register_channel_class,
    reload_channel,
    remove_channel,
    stop_all_channels,
)

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
