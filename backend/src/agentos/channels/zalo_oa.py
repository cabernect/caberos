"""Zalo Official Account (OA) channel implementation (Ticket 08c).

Uses the Zalo OA OpenAPI v3.0 for delivering replies and receiving webhooks.

Zalo OA is the business/enterprise messaging platform on Zalo. It requires:
  - An OA (Official Account) registered at https://oa.zalo.me
  - An App with app_id + secret_key (OAuth login to get access_token)
  - The access_token is used as the bot_token in ChannelConfig

Two message types for replies:
  - "cs" (customer service): reply within 7 days of user interaction
  - "transaction": transactional messages (template-based)
  - "promotion": promotional messages (template-based)

We use "cs" for conversational replies (agent responses).

Webhook events from Zalo OA:
  - user_send_text: user sent a text message
  - follow: user followed the OA
  - unfollow: user unfollowed
  - user_send_image, user_send_file, etc.

Webhook payload format (Zalo OA):
  {
    "event_name": "user_send_text",
    "message": {
      "text": "hello",
      "msg_id": "abc123",
      "sender": {
        "id": "user_zalo_id",
        "display_name": "Nguyen Van A"
      }
    }
  }

API reference: https://oa.zalo.me/home/documents

Setup:
  1. Register OA at https://oa.zalo.me
  2. Create an App, get app_id + secret_key
  3. OAuth login to get access_token (store as bot_token in ChannelConfig)
  4. Configure webhook URL in OA settings:
     url=https://your-domain/api/channels/zalo_oa/webhook?agent_id={agent_id}
  5. Note: Zalo OA requires HTTPS and ideally a Vietnam IP for full user info
"""

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

ZALO_OA_API_BASE = "https://openapi.zalo.me/v3.0/oa/message"


class ZaloOAChannel(Channel):
    """Zalo Official Account channel — webhook inbound, HTTP POST outbound."""

    platform = "zalo_oa"
    constraints = OutputConstraints(
        max_length=None,  # Zalo OA doesn't have a strict char limit for cs messages
        supported_formatting=["plain"],  # Zalo OA text messages are plain text
        supports_typing_indicator=False,  # Zalo OA has no typing indicator API
    )

    def __init__(self, bot_token: str, agent_id: str, webhook_secret: str = ""):
        super().__init__(bot_token, agent_id, webhook_secret)
        # bot_token = access_token from Zalo OA OAuth
        self._access_token = bot_token

    async def receive(self, raw_payload: dict[str, Any]) -> InboundMessage | None:
        """Parse a Zalo OA webhook payload into InboundMessage.

        Only processes "user_send_text" events. Other events (follow, image, etc.)
        are ignored for now.
        """
        event_name = raw_payload.get("event_name", "")
        if event_name != "user_send_text":
            return None

        message = raw_payload.get("message", {})
        text = message.get("text", "")
        if not text:
            return None

        sender = message.get("sender", {})
        user_id = sender.get("id", "")
        msg_id = message.get("msg_id", "")

        if not user_id:
            return None

        return InboundMessage(
            channel=self.platform,
            bot_id=self.agent_id,
            external_user_id=user_id,
            text=text,
            message_id=str(msg_id),
            session_id=None,
            new_session=False,
        )

    async def deliver(self, outbound: OutboundMessage) -> dict[str, Any]:
        """Send a reply via Zalo OA API: POST /v3.0/oa/message/cs

        Uses "cs" (customer service) message type for conversational replies.
        """
        formatted = self.format_text(outbound.text)
        chunks = self.split_message(formatted)

        last_msg_id = None
        for chunk in chunks:
            try:
                resp = await self._call_api(
                    "cs",
                    {
                        "recipient": {"user_id": outbound.chat_id},
                        "message": {"text": chunk},
                    },
                )
                # Zalo OA returns {"data": {"message_id": "..."}, "error": 0, "message": "Success"}
                if resp.get("error") == 0 or resp.get("error") is None:
                    last_msg_id = resp.get("data", {}).get("message_id")
                else:
                    error_msg = resp.get("message", "Unknown Zalo OA error")
                    log.error("Zalo OA deliver failed: %s (error=%s)", error_msg, resp.get("error"))
                    return {"success": False, "error": f"Zalo OA: {error_msg}"}
            except Exception as e:
                log.error("Zalo OA deliver failed: %s", e)
                return {"success": False, "error": str(e)}

        return {"success": True, "error": None, "message_id": last_msg_id}

    async def _call_api(self, message_type: str, body: dict[str, Any]) -> dict[str, Any]:
        """Call the Zalo OA message API."""
        url = f"{ZALO_OA_API_BASE}/{message_type}"
        headers = {
            "access_token": self._access_token,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30, verify=SSL_CERT_PATH) as client:
            resp = await client.post(url, json=body, headers=headers)
            return resp.json()

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        """Verify Zalo OA webhook MAC signature.

        Zalo OA uses HMAC-SHA256 with the OA secret key to sign webhook bodies.
        The signature is sent in the X-ZEvent-Signature header.
        """
        if not self.webhook_secret:
            return True  # No secret configured — skip verification
        expected = hmac.new(
            self.webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


# Auto-register on import
register_channel_class("zalo_oa", ZaloOAChannel)
