# Service Contract — Messaging Gateway

Version: 2.0 (platform-neutral redesign)
Base URL: `http://tg-gateway:8080` (internal Docker network only)

This gateway is a **platform adapter**. The backend sends and receives platform-neutral messages; the
gateway translates them to/from the target platform (Telegram, Slack, etc.). Switching platforms
requires deploying a different gateway — no backend changes.

---

## Authentication

None. The gateway is only reachable from the `gateway` Docker network. Backend and gateway must both
be on that network; the endpoint is not exposed through Traefik.

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
| `text`         | string          | yes (send/edit) | Message body |
| `format`       | `html` / `markdown` / `plain` | no | Default: `html` |
| `message_id`   | integer         | yes (edit/delete) | ID of the message to edit or delete |
| `buttons`      | array of rows   | no       | `[[{label, value}, ...], ...]` — empty array removes buttons on edit |
| `request_id`   | integer         | no       | Passed through; echoed in logs |
| `approval_id`  | string/integer  | no       | Passed through; echoed in logs |

**Actions:**

| Action           | Telegram method      | buttons required |
|------------------|----------------------|------------------|
| `send`           | `sendMessage`        | no               |
| `send_interactive` | `sendMessage`      | yes              |
| `edit`           | `editMessageText`    | no               |
| `edit_interactive` | `editMessageText`  | yes              |
| `delete`         | `deleteMessage`      | no               |

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

Receive platform events (Telegram updates). The gateway filters for interactive events
(button clicks), applies cooldown deduplication, and forwards a platform-neutral callback to the
backend.

**Telegram registers this URL as the bot webhook.** The `{bot_token}` in the path is used to
identify which bot received the event; it is never logged or forwarded.

**Non-interactive events** (plain messages, etc.) are acknowledged with `{"ok": true}` and not
forwarded.

**Cooldown:** Rapid duplicate button clicks from the same `(recipient_id, value)` pair within
`CALLBACK_COOLDOWN_SECS` (default 10 s) are silently dropped. The gateway returns 200 to Telegram
immediately regardless.

**Forwarded payload (gateway → backend):**

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

| Field          | Type    | Description |
|----------------|---------|-------------|
| `event`        | string  | Always `"interaction"` for button clicks |
| `payload`      | string  | The value attached to the button that was clicked |
| `user_id`      | string  | Platform user ID of the person who clicked |
| `recipient_id` | string  | Channel/chat the message was in |
| `message_id`   | integer | ID of the message containing the button |
| `platform`     | string  | `"telegram"`, `"slack"`, etc. — for logging only; business logic must not branch on this |

**Backend webhook URL:** configured via `BACKEND_WEBHOOK_URL` env var.
No auth header is sent — network isolation is the only access control.

**Response to Telegram:** always `{"ok": true}` (Telegram requires a 200 within 10 s).

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
| `DATABASE_URL`         | no       | —       | PostgreSQL DSN; omit to disable logging |
| `CALLBACK_COOLDOWN_SECS` | no     | `10`    | Dedup window for identical button clicks |

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
