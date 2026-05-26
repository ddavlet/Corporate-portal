# n8n AI Request Creation Endpoint

## Overview

This endpoint is intended for AI/n8n flows that collect request details from a user and create a `Request` in backend using the same validation and workflow logic as frontend creation.

- **Method:** `POST`
- **Path:** `/api/n8n/requests/ai-create/`
- **Purpose:** create a request from user-level fields and automatically bootstrap approval steps.

---

## Authentication and Headers

Required headers:

- `X-N8N-Integration-Token: <token>`
- `Authorization: Bearer <access_jwt>`
- `Host: <tenant-subdomain>.<base-domain>`
- `Content-Type: application/json`

Recommended:

- `Accept: application/json`

Notes:

- Tenant is resolved from host/subdomain.
- Integration token and JWT are both required.

---

## Access Control

The caller must have effective access to module `requests` in the tenant:

- Tenant membership is active
- `requests` module is enabled for tenant
- Caller role is one of: `admin`, `director`, `approver`, `requester`, `accountant`, `cashier`

If not, endpoint returns `403 Forbidden`.

---

## Request Body

Endpoint accepts frontend-like request fields (`PortalRequestSerializer` flow).

### Common fields

- `company_payer`: string (optional)
- `category`: string (optional, can be derived by payment purpose config)
- `vendor`: string (optional)
- `vendor_ref`: integer (optional; vendor id)
- `contract_ref`: integer (optional; contract id)
- `description`: string (optional, blank allowed)
- `amount`: decimal string (required in practice)
- `currency`: `UZS | USD | EUR | RUB`
- `payment_type`: `Наличные | Перечисление | Пополнение | Платежная карта | Начисление ЗП`
- `urgency`: `Низко | Обычно | Срочно`
- `requester`: integer (conditional, see below)
- `payment_purpose`: string (required if tenant form config enforces it)
- `expense_id`: string (optional)
- `expense_year`: integer (optional)
- `expense_month`: integer (optional)
- `expense_day`: integer (optional)
- `billing_date`: `YYYY-MM-DD` (required)
- `amortization_months`: integer 1..6 (optional, default `1`)

### Requester behavior

- If caller is **admin/director**, `requester` is expected.
- If caller is **not admin/director**, incoming `requester` is ignored and replaced with JWT user.

### Read-only / ignored for create

These values are not accepted as writable create input:

- `id`
- `created_at`
- `created_by`
- `status`
- `attachments`
- `expense_link`

---

## Backend Side Effects (Automatic)

After request is saved, backend automatically:

1. Creates approval rows using current approval config.
2. Recalculates status when needed.
3. Routes approvals via existing workflow logic.

This means AI only sends user-level fields; approval pipeline is backend-managed.

---

## Responses

### Success

- **Status:** `201 Created`
- **Body:** created request serialized with portal serializer fields.

### Error statuses

- `400 Bad Request` - validation or payload errors
- `401 Unauthorized` - missing/invalid integration token or JWT
- `403 Forbidden` - insufficient module/role access

---

## Example cURL

```bash
curl -X POST "https://acme.example.com/api/n8n/requests/ai-create/" \
  -H "X-N8N-Integration-Token: integ-test-secret" \
  -H "Authorization: Bearer <access_jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "payment_type": "Наличные",
    "amount": "120000.00",
    "currency": "UZS",
    "urgency": "Обычно",
    "billing_date": "2026-05-06",
    "payment_purpose": "Интернет",
    "description": "May internet invoice",
    "vendor_ref": 12,
    "requester": 15
  }'
```

---

## Suggested AI Agent Completion Criteria

Before calling endpoint, AI agent should ensure it has at least:

- `payment_type`
- `amount`
- `currency`
- `urgency`
- `billing_date`

And tenant-dependent fields if configured:

- `payment_purpose`
- `vendor_ref`
- `contract_ref`
- `requester` (when running under admin/director token)
