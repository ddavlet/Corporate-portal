"""
Standalone contract verification: backend service layer → real gateway → Telegram.
No Django ORM, no database needed. Proves _post_to_gateway sends the right payload
and that sendMessage / editMessage / deactivate flows work end-to-end.

Run (gateway must be up on localhost:8080):
    python verify_gateway_contract.py
"""
import os
import sys
import types

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "8411387505:AAE0BSIOft8st2vPxrkOU7FuIdgymG81nsg")
os.environ.setdefault("MESSAGING_GATEWAY_SEND_URL", "http://localhost:8080/v1/messaging/send")
os.environ.setdefault("MESSAGING_GATEWAY_SEND_URL", "http://localhost:8080/v1/messaging/send")

import django
django.setup()

import requests as http
from django.conf import settings

GATEWAY_URL  = os.environ["MESSAGING_GATEWAY_SEND_URL"]
BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
RECIPIENT_ID = "8306054387"
TENANT_ID    = "verify"

RESULTS: list[tuple[bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    icon = "✅" if condition else "❌"
    print(f"  {icon} {label}" + (f": {detail}" if detail else ""))
    RESULTS.append((condition, label))


def section(title: str) -> None:
    print(f"\n── {title} {'─' * max(0, 52 - len(title))}")


# ── Minimal stubs for Approval / Request / Tenant ─────────────────────────────

def _make_approval(approval_id: int, message_id: int | None = None) -> object:
    tenant = types.SimpleNamespace(pk=1, id=1, subdomain="verify")
    request = types.SimpleNamespace(
        pk=1, id=1, tenant=tenant, tenant_id=1,
        status="1", title="Verify Contract",
        vendor="-", vendor_ref=None, vendor_ref_id=None,
        category="-", amount=100000, currency="UZS",
        payment_type="Наличные", payment_purpose="-",
        description="Gateway contract test", urgency="Обычно",
        company_payer="-", submitted_at=None,
        billing_date=None, expense_year=None, expense_month=None,
        requester=types.SimpleNamespace(full_name="Test Requester", username="req"),
        requester_id=1,
    )
    approval = types.SimpleNamespace(
        pk=approval_id, id=approval_id,
        request=request, request_id=1,
        approver_tg_id=int(RECIPIENT_ID),
        approver_tg_from_id=int(RECIPIENT_ID),
        approver_user=types.SimpleNamespace(full_name="Test Approver", username="appr"),
        message_id=message_id,
        message_sent=message_id is not None,
        message_sent_at=None,
        step=1,
        step_type="serial",
        decision="pending",
    )
    return approval


# ── Import the real service functions ─────────────────────────────────────────

from apps.modules.telegram_approvals.services import (
    _post_to_gateway,
    _dispatch_payload,
    build_approval_message,
    _buttons,
)
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings


section("Health check")
try:
    health_url = GATEWAY_URL.replace("/v1/messaging/send", "/health")
    r = http.get(health_url, timeout=3)
    check("gateway reachable", r.status_code == 200, r.text.strip())
except Exception as exc:
    check("gateway reachable", False, str(exc))
    print("\nGateway not running. Start it first: uvicorn main:app --port 8080")
    sys.exit(1)


section("sendMessage via _post_to_gateway")

approval = _make_approval(approval_id=1)

# Monkey-patch get_requests_messaging_gateway_settings to return real action names
import apps.modules.telegram_approvals.services as svc
_orig_get = svc.get_requests_messaging_gateway_settings

class _FakeSettings:
    dispatch_url = GATEWAY_URL
    send_action = "send_interactive"
    edit_action = "edit"
    draft_notification_action = "send"
    message_template = "{header}\n{subheader_block}Проект: {project_title}\nСумма: {amount} {currency}"
    header_new_template = "💰 Новая заявка № {request_id}"
    header_step_approved_template = "✅ Заявка № {request_id} одобрена"
    header_fully_approved_template = "✅ Заявка № {request_id} полностью одобрена"
    header_closed_template = "☑️ Заявка № {request_id} закрыта"
    header_rejected_template = "❌ Заявка № {request_id} отклонена"
    subheader_payment_responsible_template = "Ответственный: {payment_responsible}"
    subheader_rejected_by_template = "Отклонил: {rejected_by}"
    bridge_token = ""
    n8n_integration_token = ""

def _patched_get(*args, **kwargs):
    return _FakeSettings()

svc.get_requests_messaging_gateway_settings = _patched_get

# Also patch ORM queries used by build_approval_message internals
from unittest.mock import patch, MagicMock
mock_qs = MagicMock()
mock_qs.filter.return_value = mock_qs
mock_qs.select_related.return_value = mock_qs
mock_qs.distinct.return_value = mock_qs
mock_qs.order_by.return_value = mock_qs
mock_qs.__iter__ = lambda self: iter([])
mock_qs.first.return_value = None

with patch("apps.modules.telegram_approvals.services.Approval.objects", mock_qs), \
     patch("apps.modules.telegram_approvals.services.RequestApprovalStepConfig.objects", mock_qs), \
     patch("apps.modules.telegram_approvals.services._get_tenant_bot_token", return_value=BOT_TOKEN):

    message_text = build_approval_message(request_obj=approval.request, approval=approval)
    payload = _dispatch_payload(
        action="send_interactive",
        request_obj=approval.request,
        approval=approval,
        message_text=message_text,
    )

    response = _post_to_gateway(request_obj=approval.request, payload=payload)

check("_post_to_gateway returned response", response is not None)
if response:
    message_id = (response.get("result") or {}).get("message_id") or response.get("message_id")
    check("sendMessage returned real message_id from Telegram", isinstance(message_id, int) and message_id > 0, str(message_id))
    check("payload used text field (not message)", "text" in payload)
    check("payload used recipient_id (not chat_id)", "recipient_id" in payload and "chat_id" not in payload)
    check("payload used buttons (not inline_keyboard)", "buttons" in payload and "inline_keyboard" not in payload)
    btn_row = payload.get("buttons", [[]])[0] if payload.get("buttons") else []
    if btn_row:
        check("buttons use label/value (not text/callback_data)", "label" in btn_row[0] and "value" in btn_row[0])
else:
    message_id = None
    print("    (send failed — skipping further checks)")


section("editMessage (deactivate buttons) via _post_to_gateway")

if message_id:
    approval2 = _make_approval(approval_id=1, message_id=message_id)
    approval2.request.status = "APPROVED"

    with patch("apps.modules.telegram_approvals.services.Approval.objects", mock_qs), \
         patch("apps.modules.telegram_approvals.services.RequestApprovalStepConfig.objects", mock_qs), \
         patch("apps.modules.telegram_approvals.services._get_tenant_bot_token", return_value=BOT_TOKEN):
        edit_payload = _dispatch_payload(
            action="edit",
            request_obj=approval2.request,
            approval=approval2,
            message_text=message_text,
            include_buttons=False,
        )
        edit_response = _post_to_gateway(request_obj=approval2.request, payload=edit_payload)

    check("editMessage returned response", edit_response is not None)
    if edit_response:
        edited_id = (edit_response.get("result") or {}).get("message_id") or edit_response.get("message_id")
        check("editMessage returned same message_id", edited_id == message_id, f"{edited_id} == {message_id}")
        check("edit payload has buttons=[]", edit_payload.get("buttons") == [])
        check("edit payload has message_id", edit_payload.get("message_id") == message_id)


section("Cleanup")

if message_id:
    del_resp = http.post(GATEWAY_URL, json={
        "action": "delete",
        "bot_token": BOT_TOKEN,
        "tenant_id": TENANT_ID,
        "recipient_id": RECIPIENT_ID,
        "message_id": message_id,
    }, timeout=5)
    check("test message deleted from Telegram", del_resp.status_code == 200)


# ── Summary ───────────────────────────────────────────────────────────────────
passed = sum(1 for ok, _ in RESULTS if ok)
total = len(RESULTS)
print(f"\n{'═' * 58}")
print(f"  Results: {passed}/{total} passed")
if passed < total:
    for ok, label in RESULTS:
        if not ok:
            print(f"    ❌ FAILED: {label}")
print(f"{'═' * 58}\n")
sys.exit(0 if passed == total else 1)
