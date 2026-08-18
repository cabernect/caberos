"""Channel base abstraction (Ticket 08c).

A Channel is a bidirectional adapter between CaberOS and an external messaging
platform (Telegram, Discord, Zalo, ...). It:

  1. Parses inbound webhooks into InboundMessage (already defined in pipeline.py)
  2. Delivers OutboundMessage replies via the platform's API
  3. Optionally sends typing indicators while the agent is running

The dashboard chat is implementation #1 (built directly in chat.py, not via
this ABC — it uses SSE streaming instead of HTTP delivery). Each external
platform is implementation #2, #3, etc.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OutputConstraints:
    """Platform-specific output limits."""

    max_length: int | None = None  # None = no hard limit
    supported_formatting: list[str] = field(default_factory=lambda: ["plain"])
    supports_typing_indicator: bool = False


@dataclass
class OutboundMessage:
    """Normalized outbound reply (produced by pipeline, consumed by channels)."""

    session_id: str
    text: str
    chat_id: str  # platform-specific chat/channel ID to deliver to
    reply_to_message_id: str | None = None  # original message ID (for reply threading)


class Channel(ABC):
    """Base class for external messaging channels.

    Subclasses implement:
      - receive(): parse raw webhook payload → InboundMessage
      - deliver(): send OutboundMessage via platform API
      - send_typing(): (optional) send typing indicator
    """

    platform: str = ""  # "telegram", "discord", "zalo", ...
    constraints: OutputConstraints = OutputConstraints()

    def __init__(self, bot_token: str, agent_id: str, webhook_secret: str = ""):
        self.bot_token = bot_token
        self.agent_id = agent_id
        self.webhook_secret = webhook_secret

    @abstractmethod
    async def receive(self, raw_payload: dict[str, Any]) -> Any:
        """Parse a raw webhook payload into an InboundMessage.

        Returns InboundMessage (from pipeline.py) with channel=self.platform,
        bot_id=self.agent_id, and platform-specific fields mapped.
        """
        ...

    @abstractmethod
    async def deliver(self, outbound: OutboundMessage) -> dict[str, Any]:
        """Deliver an OutboundMessage to the platform.

        Returns a dict with at least {"success": bool, "error": str | None}.
        May split long messages into multiple API calls per output_constraints.
        """
        ...

    async def send_typing(self, chat_id: str) -> None:
        """Send a typing indicator to the platform (if supported)."""
        if not self.constraints.supports_typing_indicator:
            return
        # Override in subclass

    def format_text(self, text: str) -> str:
        """Format text for the platform's supported formatting.

        Default: strip markdown to plain text. Subclasses can override
        to convert to platform-specific formats (e.g. Telegram MarkdownV2).
        """
        if "markdown" in self.constraints.supported_formatting:
            return text
        # Strip basic markdown to plain text
        import re

        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        plain = re.sub(r"`(.+?)`", r"\1", plain)
        plain = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", plain)
        return plain

    def split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit the platform's max_length."""
        if self.constraints.max_length is None:
            return [text]
        max_len = self.constraints.max_length
        if len(text) <= max_len:
            return [text]
        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= max_len:
                chunks.append(remaining)
                break
            # Try to split at a newline near the limit
            split_at = remaining.rfind("\n", 0, max_len)
            if split_at < max_len // 2:
                split_at = remaining.rfind(" ", 0, max_len)
            if split_at < 0:
                split_at = max_len
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        return chunks
