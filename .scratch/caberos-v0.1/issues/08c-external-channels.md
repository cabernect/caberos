# 08c — External messaging channels

**What to build:** Connect CaberOS to external messaging platforms (Telegram, Discord, Zalo, WhatsApp, Slack) for inbound messages and outbound replies. Each platform is a `Channel` implementation that parses webhooks into `InboundMessage` and delivers replies via the platform's API. The pipeline (plan 07) is channel-agnostic — no changes needed to the core orchestration.

**Blocked by:** 08a — MCP client infrastructure (shares the encrypted credential store). 02 — Dashboard chat (the Channel base abstraction already exists from plan 08).

**Status:** ready-for-agent

**Spec references:** D20 (Channel port, proven by two implementations), D19 (execution pipeline — step 12 deliver), D33 (API is client-agnostic)

## Architecture

```
Telegram webhook → POST /api/channels/telegram/webhook
  → TelegramChannel.receive(raw_payload) → InboundMessage(channel="telegram", ...)
  → pipeline.handle_inbound(message)
  → agent runs (reason, mediate, iterate — same pipeline as dashboard)
  → final answer text
  → TelegramChannel.deliver(OutboundMessage)
  → HTTP POST to Telegram Bot API: sendMessage({chat_id, text})
  → Reply appears in Telegram
```

The dashboard chat channel is implementation #1 (already built). Each external platform is implementation #2, #3, etc. The pipeline doesn't know or care which channel triggered the run.

## Key differences from dashboard chat

| | Dashboard chat | External channels |
|---|---|---|
| **Inbound** | HTTP POST from browser | Webhook from platform |
| **Deliver** | SSE event (push to open connection) | HTTP POST to platform API |
| **Streaming** | Yes (token-by-token SSE) | No (platforms are request-response) |
| **Typing indicator** | SSE `typing` event | Platform-specific API call (e.g. Telegram `sendChatAction`) |
| **Formatting** | Full markdown | Platform-specific (Telegram: MarkdownV2, Discord: markdown, Zalo: plain) |

## Tasks

### 1. Channel base abstraction (already exists — verify and extend)

`backend/src/agentos/channels/base.py`:
- `Channel` ABC with `receive()`, `deliver()`, `output_constraints`
- `InboundMessage` — already defined in pipeline.py
- Add `OutboundMessage` model: `{session_id, text, chat_id, reply_to_message_id}`
- Add `ChannelConfig` model: `{platform, bot_token (encrypted), agent_id, webhook_secret, enabled}`

### 2. Telegram channel (first implementation)

`backend/src/agentos/channels/telegram.py`:
- **`receive(raw_payload)`** — parse Telegram webhook payload:
  - `message.chat.id` → `external_user_id` (chat ID)
  - `message.from.id` → user's Telegram ID
  - `message.from.first_name` → `external_user_name`
  - `message.text` → `text`
  - `message.message_id` → `message_id` (for dedup)
  - `message.date` → `timestamp`
  - Returns `InboundMessage(channel="telegram", bot_id=agent_id, ...)`
- **`deliver(outbound)`** — send reply via Telegram Bot API:
  - `POST https://api.telegram.org/bot{TOKEN}/sendMessage`
  - Body: `{chat_id, text, parse_mode: "MarkdownV2", reply_to_message_id}`
  - Handle message length limit (4096 chars) — split if needed
- **`send_typing(chat_id)`** — `POST .../sendChatAction` with `action: "typing"`
- **Output constraints:** max_length=4096, supported_formatting=["markdown"], supports_typing_indicator=true

### 3. Discord channel (second implementation)

`backend/src/agentos/channels/discord.py`:
- **Inbound:** Discord bot gateway (WebSocket) or webhook
  - `channel_id` → `external_user_id`
  - `author.username` → `external_user_name`
  - `content` → `text`
  - `id` → `message_id`
- **Deliver:** `POST https://discord.com/api/v10/channels/{channel_id}/messages`
  - Body: `{content: text}` (2000 char limit — split if needed)
- **Output constraints:** max_length=2000, supported_formatting=["markdown"], supports_typing_indicator=false

### 4. Zalo channel (third implementation)

`backend/src/agentos/channels/zalo.py`:
- **Inbound:** Zalo OA webhook → `POST /api/channels/zalo/webhook`
  - Parse Zalo event format (sender_id, message, event_name)
  - `sender_id` → `external_user_id`
  - `display_name` → `external_user_name`
  - `message.text` → `text`
- **Deliver:** Zalo OA API — send message to user
  - `POST https://openapi.zalo.me/v3.0/oa/message`
  - Headers: `{access_token, ...}`
  - Body: `{recipient: {user_id}, message: {text}}`
- **Output constraints:** max_length=None (varies), supported_formatting=["plain"], supports_typing_indicator=false

### 5. Channel registry and webhook routes

`backend/src/agentos/channels/registry.py`:
- Process-global registry of active channel instances: `{(platform, agent_id): Channel}`
- `register_channel(config)` — instantiate and register a channel from DB config
- `get_channel(platform, agent_id)` — lookup for delivery

`backend/src/agentos/api/channels.py`:
- `POST /api/channels/telegram/webhook` — Telegram webhook receiver
- `POST /api/channels/discord/webhook` — Discord webhook receiver
- `POST /api/channels/zalo/webhook` — Zalo webhook receiver
- `GET /api/channels` — list configured channels (platform, agent, enabled, webhook URL)
- `POST /api/channels` — add a channel config (platform, bot_token, agent_id)
- `DELETE /api/channels/{id}` — remove a channel config
- `POST /api/channels/{id}/test` — send a test message to verify the connection

### 6. DB model for channel configs

`backend/src/agentos/models/channel_config.py`:
- `ChannelConfig` table: `id, platform, agent_id, bot_token (encrypted), webhook_secret, enabled, created_at, updated_at`
- Unique constraint on `(platform, agent_id)` — one bot per agent per platform

### 7. Pipeline integration — deliver step

The pipeline's step 12 (deliver) currently uses `event_emitter` for SSE. For external channels:
- If `message.channel == "dashboard_chat"` → SSE event emitter (current behavior)
- If `message.channel == "telegram"` → `TelegramChannel.deliver(outbound)`
- If `message.channel == "discord"` → `DiscordChannel.deliver(outbound)`
- The pipeline looks up the channel from the registry by `(message.channel, message.bot_id)`

No streaming for external channels — the `event_emitter` is a no-op for `token`/`thinking`/`tool_call` events. Only the final answer is delivered via `channel.deliver()`.

Typing indicator: for platforms that support it, send a typing action when the run starts (step 7-8).

### 8. Frontend — Channels page

`frontend/src/pages/Channels.tsx`:
- List configured channels: platform icon, agent name, status (connected/disconnected), webhook URL
- Add channel form:
  - Platform dropdown (Telegram, Discord, Zalo, WhatsApp, Slack)
  - Agent selection (which agent handles this channel)
  - Bot token input (encrypted on save)
  - Webhook URL displayed after creation (operator copies to platform config)
- Per-channel: test button (sends a test message), remove button
- Webhook URL format: `https://your-domain/api/channels/{platform}/webhook`

### 9. Frontend — route + sidebar nav

- Route: `/channels` → `Channels` page
- Sidebar: "Channels" entry under "Capabilities" section (already exists in sidebar, just needs the route)

### 10. Lifespan integration

- On startup: load all enabled `ChannelConfig` rows, register channel instances
- On shutdown: gracefully disconnect (close WebSocket for Discord, no-op for webhook-based)

## Files to create

- `backend/src/agentos/channels/__init__.py`
- `backend/src/agentos/channels/base.py` (extend existing)
- `backend/src/agentos/channels/telegram.py`
- `backend/src/agentos/channels/discord.py`
- `backend/src/agentos/channels/zalo.py`
- `backend/src/agentos/channels/registry.py`
- `backend/src/agentos/models/channel_config.py`
- `backend/src/agentos/api/channels.py`
- `frontend/src/pages/Channels.tsx`
- `backend/tests/test_channels_external.py`

## Verification

- **Telegram:** Configure bot token → send message to bot on Telegram → agent replies in Telegram
- **Discord:** Configure bot token → mention bot in Discord channel → agent replies in Discord
- **Zalo:** Configure OA token → send message to Zalo OA → agent replies in Zalo
- **Dedup:** Telegram sends the same update twice (retry) → second is dropped
- **Per-Contact lock:** Two messages from same Telegram chat → second queues behind first
- **Long messages:** Agent reply > 4096 chars (Telegram) → split into multiple messages
- **No streaming:** External channels do not emit token/thinking events — only final answer delivered
- **Typing indicator:** Telegram shows "typing..." while agent is running
- **Webhook URL:** After adding a channel, the webhook URL is shown for the operator to configure on the platform
- **`uv run pytest tests/test_channels_external.py` passes** (mock webhook payloads, mock platform API responses)

## Notes

- WhatsApp Business API and Slack Event API follow the same pattern — add them after the first three are proven
- Slack is special: it has both inbound (Event API) and outbound (MCP Slack server). The operator connects Slack once and gets both directions
- For local development without a public URL: use `ngrok` or `cloudflared tunnel` to expose the webhook endpoint
- Bot tokens are stored encrypted (Fernet, same secret store as provider keys and MCP credentials)
