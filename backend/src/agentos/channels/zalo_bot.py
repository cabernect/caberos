"""Zalo Bot Platform channel implementation (Ticket 08c).

Uses the Zalo Bot Platform API for delivering replies and receiving webhooks.

Zalo Bot Platform is the newer bot API (similar to Telegram Bot API) that allows
creating bots on Zalo. It's separate from Zalo OA (Official Account).

Key differences from Zalo OA:
  - Simpler auth: just a bot token (format: {bot_id}:{secret_key})
  - Telegram-like API: sendMessage, sendPhoto, sendChatAction, getUpdates
  - Webhook secret via X-Bot-Api-Secret-Token header
  - 2000 char message limit
  - Supports typing indicator

API base: https://bot-api.zaloplatforms.com/bot{TOKEN}/{method}

Webhook payload format (Zalo Bot Platform):
  {
    "event_name": "message.text.received",
    "message": {
      "date": 1775362520302,
      "chat": {"chat_type": "PRIVATE", "id": "chat_id_abc"},
      "message_id": "msg_id_abc",
      "from": {"id": "user_id", "is_bot": false, "display_name": "Nguyen Van A"},
      "text": "Xin chao"
    }
  }

Setup:
  1. Open Zalo on your phone
  2. Search for OA "Zalo Bot Manager"
  3. Tap "Create Bot" — enter a bot name (must start with "Bot")
  4. Zalo sends the Bot Token via message: {bot_id}:{secret_key}
  5. Add channel config in CaberOS (platform=zalo_bot, bot_token, agent_id)
  6. Webhook mode: set webhook via API or let CaberOS set it on startup
     url=https://your-domain/api/channels/zalo_bot/webhook?agent_id={agent_id}

API reference: https://bot.zaloplatforms.com/docs
"""

import asyncio
import hashlib
import hmac
import logging
from typing import Any

import httpx

from ..pipeline import InboundMessage
from ..ssl_utils import SSL_CERT_PATH
from .base import Channel, OutboundMessage, OutputConstraints
from .registry import register_channel_class

log = logging.getLogger(__name__)

ZALO_BOT_API_BASE = "https://bot-api.zaloplatforms.com/bot{token}/{method}"
POLL_TIMEOUT = 30  # long-poll timeout in seconds


class ZaloBotChannel(Channel):
    """Zalo Bot Platform channel — polling or webhook inbound, HTTP POST outbound."""

    platform = "zalo_bot"
    constraints = OutputConstraints(
        max_length=2000,
        supported_formatting=["markdown"],  # Zalo Bot supports markdown
        supports_typing_indicator=True,
    )

    def __init__(self, bot_token: str, agent_id: str, webhook_secret: str = ""):
        super().__init__(bot_token, agent_id, webhook_secret)
        self._poll_task: asyncio.Task | None = None
        self._last_update_id: int = 0
        # Derive webhook secret from bot token if not explicitly set
        # (Zalo Bot Platform convention: SHA256(botToken).hex()[:32])
        if not self.webhook_secret:
            self.webhook_secret = hashlib.sha256(bot_token.encode()).hexdigest()[:32]

    async def receive(self, raw_payload: dict[str, Any]) -> InboundMessage | None:
        """Parse a Zalo Bot webhook payload into InboundMessage.

        Processes "message.text.received" events. Other events (image, sticker, etc.)
        are ignored for now.
        """
        event_name = raw_payload.get("event_name", "")
        if event_name != "message.text.received":
            return None

        message = raw_payload.get("message", {})
        text = message.get("text", "")
        if not text:
            return None

        chat = message.get("chat", {})
        chat_id = chat.get("id", "")
        msg_id = message.get("message_id", "")
        from_user = message.get("from", {})

        # Ignore messages from bots
        if from_user.get("is_bot"):
            return None

        if not chat_id:
            return None

        return InboundMessage(
            channel=self.platform,
            bot_id=self.agent_id,
            external_user_id=chat_id,
            text=text,
            message_id=str(msg_id),
            session_id=None,
            new_session=False,
        )

    async def deliver(self, outbound: OutboundMessage) -> dict[str, Any]:
        """Send a reply via Zalo Bot API: POST /sendMessage.

        Splits long messages into multiple sends (2000 char limit).
        """
        formatted = self.format_text(outbound.text)
        chunks = self.split_message(formatted)

        last_message_id = None
        for chunk in chunks:
            try:
                resp = await self._call_api(
                    "sendMessage",
                    {
                        "chat_id": outbound.chat_id,
                        "text": chunk,
                        "parse_mode": "markdown",
                    },
                )
                if isinstance(resp, dict):
                    if not resp.get("ok", True):
                        err = resp.get("description", "unknown error")
                        log.error("Zalo Bot sendMessage failed: %s", err)
                        return {"success": False, "error": err}
                    last_message_id = resp.get("result", {}).get("message_id") or resp.get(
                        "message_id"
                    )
            except Exception as e:
                log.error("Zalo Bot deliver failed: %s", e)
                return {"success": False, "error": str(e)}

        return {"success": True, "error": None, "message_id": last_message_id}

    async def send_typing(self, chat_id: str) -> None:
        """Send typing indicator via Zalo Bot API: POST /sendChatAction."""
        try:
            await self._call_api(
                "sendChatAction",
                {
                    "chat_id": chat_id,
                    "action": "typing",
                },
            )
        except Exception:
            pass

    async def _call_api(self, method: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a Zalo Bot API method."""
        url = ZALO_BOT_API_BASE.format(token=self.bot_token, method=method)
        # Use a long timeout for getUpdates (long-poll), shorter for other methods
        timeout = 90 if method == "getUpdates" else 60
        async with httpx.AsyncClient(timeout=timeout, verify=SSL_CERT_PATH) as client:
            if body:
                resp = await client.post(url, json=body)
            else:
                resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    # --- Polling mode ---

    async def start_polling(self) -> None:
        """Start the long-polling loop as a background task."""
        if self._poll_task and not self._poll_task.done():
            return  # Already polling

        # Delete any existing webhook (polling and webhook are mutually exclusive)
        try:
            await self._call_api("deleteWebhook", {})
            log.info("Zalo Bot: deleted existing webhook (switching to polling mode)")
        except Exception:
            pass

        self._poll_task = asyncio.create_task(self._poll_loop())
        log.info("Zalo Bot: polling started for agent %s", self.agent_id)

    async def stop_polling(self) -> None:
        """Stop the polling loop."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        log.info("Zalo Bot: polling stopped for agent %s", self.agent_id)

    async def _poll_loop(self) -> None:
        """Long-polling loop: call getUpdates repeatedly, process each update.

        Zalo Bot getUpdates returns a single event object (not a list like Telegram):
          {"ok": true, "result": {"event_name": "...", "message": {...}}}
        When no update arrives during the long-poll window, it returns:
          {"ok": false, "error_code": 408, "description": "Request timeout"}
        """
        log.info("Zalo Bot poll loop started for agent %s", self.agent_id)
        while True:
            try:
                resp = await self._call_api(
                    "getUpdates",
                    {"timeout": str(POLL_TIMEOUT)},
                )

                if isinstance(resp, dict):
                    if not resp.get("ok", False):
                        if resp.get("error_code") == 408:
                            continue  # No updates during long-poll — normal, poll again
                        desc = resp.get("description", "unknown error")
                        log.error("Zalo Bot getUpdates failed: %s", desc)
                        await asyncio.sleep(5)
                        continue
                    result = resp.get("result")
                    # Real API: result is a single event object
                    # Legacy/test compat: result may be a list of updates
                    if isinstance(result, list):
                        for update in result:
                            asyncio.create_task(self._process_update(update))
                    elif isinstance(result, dict):
                        asyncio.create_task(self._process_update(result))
                elif isinstance(resp, list):
                    # Legacy/test compat: raw list of updates
                    for update in resp:
                        asyncio.create_task(self._process_update(update))

            except asyncio.CancelledError:
                log.info("Zalo Bot poll loop cancelled for agent %s", self.agent_id)
                raise
            except Exception as e:
                log.error("Zalo Bot poll loop error: %s", e)
                await asyncio.sleep(5)

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Process a single Zalo Bot update: parse → run agent → deliver reply."""
        try:
            inbound = await self.receive(update)
            if inbound is None:
                return

            log.info(
                "Zalo Bot: processing update from %s: %s",
                inbound.external_user_id,
                inbound.text[:50],
            )
            await self.send_typing(inbound.external_user_id)

            from ..runner import run_agent

            result = await run_agent(
                agent_id=self.agent_id,
                text=inbound.text,
                user_id=inbound.external_user_id,
                channel="zalo_bot",
                trigger="user_message",
            )

            log.info("Zalo Bot: agent run status=%s", result.get("status"))

            if result.get("status") == "completed":
                from sqlalchemy import select

                from ..db import async_session_factory
                from ..models.run import Message, Run

                async with async_session_factory() as db:
                    stmt = (
                        select(Message.content)
                        .join(Run, Message.run_id == Run.id)
                        .where(Run.id == result["run_id"], Message.role == "assistant")
                        .order_by(Message.seq.desc())
                        .limit(1)
                    )
                    msg_result = await db.execute(stmt)
                    final_answer = msg_result.scalar_one_or_none()

                if final_answer:
                    log.info(
                        "Zalo Bot: delivering reply (%d chars) to %s",
                        len(final_answer),
                        inbound.external_user_id,
                    )
                    outbound = OutboundMessage(
                        session_id=result["session_id"],
                        text=final_answer,
                        chat_id=inbound.external_user_id,
                        reply_to_message_id=inbound.message_id,
                    )
                    deliver_result = await self.deliver(outbound)
                    log.info("Zalo Bot: deliver result: %s", deliver_result)
                else:
                    log.warning(
                        "Zalo Bot: no assistant message found for run %s", result.get("run_id")
                    )

        except Exception:
            log.error("Zalo Bot: failed to process update", exc_info=True)

    def format_text(self, text: str) -> str:
        """Zalo Bot supports markdown — pass through."""
        return text

    def verify_webhook_secret(self, secret_token: str | None) -> bool:
        """Verify the X-Bot-Api-Secret-Token header.

        The secret is derived as SHA256(botToken).hex()[:32] by convention.
        """
        if not secret_token:
            return False
        return hmac.compare_digest(secret_token, self.webhook_secret)


# Auto-register on import
register_channel_class("zalo_bot", ZaloBotChannel)
