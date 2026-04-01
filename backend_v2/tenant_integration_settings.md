# Tenant Integration Settings

Portal endpoint for tenant admins:

- `GET /api/tenant-integration-config/`
- `PUT /api/tenant-integration-config/`

Access:

- JWT required
- active tenant membership
- tenant role `admin`

## Purpose

Tenant-level runtime configuration for integrations that previously depended only on ENV or hardcoded values.

Resolver priority:

1. tenant DB config (`TenantIntegrationConfig`)
2. ENV fallback (`settings.py`)

## Fields

- `telegram_bot_token` (secret, masked in API responses; used by OTP and Notes)
- `telegram_approvals_bridge_dispatch_url`
- `telegram_approvals_send_action`
- `telegram_approvals_edit_action`
- `telegram_approvals_message_template` (HTML template for approval cards)
- `telegram_approvals_header_new_template`
- `telegram_approvals_header_step_approved_template`
- `telegram_approvals_header_fully_approved_template`
- `telegram_approvals_header_closed_template`
- `telegram_approvals_header_rejected_template`
- `telegram_approvals_subheader_payment_responsible_template`
- `telegram_approvals_subheader_rejected_by_template`
- `telegram_approvals_bridge_token` (secret, masked in API responses)
- `n8n_integration_token` (secret, masked)
- `requests_file_gateway_token` (secret, masked)

## Secret handling

Secrets are stored encrypted in DB and are never returned in clear-text from API.

`telegram_approvals_message_template` is not a secret and is returned as-is.

## Resend approvals behavior

Resend action is available from request module endpoint:

- `POST /api/requests/{id}/approvals/resend/`

Behavior for current pending step only:

1. Edit old Telegram message and remove `inline_keyboard`
2. Send a new message with approval buttons
3. Save new `message_id` into `Approval.message_id`

