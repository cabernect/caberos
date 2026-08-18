"""Discord channel implementation (Ticket 08c).

Uses the Discord Bot API for receiving messages (via webhook or gateway) and
delivering replies. No SDK dependency — just plain HTTP calls via httpx.

Two modes:
  - **webhook** (default): Discord pushes interactions/messages to a public HTTPS URL.
    Requires a public URL (ngrok/cloudflare tunnel or VPS).
  - **polling**: Bot polls Discord gateway via WebSocket (not implemented yet —
    Discord's gateway is WebSocket-based, not HTTP long-polling like Telegram).

Setup:
  1. Create a bot at https://discord.com/developers/applications
  2. Enable "Message Content Intent" in Bot settings
  3. Add bot to your server with scopes=bot, permissions=Send Messages
  4. Add channel config in CaberOS (platform=discord, bot_token, agent_id)
  5. Webhook mode: set webhook URL in Discord Developer Portal → Webhooks
     url=https://your-domain/api/channels/discord/webhook?agent_id={agent_id}

Discord API reference: https://discord.com/developers/docs/intro
"""

import logging
from typing import Any

import httpx

from ..pipeline import InboundMessage
from ..ssl_utils import SSL_CERT_PATH
from .base import Channel, OutboundMessage, OutputConstraints
from .registry import register_channel_class

log = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordChannel(Channel):
    """Discord Bot API channel — webhook inbound, HTTP POST outbound."""

    platform = "discord"
    constraints = OutputConstraints(
        max_length=2000,
        supported_formatting=["markdown"],
        supports_typing_indicator=False,  # Discord typing requires gateway (WebSocket)
    )

    def __init__(self, bot_token: str, agent_id: str, webhook_secret: str = ""):
        super().__init__(bot_token, agent_id, webhook_secret)
        # Discord bot tokens need the "Bot " prefix for API calls
        self._auth_header = (
            self.bot_token if self.bot_token.startswith("Bot ") else f"Bot {self.bot_token}"
        )

    async def receive(self, raw_payload: dict[str, Any]) -> InboundMessage | None:
        """Parse a Discord webhook payload into InboundMessage.

        Discord sends different payload types:
        - Interaction (slash command): type=2 (APPLICATION_COMMAND)
        - Message create: via gateway event (not webhook — but we support it if forwarded)
        """
        # Discord interaction (slash command or message component)
        if raw_payload.get("type") == 1:
            # PING — Discord verification, not a message
            return None

        # Slash command interaction (type=2, data.name = command name)
        if raw_payload.get("type") == 2:
            data = raw_payload.get("data", {})
            channel_id = raw_payload.get("channel_id", "")
            # Build text from options first, then fall back to value, then command name
            options = data.get("options", [])
            if options:
                text = " ".join(str(opt.get("value", "")) for opt in options if opt.get("value"))
            else:
                text = data.get("value") or data.get("name", "")
            if not text or not channel_id:
                return None
            return InboundMessage(
                channel=self.platform,
                bot_id=self.agent_id,
                external_user_id=channel_id,
                text=text,
                message_id=str(raw_payload.get("id", "")),
                session_id=None,
                new_session=False,
            )

        # Gateway-style message create event (if forwarded by a gateway adapter)
        if raw_payload.get("type") == 0 and raw_payload.get("t") == "MESSAGE_CREATE":
            data = raw_payload.get("d", {})
            # Ignore bot messages (including our own)
            author = data.get("author", {})
            if author.get("bot"):
                return None
            channel_id = data.get("channel_id", "")
            text = data.get("content", "")
            if not text or not channel_id:
                return None
            return InboundMessage(
                channel=self.platform,
                bot_id=self.agent_id,
                external_user_id=channel_id,
                text=text,
                message_id=str(data.get("id", "")),
                session_id=None,
                new_session=False,
            )

        # Direct message payload (from webhook forwarding)
        content = raw_payload.get("content", "")
        channel_id = raw_payload.get("channel_id", "")
        author = raw_payload.get("author", {})
        if content and channel_id and not author.get("bot"):
            return InboundMessage(
                channel=self.platform,
                bot_id=self.agent_id,
                external_user_id=channel_id,
                text=content,
                message_id=str(raw_payload.get("id", "")),
                session_id=None,
                new_session=False,
            )

        return None

    async def deliver(self, outbound: OutboundMessage) -> dict[str, Any]:
        """Send a reply via Discord Bot API: POST /channels/{channel_id}/messages.

        Splits long messages into multiple sends (2000 char limit).
        """
        formatted = self.format_text(outbound.text)
        chunks = self.split_message(formatted)

        last_message_id = None
        for chunk in chunks:
            try:
                resp = await self._call_api(
                    f"/channels/{outbound.chat_id}/messages",
                    {"content": chunk},
                )
                last_message_id = resp.get("id")
            except Exception as e:
                log.error("Discord deliver failed: %s", e)
                return {"success": False, "error": str(e)}

        return {"success": True, "error": None, "message_id": last_message_id}

    async def _call_api(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a Discord API endpoint."""
        url = f"{DISCORD_API_BASE}{path}"
        headers = {"Authorization": self._auth_header}
        async with httpx.AsyncClient(timeout=30, verify=SSL_CERT_PATH) as client:
            if body:
                resp = await client.post(url, json=body, headers=headers)
            else:
                resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {}
            return resp.json()

    def format_text(self, text: str) -> str:
        """Discord supports standard markdown — pass through."""
        return text


# Auto-register on import
register_channel_class("discord", DiscordChannel)
