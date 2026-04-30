# Developer Notes: TG Gateway Refactoring

Changes span two services: `tg-gateway` (this repo) and `backend_v2`.
Tasks are ordered by dependency — do them top to bottom.

---

## Task 1 & 2 — Replace Token Auth with Docker Network Isolation

**Why:** The `X-N8N-Integration-Token` header is a shared secret that has to be stored and rotated. It
is also coupled to n8n, which is being replaced. Network isolation is cheaper and stronger: if only the
gateway container can reach the backend webhook port, no token is needed.

### docker-compose.yml (kolberg root)

Add a new internal network and wire both services into it.

```yaml
# Add to the `networks:` section at the bottom
networks:
  traefik-public:
  backend:
  chromium:
  gateway:          # NEW — internal only, no internet exposure
    internal: true

# Add new tg-gateway service
  tg-gateway:
    build: ./tg-gateway
    container_name: tg_gateway
    restart: always
    environment:
      DATABASE_URL: postgresql://...   # can share backend db or have its own
      BACKEND_WEBHOOK_URL: http://django_v2:8001/api/messaging-gateway/webhook/
      # No BACKEND_TOKEN needed — network isolation replaces it
      CALLBACK_COOLDOWN_SECS: 10
    networks:
      - traefik-public   # must be reachable by Telegram (inbound webhooks)
      - gateway          # must reach backend_v2

# In backend_v2 service, add the gateway network
  backend_v2:
    networks:
      - traefik-public
      - backend
      - gateway          # NEW — allow tg-gateway to reach it directly
```

The webhook endpoint on the backend (`/api/messaging-gateway/webhook/`) must NOT be routed through
Traefik anymore — it should only be reachable via the `gateway` Docker network on port 8001 directly.
Remove or do not add a Traefik rule for that path.

### Gateway — main.py

Remove the `Authorization` / token header from the callback forward call. The `BACKEND_TOKEN` env var
and the `X-N8N-Integration-Token` header can be deleted entirely.

```python
# Before:
resp = await client.post(BACKEND_URL, json=forward, headers={"X-N8N-Integration-Token": BACKEND_TOKEN})

# After (no auth header, network isolation is enough):
resp = await client.post(BACKEND_URL, json=forward)
```

### Backend — telegram_approvals/views.py

Remove `_check_token()` and the `X-N8N-Integration-Token` validation entirely. The endpoint is not
reachable from outside the `gateway` Docker network, so no token check is needed.

Remove these env vars from backend settings and docker-compose:
- `N8N_INTEGRATION_TOKEN`
- `N8N_TOKEN`
- `TELEGRAM_APPROVALS_BRIDGE_TOKEN` (and all its tenant-level copies)

---

## Task 3 — Service Contract

See `SERVICE_CONTRACT.md` in this directory. Write it **after** Tasks 4 & 5 are finalised, since the
contract documents the agreed-upon universal API, not the current one.

---

## Tasks 4 & 5 — Platform-Neutral API Contract

**Why:** All user interactions are currently on Telegram, but the gateway is meant to be a swap-in
adapter. If the company later moves to Slack or WhatsApp, the backend should not need any changes —
only a different gateway is deployed. That requires every field in the API to be platform-agnostic.

### Proposed field renames

| Current (backend sends)         | New (universal)         | Reason |
|---------------------------------|-------------------------|--------|
| `message` / `text_message`      | `text`                  | Unified; neither "message" nor Telegram-specific |
| `chat_id` (int)                 | `recipient_id` (str)    | Slack/WhatsApp use string IDs |
| `inline_keyboard`               | `buttons`               | Telegram widget term |
| `parse_mode` = `"HTML"`         | `format` = `"html"`     | Lowercase enum, platform-neutral |
| `action: send_approval_message` | `action: send_interactive` | No platform name in action |
| `action: edit_approval_message` | `action: edit_interactive` | Same |
| `action: send_draft_notification` | `action: send`         | No buttons → plain send |
| `action: send_portal_feedback`  | `action: send`          | Same |

Gateway actions after rename:
```
send             — plain message, no buttons
send_interactive — message with buttons
edit             — edit text only
edit_interactive — edit text + update/remove buttons
delete           — delete message
```

### Callback forward payload (gateway → backend)

Replace the current Telegram-specific structure with a flat platform-neutral event:

```json
// CURRENT (Telegram-specific, breaks with Slack)
{
  "update": {
    "callback_query": {
      "data": "v2_1:a",
      "from": { "id": 789 },
      "message": { "message_id": 456, "chat": { "id": 123456 } }
    }
  }
}

// NEW (platform-neutral)
{
  "event":        "interaction",
  "payload":      "v2_1:a",
  "user_id":      "789",
  "recipient_id": "123456",
  "message_id":   456,
  "platform":     "telegram"
}
```

`platform` lets the backend log or branch if ever needed, but business logic must never depend on it.

### Files to change — Gateway

**models.py:**
- Rename `text_message` → `text`
- Rename `chat_id: int` → `recipient_id: str`
- Rename `inline_keyboard` → `buttons`
- Rename `parse_mode` → `format`, default `"html"`
- Update `SEND_ACTIONS`, `EDIT_ACTIONS` with new action names

**main.py:**
- Update field references after model rename
- Replace the `forward` dict in `telegram_webhook()` with the new flat format
- Map `recipient_id` (str) → Telegram `chat_id` (int) via `int(payload.recipient_id)`

### Files to change — Backend

**telegram_approvals/views.py** (webhook parsing):
```python
# Before — tightly coupled to Telegram structure:
cb       = update.get("callback_query")
cb_data  = cb.get("data", "")
from_id  = cb.get("from", {}).get("id")
chat_id  = cb.get("message", {}).get("chat", {}).get("id")
msg_id   = cb.get("message", {}).get("message_id")

# After — reads flat platform-neutral event:
cb_data    = payload.get("payload", "")
from_id    = payload.get("user_id")
chat_id    = payload.get("recipient_id")
message_id = payload.get("message_id")
# `update` key no longer exists; `TelegramApprovalWebhookSerializer` can be deleted
```

**telegram_approvals/serializers.py:**
Replace with a minimal serializer that validates the flat format:
```python
class MessagingCallbackSerializer(serializers.Serializer):
    event        = serializers.CharField()
    payload      = serializers.CharField()
    user_id      = serializers.CharField()
    recipient_id = serializers.CharField()
    message_id   = serializers.IntegerField(required=False)
    platform     = serializers.CharField(default="telegram")
```

**telegram_approvals/services.py — outbound payloads:**

Every call to `_post_to_bridge()` must be updated. Key changes in each payload-building function:

- `dispatch_pending_approvals()` (line ~773): rename `message` → `text`, `chat_id` → `recipient_id`,
  `inline_keyboard` → `buttons`, action `send_approval_message` → `send_interactive`
- `edit_approval_message()` (line ~813): same renames, action `edit_approval_message` → `edit_interactive`
- `deactivate_approval_message_buttons()` (line ~835): action → `edit_interactive`, buttons → `[]`
- `dispatch_draft_request_notification()` (line ~200): action → `send`, rename fields
- Portal feedback payload in `feedback/views.py` (line ~132): same renames, action → `send`
- Investment approvals in `investments/approval_services.py`: same renames

**tenants/integration_settings.py and requests/integration_settings.py:**
Update default action names:
- `telegram_approvals_send_action` default: `"send_approval_message"` → `"send_interactive"`
- `telegram_approvals_edit_action` default: `"edit_approval_message"` → `"edit_interactive"`
- `telegram_approvals_draft_notification_action` default: `"send_draft_notification"` → `"send"`

**tenants/models.py — TenantIntegrationConfig:**
Rename the bridge URL fields from `telegram_approvals_bridge_dispatch_url` to `messaging_gateway_dispatch_url`
(see Task 6 for the full field rename list).

---

## Task 6 — Rename Module & Consolidate Admin Settings

**Why:** The module is called `telegram_approvals` but it already handles investments, feedback, and
draft notifications. Naming it after a single platform creates confusion when adding Slack or extending
to more flows. The new name should reflect what it does, not which platform it uses.

### New module identity

```python
MODULE_KEY   = "messaging_gateway"
display_name = "Telegram Gateway"      # or "Messaging Gateway"
```

### What stays in `apps/accounts/` (DO NOT move)

These are authentication features — separate install, no gateway dependency:
- `telegram_login_widget.py` + `views_telegram_login_widget.py`
- `telegram_webapp.py` + `views_telegram_webapp.py`
- `telegram_oidc.py` + `views_telegram_oidc.py`
- URL routes: `api/auth/telegram/...`
- Tenant model fields: `telegram_otp_enabled`, `telegram_bot_token_enc`, `telegram_bot_username`

### What moves into `messaging_gateway` module

- All approval message dispatch: requests + investments
- Draft request notifications
- Portal feedback via gateway
- Notes module gateway calls — **verify this exists** in `apps/modules/notes/`; if notes can be sent
  to Telegram, that logic must move here too
- All gateway integration settings (URL, token, action names, message templates)
- New admin settings panel (see below)

### Files to rename / move

```
apps/modules/telegram_approvals/  →  apps/modules/messaging_gateway/
apps/modules/telegram_approvals/registry.py  →  MODULE_KEY = "messaging_gateway"
apps/modules/telegram_approvals/apps.py      →  name = "apps.modules.messaging_gateway"
```

URL change:
```
api/telegram-approvals/webhook/  →  api/messaging-gateway/webhook/
```
Add a 301 redirect from the old URL so existing webhook registrations keep working during the
transition.

### Model field renames (needs Django migration)

In `TenantIntegrationConfig` and `RequestApprovalConfig`:

| Old field name                               | New field name                          |
|----------------------------------------------|-----------------------------------------|
| `telegram_approvals_bridge_dispatch_url`     | `messaging_gateway_dispatch_url`        |
| `telegram_approvals_bridge_token_enc`        | `messaging_gateway_token_enc`           |
| `telegram_approvals_send_action`             | `messaging_gateway_send_action`         |
| `telegram_approvals_edit_action`             | `messaging_gateway_edit_action`         |
| `telegram_approvals_draft_notification_action` | `messaging_gateway_draft_action`      |
| `telegram_approvals_message_template`        | `messaging_gateway_message_template`    |
| `telegram_approvals_header_*_template`       | `messaging_gateway_header_*_template`   |
| `telegram_approvals_subheader_*_template`    | `messaging_gateway_subheader_*_template`|
| `n8n_integration_token_enc`                  | `messaging_gateway_token_enc` (merged)  |
| `portal_feedback_telegram_chat_id`           | `messaging_gateway_feedback_recipient_id` |
| `portal_feedback_telegram_action`            | `messaging_gateway_feedback_action`     |

Also rename `Approval` model fields:
| Old                  | New                       |
|----------------------|---------------------------|
| `approver_tg_id`     | `approver_recipient_id`   |
| `approver_tg_from_id`| `approver_user_id`        |
| `message_id`         | `gateway_message_id`      |

And `User` model fields:
| Old                  | New               |
|----------------------|-------------------|
| `telegram_chat_id`   | keep or rename to `messaging_recipient_id` — coordinate with auth team since this is also used for OTP |
| `telegram_from_id`   | keep — used by OIDC/webapp auth, not gateway |

### New Admin Settings Panel

Add a settings section in the web app visible only to admin-role users when the `messaging_gateway`
module is enabled for the tenant.

Settings to expose (all currently scattered across `TenantIntegrationConfig` and `RequestApprovalConfig`):
- Gateway dispatch URL
- Gateway auth token (write-only field, masked on display)
- Send / edit / draft action names (advanced, with sensible defaults)
- Approval message template (HTML, with variable reference)
- Header templates for each request status
- Portal feedback recipient ID (the chat/channel to send feedback to)

The panel should be a new Django view (or DRF endpoint + frontend page) rather than the raw Django
admin, so it fits the existing tenant settings UX. Gate it with:
```python
if not tenant.is_module_enabled("messaging_gateway"):
    return 403
if not request.user.has_role("admin"):
    return 403
```

---

## Checklist: All Telegram-Touching Files

Use this to make sure nothing is missed during the rename.

### Gateway (tg-gateway/)
- [ ] `main.py` — field renames, remove token header, new callback format
- [ ] `models.py` — field renames, new action names
- [ ] `db.py` — no renames needed
- [ ] `bot.py` — standalone; update only if action names are hardcoded
- [ ] `docker-compose.yml` (root) — add service + gateway network

### Backend (backend_v2/)
**Core module:**
- [ ] `apps/modules/telegram_approvals/` → rename directory to `messaging_gateway/`
- [ ] `registry.py` — MODULE_KEY, display_name
- [ ] `apps.py` — app name
- [ ] `views.py` — remove token check, update webhook parsing to flat format
- [ ] `serializers.py` — replace with platform-neutral serializer
- [ ] `services.py` — rename all payload fields, update action names
- [ ] `urls.py` — rename URL prefix, add redirect from old path
- [ ] `management/commands/refresh_telegram_approval_messages.py` — rename command

**Cross-module callers:**
- [ ] `apps/modules/requests/approval_workflow.py` — update import paths
- [ ] `apps/modules/requests/auto_requests.py` — update import paths + payload fields
- [ ] `apps/modules/requests/views.py` — update import paths
- [ ] `apps/modules/investments/approval_services.py` — update import + payload fields
- [ ] `apps/modules/feedback/views.py` — update import + payload fields
- [ ] `apps/modules/feedback/services.py` — update payload fields
- [ ] `apps/modules/notes/` — **CHECK** if telegram send exists here; update if so
- [ ] `apps/modules/registry.py` — update import and key

**Models & config:**
- [ ] `apps/modules/requests/models.py` — rename Approval fields
- [ ] `apps/tenants/models.py` — rename TenantIntegrationConfig fields
- [ ] `apps/modules/requests/models.py` — rename RequestApprovalConfig fields
- [ ] `apps/accounts/models.py` — rename User telegram fields (coordinate with auth team)
- [ ] `apps/tenants/integration_settings.py` — rename dataclass fields, update defaults
- [ ] `apps/modules/requests/integration_settings.py` — same

**Admin:**
- [ ] `apps/modules/requests/admin.py` — update field names in ApprovalAdmin
- [ ] `apps/tenants/admin.py` — update TenantAdminForm field names
- [ ] New admin settings panel (new file)

**Config:**
- [ ] `config/settings.py` — remove `N8N_INTEGRATION_TOKEN`, `N8N_TOKEN`, `TELEGRAM_APPROVALS_BRIDGE_TOKEN`
- [ ] `config/urls.py` — rename URL prefixes, keep backward-compat redirect
- [ ] `docker-compose.yml` — remove token env vars, add gateway network

**Migrations:**
- [ ] New migration for all `TenantIntegrationConfig` field renames
- [ ] New migration for all `RequestApprovalConfig` field renames
- [ ] New migration for `Approval` field renames
- [ ] New migration for `User` field renames (if renaming telegram_chat_id)
