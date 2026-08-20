"""Telegram channel implementation (Ticket 08c).

Uses the Telegram Bot API for both receiving and delivering replies.
No SDK dependency — just plain HTTP calls via httpx.

Two modes:
  - **polling** (default): Bot calls getUpdates in a long-polling loop.
    Works from localhost — no public URL needed.
  - **webhook**: Telegram pushes updates to a public HTTPS URL.
    Lower latency, but requires ngrok/cloudflare tunnel or a public server.

Setup:
  1. Create a bot via @BotFather → get bot_token
  2. Add channel config in CaberOS (platform=telegram, bot_token, agent_id)
  3a. Polling mode: just enable the channel — CaberOS polls automatically
  3b. Webhook mode: set webhook via @BotFather → /setwebhook
      with url=https://your-domain/api/channels/telegram/webhook?agent_id={agent_id}
"""

import asyncio
import logging
from typing import Any

import httpx

from ..pipeline import InboundMessage
from ..ssl_utils import SSL_CERT_PATH
from .base import Channel, OutboundMessage, OutputConstraints
from .registry import register_channel_class

log = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30  # long-poll timeout in seconds (Telegram max is 50)


class TelegramChannel(Channel):
    """Telegram Bot API channel — polling or webhook inbound, HTTP POST outbound."""

    platform = "telegram"
    constraints = OutputConstraints(
        max_length=4096,
        supported_formatting=["markdown"],
        supports_typing_indicator=True,
    )

    def __init__(self, bot_token: str, agent_id: str, webhook_secret: str = ""):
        super().__init__(bot_token, agent_id, webhook_secret)
        self._poll_task: asyncio.Task | None = None
        self._last_update_id: int = 0

    async def receive(self, raw_payload: dict[str, Any]) -> InboundMessage | None:
        """Parse a Telegram update (webhook payload or polling result) into InboundMessage.

        Returns None if the payload is not a text message.
        """
        msg = raw_payload.get("message") or raw_payload.get("channel_post")
        if not msg:
            return None

        chat = msg.get("chat", {})
        msg.get("from", {})
        text = msg.get("text", "")
        if not text:
            return None  # Non-text message (sticker, photo, etc.) — skip for now

        chat_id = str(chat.get("id", ""))
        message_id = str(msg.get("message_id", ""))

        return InboundMessage(
            channel=self.platform,
            bot_id=self.agent_id,
            external_user_id=chat_id,
            text=text,
            message_id=message_id,
            session_id=None,
            new_session=False,
        )

    async def deliver(self, outbound: OutboundMessage) -> dict[str, Any]:
        """Send a reply via Telegram Bot API sendMessage.

        Splits long messages into multiple sends (4096 char limit).
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
                        "parse_mode": "Markdown",
                        "reply_to_message_id": outbound.reply_to_message_id
                        if last_message_id is None
                        else None,
                    },
                )
                if resp.get("ok"):
                    last_message_id = resp.get("result", {}).get("message_id")
                else:
                    # Markdown parse failed — retry as plain text
                    resp = await self._call_api(
                        "sendMessage",
                        {
                            "chat_id": outbound.chat_id,
                            "text": chunk,
                            "reply_to_message_id": outbound.reply_to_message_id
                            if last_message_id is None
                            else None,
                        },
                    )
                    if resp.get("ok"):
                        last_message_id = resp.get("result", {}).get("message_id")
            except Exception as e:
                log.error("Telegram deliver failed: %s", e)
                return {"success": False, "error": str(e)}

        return {"success": True, "error": None, "message_id": last_message_id}

    async def send_typing(self, chat_id: str) -> None:
        """Send 'typing...' chat action to Telegram."""
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
        """Call a Telegram Bot API method."""
        url = TELEGRAM_API_BASE.format(token=self.bot_token, method=method)
        async with httpx.AsyncClient(timeout=60, verify=SSL_CERT_PATH) as client:
            if body:
                resp = await client.post(url, json=body)
            else:
                resp = await client.get(url)
            return resp.json()

    # --- Polling mode ---

    async def start_polling(self) -> None:
        """Start the long-polling loop as a background task."""
        if self._poll_task and not self._poll_task.done():
            return  # Already polling

        # Delete any existing webhook (polling and webhook are mutually exclusive in Telegram)
        try:
            await self._call_api("deleteWebhook", {})
            log.info("Telegram: deleted existing webhook (switching to polling mode)")
        except Exception:
            pass

        self._poll_task = asyncio.create_task(self._poll_loop())
        log.info("Telegram: polling started for agent %s", self.agent_id)

    async def stop_polling(self) -> None:
        """Stop the polling loop."""
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        self._poll_task = None
        log.info("Telegram: polling stopped for agent %s", self.agent_id)

    async def _poll_loop(self) -> None:
        """Long-polling loop: call getUpdates repeatedly, process each update."""
        log.info("Telegram poll loop started for agent %s", self.agent_id)
        while True:
            try:
                resp = await self._call_api(
                    "getUpdates",
                    {
                        "offset": self._last_update_id + 1,
                        "timeout": POLL_TIMEOUT,
                        "allowed_updates": ["message", "channel_post"],
                    },
                )

                if not resp.get("ok"):
                    log.error("Telegram getUpdates failed: %s", resp.get("description"))
                    await asyncio.sleep(5)  # Back off on error
                    continue

                updates = resp.get("result", [])
                for update in updates:
                    update_id = update.get("update_id", 0)
                    if update_id > self._last_update_id:
                        self._last_update_id = update_id

                    # Process the update (fire-and-forget — don't block the poll loop)
                    asyncio.create_task(self._process_update(update))

            except asyncio.CancelledError:
                log.info("Telegram poll loop cancelled for agent %s", self.agent_id)
                raise
            except Exception as e:
                log.error("Telegram poll loop error: %s", e)
                await asyncio.sleep(5)  # Back off on unexpected error

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Process a single Telegram update: parse → run agent → deliver reply."""
        try:
            inbound = await self.receive(update)
            if inbound is None:
                return

            # Send typing indicator
            await self.send_typing(inbound.external_user_id)

            # Run the agent via the run manager so events are buffered
            # and the dashboard can stream channel runs via SSE.
            from ..run_manager import get_run, start_run

            result = await start_run(
                agent_id=self.agent_id,
                text=inbound.text,
                user_id=inbound.external_user_id,
                channel="telegram",
                trigger="user_message",
            )

            # Wait for the run to complete so we can deliver the reply
            run_id = result.get("run_id")
            if run_id:
                ctx = get_run(run_id)
                if ctx:
                    await ctx.task

            # Fetch and deliver the final answer (also for failed runs —
            # the error message is stored as an assistant message).
            if run_id:
                from sqlalchemy import select

                from ..db import async_session_factory
                from ..models.run import Message, Run

                async with async_session_factory() as db:
                    stmt = (
                        select(Message.content)
                        .join(Run, Message.run_id == Run.id)
                        .where(Run.id == run_id, Message.role == "assistant")
                        .order_by(Message.seq.desc())
                        .limit(1)
                    )
                    msg_result = await db.execute(stmt)
                    final_answer = msg_result.scalar_one_or_none()

                if final_answer:
                    outbound = OutboundMessage(
                        session_id=result["session_id"],
                        text=final_answer,
                        chat_id=inbound.external_user_id,
                        reply_to_message_id=inbound.message_id,
                    )
                    await self.deliver(outbound)

        except Exception:
            log.error("Telegram: failed to process update", exc_info=True)

    def format_text(self, text: str) -> str:
        """Pass through markdown — Telegram supports it natively."""
        return text


# Auto-register on import
register_channel_class("telegram", TelegramChannel)
