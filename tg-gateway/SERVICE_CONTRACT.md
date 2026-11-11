# Service Contract — Messaging Gateway

Version: 2.5
Base URL:
- Internal (backend -> gateway): `http://tg-gateway:8080`
- Public (Telegram -> gateway webhook only): `https://<TG_GATEWAY_PUBLIC_HOST>`

This gateway is a **platform adapter**. The backend sends and receives platform-neutral messages; the
gateway translates them to/from the target platform (Telegram, Slack, etc.). Switching platforms
requires deploying a different gateway — no backend changes.

---

## Authentication and Network Model

No token authentication between backend and gateway.

Access is split by path and network:
- `POST /v1/messaging/send` and webhook management endpoints are **internal-only** (Docker network).
- `POST /v1/messaging/webhook/{bot_token}` is exposed externally via Traefik on a dedicated host/path
  so Telegram can deliver updates.

The backend callback endpoint (`/api/messaging-gateway/webhook/`) remains internal-only and is not
exposed via Traefik.

---

## Endpoints

### POST /v1/messaging/send

Send, edit, or delete a message on any platform.

**Request body:**

```json
{
  "action":       "send_interactive",
  "bot_token":    "110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
  "tenant_id":    "lemonfit",
  "recipient_id": "123456789",
  "text":         "<b>New request #42</b>\nAmount: 1 000 000 UZS",
  "format":       "html",
  "message_id":   null,
  "buttons": [
    [
      { "label": "✅ Approve", "value": "v2_42:a" },
      { "label": "❌ Reject",  "value": "v2_42:r" }
    ]
  ],
  "request_id":  42,
  "approval_id": 17
}
```

**Fields:**

| Field          | Type            | Required | Description |
|----------------|-----------------|----------|-------------|
| `action`       | string (enum)   | yes      | See action table below |
| `bot_token`    | string          | yes      | Platform credential (Telegram bot token, Slack bot token, etc.) |
| `tenant_id`    | string          | no       | Echoed in response and logs |
| `recipient_id` | string          | yes      | Platform-agnostic channel/chat/user identifier |
| `text`         | string          | no | Message body (`null/empty` is passed through to platform API) |
| `format`       | `html` / `markdown` / `plain` | no | Default: `html` |
| `message_id`   | integer         | yes (edit/delete) | ID of the message to edit or delete |
| `reply_to_message_id` | integer  | no       | Send actions only: send as a reply to this message (`reply_parameters`, `allow_sending_without_reply: true`) |
| `buttons`      | array of rows   | no       | `[[{label, value}, ...], ...]` |
| `request_id`   | integer         | no       | Passed through; echoed in logs |
| `approval_id`  | string/integer  | no       | Passed through; echoed in logs |

**Actions:**

| Action             | Telegram method    | Notes |
|--------------------|--------------------|-------|
| `send`             | `sendMessage`      | Plain send |
| `send_interactive` | `sendMessage`      | If `buttons` present, sent as inline keyboard |
| `edit`             | `editMessageText`  | If `buttons` present, they are updated |
| `edit_interactive` | `editMessageText`  | Same behavior as `edit`, semantic alias |
| `delete`           | `deleteMessage`    | Deletes message by id |
| `typing`           | `sendChatAction`   | Shows "typing" in the chat; response `message_id` is `null` |

For `edit`/`edit_interactive`, passing `buttons: []` clears buttons.

**Success response (200):**

```json
{
  "ok":                true,
  "tenant":            "lemonfit",
  "recipient_id":      "123456789",
  "message_id":        7712,
  "telegram_response": { ... }
}
```

**Error responses:**

| Code | Cause |
|------|-------|
| 400  | Missing `message_id` for edit/delete |
| 422  | Unknown `action` or invalid field types |
| 502  | Telegram API error or network failure after 1 retry |

**Edge case:** Telegram returns 400 "message is not modified" on edits with identical content. The
gateway treats this as success (200) and returns the original `message_id`.

---

### POST /v1/messaging/webhook/{bot_token}

Receive platform events (Telegram updates). The gateway filters for:
0. **owner delete** (`-` reply from an owner to a message of this bot) → handled in the gateway,
   nothing is forwarded (see "Filter 0 — owner delete" below)
1. **interactive events** (button clicks) → `event=interaction`
2. **known slash commands** (`/bank_ostatki`, `/cash_ostatki`, `/card_ostatki`) → `event=command`

3. **messages addressed to the bot** → `event=message` (private chats: every non-command text/caption
   message; groups/supergroups: only @mentions of the bot and replies to any message)

Other non-interactive events (unaddressed group chatter, etc.) are acknowledged with `{"ok": true}`
and not forwarded as business events (they may still be discovery-logged / event-logged).

**Telegram registers this URL as the bot webhook.** The `{bot_token}` in the path is used to
identify which bot received the event. The **secret** part of the token is never logged or
forwarded. For commands, only the numeric **bot id** (token prefix before `:`) is sent as
`bot_id` so the backend can resolve the tenant.

**Cooldown:** Rapid duplicate button clicks from the same `(recipient_id, value)` pair within
`CALLBACK_COOLDOWN_SECS` (default 10 s) are silently dropped. The gateway returns 200 to Telegram
immediately regardless.

**Forwarded payload — interaction (gateway → backend):**

```json
{
  "event":        "interaction",
  "payload":      "v2_42:a",
  "user_id":      "789012345",
  "recipient_id": "123456789",
  "message_id":   7712,
  "platform":     "telegram"
}
```

**Forwarded payload — command (gateway → backend):**

```json
{
  "event":        "command",
  "payload":      "bank_ostatki",
  "user_id":      "789012345",
  "recipient_id": "123456789",
  "message_id":   7712,
  "platform":     "telegram",
  "bot_id":       "110201543"
}
```

| Field          | Type    | Description |
|----------------|---------|-------------|
| `event`        | string  | `"interaction"` for button clicks, `"command"` for known slash commands |
| `payload`      | string  | Button value, or command name without leading `/` |
| `user_id`      | string  | Platform user ID of the person who clicked / sent the command |
| `recipient_id` | string  | Channel/chat the message was in |
| `message_id`   | integer | ID of the message containing the button / command |
| `platform`     | string  | `"telegram"`, `"slack"`, etc. — for logging only; business logic must not branch on this |
| `bot_id`       | string  | (commands only) Numeric Telegram bot id — **not** the bot secret |

**Forwarded payload — message (gateway → backend):**

```json
{
  "event": "message", "payload": "<text or caption>", "user_id": "<from.id>",
  "recipient_id": "<chat.id>", "message_id": 123, "platform": "telegram",
  "bot_id": "110201543", "chat_type": "private|group|supergroup",
  "sender_name": "<first last>", "mentions_bot": true,
  "reply_to_message_id": 120, "reply_to_text": "...", "reply_to_from_id": "<id or ''>",
  "reply_to_is_bot": true
}
```

`reply_to_*` are `null` / `""` / `false` when the message is not a reply. `reply_to_is_bot` is `true` only when the replied-to message was sent by this bot itself (`reply_to_message.from.id == bot_id`); a reply to another bot gives `false`. `mentions_bot` is true for an
`@bot_username` mention (case-insensitive) or a `text_mention` of the bot user; in private chats it is
informational. Commands (starting with `/`) never produce `event=message`.

**Filter 0 — owner delete.** Checked first for non-callback updates, before discovery logging,
command handling and any forward. It fires only when all of these hold:
- the update has `message` (not `edited_message`, `channel_post`, `callback_query`, etc.);
- `message.text.strip() == "-"` (so `" - "` also matches; captions and other texts do not);
- `str(message.from.id)` is listed in `OWNER_TELEGRAM_IDS`;
- `message.reply_to_message.from.id` equals this bot's id (token prefix before `:`);
- `OWNER_TELEGRAM_IDS` is non-empty (empty or unset → the feature is off, behaviour unchanged).

Works in private chats and groups/supergroups. Actions, best effort:
1. `deleteMessage(chat_id, reply_to_message.message_id)` — the bot's message;
2. `deleteMessage(chat_id, message_id)` — the owner's `-`; attempted even if step 1 failed.

In groups deleting the owner's `-` needs the bot to be an admin with "delete messages"; Telegram also
refuses to delete messages older than 48 h. Failures (`ok=false` or a network error) are logged with
the Telegram `description` / exception type only (never the token) and do not change the response.

Nothing is sent to the backend or the event log. Exactly one `gateway_logs` row is written:
`direction="in"`, `action="owner_delete"`, `recipient_id=<chat.id>`, `message_id=<bot message id>`,
`ok=<bot message deleted>`, `error_text=<description on failure>`; `payload` holds only ids and
result flags (`chat_id`, `chat_type`, `actor_user_id` — the owner's Telegram user id, `bot_message_id`,
`minus_message_id`, `bot_message_deleted`, `minus_message_deleted`, `minus_message_error`) — no message texts. This is an exception from
filter 3: an owner's `-` reply to the bot is **not** forwarded as `event=message`. A `-` from anyone
else, or a `-` not replying to this bot, goes through filters 1–3 as before.

Response to Telegram: `{"ok": true}`.

The backend is not told about owner deletes, so its `TelegramMessageHistory` still shows such a message
as live. A later `delete` / `edit` of it through `/v1/messaging/send` fails with the Telegram description
(e.g. `message to delete not found`) and HTTP 502; the backend command `delete_telegram_messages` reports
it as a gateway error.

**Privacy:** group/supergroup messages that are not forwarded are dropped without their text: it is not
written to logs, `db.log_event` payload, or the event log.

**Backend webhook URL:** configured via `BACKEND_WEBHOOK_URL` env var.
No auth header is sent — network isolation is the only access control.

**Response to Telegram:** always `{"ok": true}` (Telegram requires a 200 within 10 s).

---

### POST /v1/messaging/webhook/set

Create/update Telegram webhook for a bot.

**Request body:**
```json
{
  "bot_token": "123:abc",
  "webhook_url": "https://tg-gateway.example.com/v1/messaging/webhook/123:abc"
}
```

- `webhook_url` is optional.
- If omitted, gateway builds URL as:
  `PUBLIC_WEBHOOK_BASE_URL + "/v1/messaging/webhook/{bot_token}"`.

**Response (200 on success, 502 on Telegram failure):**
```json
{
  "ok": true,
  "webhook_url": "https://tg-gateway.example.com/v1/messaging/webhook/123:abc",
  "telegram_status": 200,
  "telegram": { "ok": true, "result": true }
}
```

---

### POST /v1/messaging/description/set

Set the bot's profile texts (Telegram `setMyDescription` + `setMyShortDescription`).

**Request body:**
```json
{
  "bot_token": "123:abc",
  "description": "up to 512 chars",
  "short_description": "up to 120 chars"
}
```

**Response (200 only if both Telegram calls succeed, otherwise 502):**
```json
{
  "ok": true,
  "telegram_status": 200,
  "telegram": { "ok": true, "result": true },
  "short_telegram_status": 200,
  "short_telegram": { "ok": true, "result": true }
}
```

The gateway logs only text lengths, never the texts or the full token.

---

### POST /v1/messaging/menu-button/set

Set the default menu button for all private chats (Telegram `setChatMenuButton`, no `chat_id`).

**Request body:**
```json
{
  "bot_token": "123:abc",
  "text": "Портал",
  "url": "https://tenant.example.com/app/tg/"
}
```

- `text`: 1..64 chars. `url`: `https://` only (422 otherwise).
- Sent to Telegram as `{"menu_button": {"type": "web_app", "text": ..., "web_app": {"url": ...}}}`.

**Response (200 on success, 502 on Telegram failure):**
```json
{ "ok": true, "telegram_status": 200, "telegram": { "ok": true, "result": true } }
```

---

### GET /v1/messaging/webhook/info/{bot_token}

Read Telegram webhook status for a bot.

**Response:**
```json
{
  "ok": true,
  "connected": true,
  "url": "https://tg-gateway.example.com/v1/messaging/webhook/123:abc",
  "pending_update_count": 0,
  "last_error_date": null,
  "last_error_message": null,
  "telegram_status": 200,
  "telegram": { "...": "..." }
}
```

---

### POST /v1/messaging/webhook/delete

Delete Telegram webhook for a bot.

**Request body:**
```json
{
  "bot_token": "123:abc",
  "drop_pending_updates": true
}
```

**Response (200 on success, 502 on Telegram failure):**
```json
{
  "ok": true,
  "telegram_status": 200,
  "telegram": { "ok": true, "result": true }
}
```

---

### GET /health

Liveness check.

**Response (200):**
```json
{ "ok": true, "db": true }
```

`db` is `false` if `DATABASE_URL` is unset or the pool is down. The gateway remains functional
without a database (all DB ops are no-ops).

---

## Logging

Every send/edit/delete call and every inbound callback is written to the `gateway_logs` table when
`DATABASE_URL` is set:

| Column       | Notes |
|--------------|-------|
| `direction`  | `"out"` (to platform) or `"in"` (from platform) |
| `endpoint`   | Request path |
| `action`     | Action name |
| `tenant_id`  | From request payload |
| `recipient_id` | Chat/channel identifier |
| `message_id` | Platform message ID |
| `ok`         | Whether the operation succeeded |
| `status_code`| HTTP status returned or received |
| `error_text` | On failure |
| `payload`    | Full request payload (bot_token excluded) |
| `tg_response`| Raw platform API response |

---

## Environment Variables

| Variable               | Required | Default | Description |
|------------------------|----------|---------|-------------|
| `BACKEND_WEBHOOK_URL`  | yes      | —       | Where to forward interaction callbacks (internal URL) |
| `PUBLIC_WEBHOOK_BASE_URL` | no    | —       | Public base URL used by `/v1/messaging/webhook/set` when `webhook_url` is omitted |
| `DATABASE_URL`         | no       | —       | PostgreSQL DSN; omit to disable logging |
| `CALLBACK_COOLDOWN_SECS` | no     | `10`    | Dedup window for identical button clicks |
| `OWNER_TELEGRAM_IDS`   | no       | empty   | Comma-separated Telegram user ids allowed to delete bot messages by replying `-` (spaces ignored); empty → owner delete off. In compose: `TG_GATEWAY_OWNER_TELEGRAM_IDS` |

`BACKEND_TOKEN` and `N8N_INTEGRATION_TOKEN` are **removed** — network isolation replaces them.
Bot tokens are passed per-request in the `bot_token` field, not as env vars.

---

## Button Value Format (Approval Callbacks)

The backend currently uses a compact format to stay within Telegram's 64-byte callback_data limit:

```
v2_{approval_id}:{decision_code}

Examples:
  v2_2267:a   →  approval 2267, approved
  v2_2267:r   →  approval 2267, rejected
```

This format is owned by the backend — the gateway forwards it as an opaque string. Any new
interactive flows should follow the same `v2_{entity_id}:{code}` convention.
