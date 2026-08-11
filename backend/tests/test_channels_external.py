"""Tests for Discord and Zalo channels (Ticket 08c).

Covers:
- Discord channel: receive (slash command, message create, DM), deliver, format
- Zalo OA channel: receive (user_send_text), deliver, webhook verification
- Zalo Bot channel: receive (message.text.received), deliver, typing, polling
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agentos.channels.base import OutboundMessage, OutputConstraints
from agentos.channels.discord import DiscordChannel
from agentos.channels.zalo_oa import ZaloOAChannel
from agentos.channels.zalo_bot import ZaloBotChannel


# --- Discord channel ---

class TestDiscordChannel:
    @pytest.mark.asyncio
    async def test_receive_slash_command(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        payload = {
            "type": 2,
            "id": "interaction-1",
            "channel_id": "987654321",
            "data": {"name": "ask", "value": "What is the weather?"},
            "member": {"user": {"id": "111", "username": "alice"}},
        }
        inbound = await ch.receive(payload)
        assert inbound is not None
        assert inbound.channel == "discord"
        assert inbound.bot_id == "agent-1"
        assert inbound.external_user_id == "987654321"
        assert inbound.text == "What is the weather?"
        assert inbound.message_id == "interaction-1"

    @pytest.mark.asyncio
    async def test_receive_slash_command_with_options(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        payload = {
            "type": 2,
            "id": "interaction-2",
            "channel_id": "channel-1",
            "data": {
                "name": "ask",
                "options": [
                    {"value": "hello"},
                    {"value": "world"},
                ],
            },
            "member": {"user": {"id": "111", "username": "bob"}},
        }
        inbound = await ch.receive(payload)
        assert inbound is not None
        assert "hello" in inbound.text
        assert "world" in inbound.text

    @pytest.mark.asyncio
    async def test_receive_message_create_event(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        payload = {
            "type": 0,
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "msg-123",
                "channel_id": "chan-456",
                "author": {"id": "user-1", "username": "alice", "bot": False},
                "content": "Hello from Discord!",
            },
        }
        inbound = await ch.receive(payload)
        assert inbound is not None
        assert inbound.channel == "discord"
        assert inbound.external_user_id == "chan-456"
        assert inbound.text == "Hello from Discord!"
        assert inbound.message_id == "msg-123"

    @pytest.mark.asyncio
    async def test_receive_ignores_bot_messages(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        payload = {
            "type": 0,
            "t": "MESSAGE_CREATE",
            "d": {
                "id": "msg-123",
                "channel_id": "chan-456",
                "author": {"id": "bot-1", "username": "MyBot", "bot": True},
                "content": "Bot reply",
            },
        }
        inbound = await ch.receive(payload)
        assert inbound is None

    @pytest.mark.asyncio
    async def test_receive_ping_returns_none(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        inbound = await ch.receive({"type": 1})
        assert inbound is None

    @pytest.mark.asyncio
    async def test_receive_dm_payload(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        payload = {
            "id": "msg-789",
            "channel_id": "dm-channel-1",
            "author": {"id": "user-2", "bot": False},
            "content": "Direct message",
        }
        inbound = await ch.receive(payload)
        assert inbound is not None
        assert inbound.external_user_id == "dm-channel-1"
        assert inbound.text == "Direct message"

    @pytest.mark.asyncio
    async def test_deliver_calls_api(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        outbound = OutboundMessage(
            session_id="s1",
            text="Hello from CaberOS!",
            chat_id="channel-123",
        )
        mock_response = {"id": "msg-999", "content": "Hello from CaberOS!"}
        with patch.object(ch, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await ch.deliver(outbound)
        assert result["success"] is True
        assert result["message_id"] == "msg-999"

    @pytest.mark.asyncio
    async def test_deliver_splits_long_message(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        long_text = "a" * 3000  # Exceeds 2000 limit
        outbound = OutboundMessage(
            session_id="s1",
            text=long_text,
            chat_id="channel-123",
        )
        call_count = 0

        async def mock_call_api(path, body):
            nonlocal call_count
            call_count += 1
            return {"id": f"msg-{call_count}"}

        with patch.object(ch, "_call_api", new_callable=AsyncMock, side_effect=mock_call_api):
            result = await ch.deliver(outbound)
        assert result["success"] is True
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_deliver_api_error(self):
        ch = DiscordChannel(bot_token="test-token", agent_id="agent-1")
        outbound = OutboundMessage(
            session_id="s1",
            text="Hello",
            chat_id="channel-123",
        )
        with patch.object(ch, "_call_api", new_callable=AsyncMock, side_effect=Exception("401 Unauthorized")):
            result = await ch.deliver(outbound)
        assert result["success"] is False
        assert "401" in result["error"]

    def test_auth_header_adds_bot_prefix(self):
        ch = DiscordChannel(bot_token="my-token", agent_id="a1")
        assert ch._auth_header == "Bot my-token"

    def test_auth_header_keeps_existing_prefix(self):
        ch = DiscordChannel(bot_token="Bot my-token", agent_id="a1")
        assert ch._auth_header == "Bot my-token"

    def test_format_text_passes_markdown(self):
        ch = DiscordChannel(bot_token="test", agent_id="a1")
        assert ch.format_text("**bold** text") == "**bold** text"

    def test_max_length_2000(self):
        ch = DiscordChannel(bot_token="test", agent_id="a1")
        assert ch.constraints.max_length == 2000


# --- Zalo OA channel ---

class TestZaloOAChannel:
    @pytest.mark.asyncio
    async def test_receive_text_message(self):
        ch = ZaloOAChannel(bot_token="access-token-123", agent_id="agent-1")
        payload = {
            "event_name": "user_send_text",
            "message": {
                "text": "Xin chao!",
                "msg_id": "msg-abc",
                "sender": {
                    "id": "user-zalo-id",
                    "display_name": "Nguyen Van A",
                },
            },
        }
        inbound = await ch.receive(payload)
        assert inbound is not None
        assert inbound.channel == "zalo_oa"
        assert inbound.bot_id == "agent-1"
        assert inbound.external_user_id == "user-zalo-id"
        assert inbound.text == "Xin chao!"
        assert inbound.message_id == "msg-abc"

    @pytest.mark.asyncio
    async def test_receive_ignores_non_text_events(self):
        ch = ZaloOAChannel(bot_token="access-token-123", agent_id="agent-1")
        # follow event
        inbound = await ch.receive({"event_name": "follow", "message": {}})
        assert inbound is None
        # image event
        inbound = await ch.receive({"event_name": "user_send_image", "message": {"image": "..."}})
        assert inbound is None

    @pytest.mark.asyncio
    async def test_receive_no_sender_returns_none(self):
        ch = ZaloOAChannel(bot_token="access-token-123", agent_id="agent-1")
        payload = {
            "event_name": "user_send_text",
            "message": {"text": "hello"},  # no sender
        }
        inbound = await ch.receive(payload)
        assert inbound is None

    @pytest.mark.asyncio
    async def test_deliver_calls_api(self):
        ch = ZaloOAChannel(bot_token="access-token-123", agent_id="agent-1")
        outbound = OutboundMessage(
            session_id="s1",
            text="Hello from CaberOS!",
            chat_id="user-zalo-id",
        )
        mock_response = {"error": 0, "message": "Success", "data": {"message_id": "zalo-msg-1"}}
        with patch.object(ch, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await ch.deliver(outbound)
        assert result["success"] is True
        assert result["message_id"] == "zalo-msg-1"

    @pytest.mark.asyncio
    async def test_deliver_api_error(self):
        ch = ZaloOAChannel(bot_token="access-token-123", agent_id="agent-1")
        outbound = OutboundMessage(
            session_id="s1",
            text="Hello",
            chat_id="user-zalo-id",
        )
        mock_response = {"error": -201, "message": "Invalid access token"}
        with patch.object(ch, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await ch.deliver(outbound)
        assert result["success"] is False
        assert "Invalid access token" in result["error"]

    @pytest.mark.asyncio
    async def test_deliver_splits_long_message(self):
        ch = ZaloOAChannel(bot_token="access-token-123", agent_id="agent-1")
        ch.constraints = OutputConstraints(max_length=100, supported_formatting=["plain"])
        long_text = "a" * 250
        outbound = OutboundMessage(
            session_id="s1",
            text=long_text,
            chat_id="user-zalo-id",
        )
        call_count = 0

        async def mock_call_api(msg_type, body):
            nonlocal call_count
            call_count += 1
            return {"error": 0, "data": {"message_id": f"msg-{call_count}"}}

        with patch.object(ch, "_call_api", new_callable=AsyncMock, side_effect=mock_call_api):
            result = await ch.deliver(outbound)
        assert result["success"] is True
        assert call_count >= 3

    def test_format_text_strips_markdown(self):
        ch = ZaloOAChannel(bot_token="test", agent_id="a1")
        result = ch.format_text("**bold** and `code`")
        assert "**" not in result
        assert "`" not in result
        assert "bold" in result
        assert "code" in result

    def test_webhook_signature_verification(self):
        import hashlib
        import hmac as hmac_mod

        ch = ZaloOAChannel(bot_token="token", agent_id="a1", webhook_secret="my-secret")
        body = b'{"event_name":"user_send_text"}'
        signature = hmac_mod.new(b"my-secret", body, hashlib.sha256).hexdigest()
        assert ch.verify_webhook_signature(body, signature) is True
        assert ch.verify_webhook_signature(body, "wrong-signature") is False

    def test_webhook_signature_no_secret_skips(self):
        ch = ZaloOAChannel(bot_token="token", agent_id="a1", webhook_secret="")
        # No secret configured — should skip verification (return True)
        assert ch.verify_webhook_signature(b"body", "any-signature") is True


# --- Zalo Bot channel ---

class TestZaloBotChannel:
    @pytest.mark.asyncio
    async def test_receive_text_message(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        payload = {
            "event_name": "message.text.received",
            "message": {
                "date": 1775362520302,
                "chat": {"chat_type": "PRIVATE", "id": "chat-abc-123"},
                "message_id": "msg-abc-456",
                "from": {"id": "user-1", "is_bot": False, "display_name": "Nguyen Van A"},
                "text": "Xin chao bot!",
            },
        }
        inbound = await ch.receive(payload)
        assert inbound is not None
        assert inbound.channel == "zalo_bot"
        assert inbound.bot_id == "agent-1"
        assert inbound.external_user_id == "chat-abc-123"
        assert inbound.text == "Xin chao bot!"
        assert inbound.message_id == "msg-abc-456"

    @pytest.mark.asyncio
    async def test_receive_ignores_non_text_events(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        # image event
        inbound = await ch.receive({"event_name": "message.image.received", "message": {}})
        assert inbound is None
        # sticker event
        inbound = await ch.receive({"event_name": "message.sticker.received", "message": {}})
        assert inbound is None

    @pytest.mark.asyncio
    async def test_receive_ignores_bot_messages(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        payload = {
            "event_name": "message.text.received",
            "message": {
                "chat": {"id": "chat-1"},
                "message_id": "msg-1",
                "from": {"id": "bot-1", "is_bot": True, "display_name": "MyBot"},
                "text": "Bot reply",
            },
        }
        inbound = await ch.receive(payload)
        assert inbound is None

    @pytest.mark.asyncio
    async def test_receive_no_chat_id_returns_none(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        payload = {
            "event_name": "message.text.received",
            "message": {
                "chat": {},
                "message_id": "msg-1",
                "from": {"id": "user-1", "is_bot": False},
                "text": "hello",
            },
        }
        inbound = await ch.receive(payload)
        assert inbound is None

    @pytest.mark.asyncio
    async def test_deliver_calls_api(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        outbound = OutboundMessage(
            session_id="s1",
            text="Hello from CaberOS!",
            chat_id="chat-abc-123",
        )
        mock_response = {"message_id": "zalo-bot-msg-1", "date": 1775362520302}
        with patch.object(ch, "_call_api", new_callable=AsyncMock, return_value=mock_response):
            result = await ch.deliver(outbound)
        assert result["success"] is True
        assert result["message_id"] == "zalo-bot-msg-1"

    @pytest.mark.asyncio
    async def test_deliver_splits_long_message(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        long_text = "a" * 3000  # Exceeds 2000 limit
        outbound = OutboundMessage(
            session_id="s1",
            text=long_text,
            chat_id="chat-abc-123",
        )
        call_count = 0

        async def mock_call_api(method, body):
            nonlocal call_count
            call_count += 1
            return {"message_id": f"msg-{call_count}"}

        with patch.object(ch, "_call_api", new_callable=AsyncMock, side_effect=mock_call_api):
            result = await ch.deliver(outbound)
        assert result["success"] is True
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_deliver_api_error(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        outbound = OutboundMessage(
            session_id="s1",
            text="Hello",
            chat_id="chat-abc-123",
        )
        with patch.object(ch, "_call_api", new_callable=AsyncMock, side_effect=Exception("401 Unauthorized")):
            result = await ch.deliver(outbound)
        assert result["success"] is False
        assert "401" in result["error"]

    @pytest.mark.asyncio
    async def test_send_typing(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        with patch.object(ch, "_call_api", new_callable=AsyncMock, return_value={}) as mock_api:
            await ch.send_typing("chat-123")
            mock_api.assert_called_once_with("sendChatAction", {
                "chat_id": "chat-123",
                "action": "typing",
            })

    @pytest.mark.asyncio
    async def test_send_typing_silent_failure(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        with patch.object(ch, "_call_api", new_callable=AsyncMock, side_effect=Exception("network error")):
            # Should not raise — typing is best-effort
            await ch.send_typing("chat-123")

    @pytest.mark.asyncio
    async def test_start_polling_deletes_webhook(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        with patch.object(ch, "_call_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {}
            await ch.start_polling()
            # First call should be deleteWebhook
            first_call = mock_api.call_args_list[0]
            assert "deleteWebhook" in str(first_call)
            await ch.stop_polling()

    @pytest.mark.asyncio
    async def test_poll_loop_processes_updates(self):
        ch = ZaloBotChannel(bot_token="bot_id:secret_key", agent_id="agent-1")
        ch._last_update_id = 0

        call_count = 0

        async def mock_call_api(method, body=None):
            nonlocal call_count
            call_count += 1
            if method == "deleteWebhook":
                return {}
            if method == "getUpdates":
                if call_count == 1:
                    return [
                        {
                            "update_id": 50,
                            "event_name": "message.text.received",
                            "message": {
                                "chat": {"id": "chat-1", "chat_type": "PRIVATE"},
                                "message_id": "msg-1",
                                "from": {"id": "user-1", "is_bot": False},
                                "text": "hello",
                                "date": 1775362520302,
                            },
                        }
                    ]
                await asyncio.sleep(10)
                return []
            return {}

        with patch.object(ch, "_call_api", new_callable=AsyncMock, side_effect=mock_call_api):
            with patch.object(ch, "_process_update", new_callable=AsyncMock) as mock_process:
                task = asyncio.create_task(ch._poll_loop())
                await asyncio.sleep(0.3)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                assert mock_process.call_count >= 1
                assert ch._last_update_id == 50

    def test_webhook_secret_derived_from_token(self):
        import hashlib

        token = "bot_id:secret_key"
        ch = ZaloBotChannel(bot_token=token, agent_id="a1")
        expected = hashlib.sha256(token.encode()).hexdigest()[:32]
        assert ch.webhook_secret == expected

    def test_webhook_secret_custom(self):
        ch = ZaloBotChannel(bot_token="token", agent_id="a1", webhook_secret="custom-secret")
        assert ch.webhook_secret == "custom-secret"

    def test_verify_webhook_secret(self):
        import hashlib

        token = "bot_id:secret_key"
        ch = ZaloBotChannel(bot_token=token, agent_id="a1")
        expected_secret = hashlib.sha256(token.encode()).hexdigest()[:32]
        assert ch.verify_webhook_secret(expected_secret) is True
        assert ch.verify_webhook_secret("wrong-secret") is False
        assert ch.verify_webhook_secret(None) is False

    def test_max_length_2000(self):
        ch = ZaloBotChannel(bot_token="test", agent_id="a1")
        assert ch.constraints.max_length == 2000

    def test_supports_typing_indicator(self):
        ch = ZaloBotChannel(bot_token="test", agent_id="a1")
        assert ch.constraints.supports_typing_indicator is True

    def test_format_text_passes_markdown(self):
        ch = ZaloBotChannel(bot_token="test", agent_id="a1")
        assert ch.format_text("**bold** text") == "**bold** text"
