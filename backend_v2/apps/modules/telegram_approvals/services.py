from __future__ import annotations
import logging
from datetime import datetime
from html import escape

import requests
from django.conf import settings
from django.db import transaction
from django.utils.formats import date_format
from django.utils import timezone

from apps.modules.requests.integration_settings import get_requests_telegram_integration_settings
from apps.modules.requests.models import Approval, Request, RequestApprovalStepConfig

logger = logging.getLogger(__name__)


def _bridge_dispatch_url(*, tenant_subdomain: str | None) -> str:
    configured = (getattr(settings, "TELEGRAM_APPROVALS_BRIDGE_DISPATCH_URL", "") or "").strip()
    if configured:
        return configured
    if not tenant_subdomain:
        return ""
    n8n_path = (getattr(settings, "N8N_INTEGRATION_URL_PATH", "n8n") or "n8n").strip("/")
    return f"https://{tenant_subdomain}.{settings.BASE_DOMAIN}/{n8n_path}/telegram/dispatch"


def _bridge_headers(*, tenant=None) -> dict:
    cfg = get_requests_telegram_integration_settings(tenant=tenant) if tenant is not None else None
    token = (cfg.n8n_integration_token if cfg is not None else "") or ""
    if not token and cfg is not None:
        token = cfg.bridge_token
    if not token:
        token = (getattr(settings, "N8N_INTEGRATION_TOKEN", "") or "").strip()
    if not token:
        token = (getattr(settings, "TELEGRAM_APPROVALS_BRIDGE_TOKEN", "") or "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-N8N-Integration-Token"] = token
    return headers


def _format_month(request_obj: Request) -> str:
    if request_obj.expense_year is None or request_obj.expense_month is None:
        return "-"
    try:
        dt = datetime(request_obj.expense_year, request_obj.expense_month, 1)
    except ValueError:
        return "-"
    return date_format(dt, "F Y", use_l10n=True)


def _format_submitted_at(request_obj: Request) -> str:
    if not request_obj.submitted_at:
        return "-"
    dt = timezone.localtime(request_obj.submitted_at)
    return f"{date_format(dt, 'j E Y', use_l10n=True)} г. в {dt.strftime('%H:%M')}"


def _payment_responsible_text(*, request_obj: Request) -> str:
    usernames = list(
        Approval.objects.filter(request=request_obj, step_type=Approval.STEP_TYPE_PAYMENT)
        .select_related("approver_user")
        .values_list("approver_user__username", flat=True)
        .distinct()
    )
    return ", ".join(u for u in usernames if u) if usernames else "-"


def _rejected_by_text(*, request_obj: Request) -> str:
    row = (
        Approval.objects.filter(request=request_obj, decision=Approval.DECISION_REJECTED)
        .select_related("approver_user")
        .order_by("decided_at", "id")
        .first()
    )
    if not row or not row.approver_user:
        return "-"
    return row.approver_user.username or "-"


def _message_header(*, request_obj: Request, approval: Approval | None) -> tuple[str, str | None]:
    settings_obj = get_requests_telegram_integration_settings(tenant=request_obj.tenant)
    ctx = {
        "request_id": request_obj.id,
        "payment_responsible": _payment_responsible_text(request_obj=request_obj),
        "rejected_by": _rejected_by_text(request_obj=request_obj),
    }
    def _fmt(template: str) -> str:
        try:
            return template.format_map(ctx)
        except Exception:
            logger.warning("Invalid telegram header template")
            return template

    if request_obj.status == Request.STATUS_APPROVED:
        return (
            _fmt(settings_obj.header_fully_approved_template),
            _fmt(settings_obj.subheader_payment_responsible_template),
        )
    if request_obj.status == Request.STATUS_PAYED:
        return (
            _fmt(settings_obj.header_closed_template),
            _fmt(settings_obj.subheader_payment_responsible_template),
        )
    if request_obj.status == Request.STATUS_REJECTED:
        return (
            _fmt(settings_obj.header_rejected_template),
            _fmt(settings_obj.subheader_rejected_by_template),
        )
    if approval is not None and approval.decision == Approval.DECISION_APPROVED:
        return _fmt(settings_obj.header_step_approved_template), None
    return _fmt(settings_obj.header_new_template), None


def build_approval_message(*, request_obj: Request, approval: Approval | None = None) -> str:
    header, subheader = _message_header(request_obj=request_obj, approval=approval)
    vendor_name = (request_obj.vendor_ref.name if request_obj.vendor_ref_id and request_obj.vendor_ref else request_obj.vendor) or "-"
    requester_name = request_obj.requester.username if request_obj.requester_id and request_obj.requester else "-"
    template = get_requests_telegram_integration_settings(tenant=request_obj.tenant).message_template
    context = {
        "header": escape(header),
        "subheader": escape(subheader or ""),
        "subheader_block": f"{escape(subheader)}\n\n" if subheader else "\n",
        "company_payer": escape(str(request_obj.company_payer or "-")),
        "project_title": escape(str(request_obj.title or "-")),
        "vendor": escape(str(vendor_name)),
        "category": escape(str(request_obj.category or "-")),
        "amount": escape(str(request_obj.amount)),
        "currency": escape(str(request_obj.currency or "-")),
        "payment_type": escape(str(request_obj.payment_type or "-")),
        "payment_purpose": escape(str(request_obj.payment_purpose or "-")),
        "description": escape(str(request_obj.description or "-")),
        "accrual_month": escape(_format_month(request_obj)),
        "urgency": escape(str(request_obj.urgency or "-")),
        "requester": escape(str(requester_name)),
        "submitted_at": escape(_format_submitted_at(request_obj)),
    }
    try:
        return template.format_map(context)
    except Exception:
        logger.exception("Failed to render tenant telegram approvals template")
        # Safe fallback to keep sending operational.
        return (
            f"<b>{context['header']}</b>\n"
            f"{context['subheader_block']}"
            f"Компания: {context['company_payer']}\n"
            f"Проект: {context['project_title']}\n\n"
            f"<b>💰 Финансы</b>\n"
            f"• Поставщик: {context['vendor']}\n"
            f"• Категория: {context['category']}\n"
            f"• Сумма: {context['amount']} {context['currency']}\n"
            f"• Тип оплаты: {context['payment_type']}\n\n"
            f"<b>📌 Назначение</b>\n"
            f"• Назначение платежа: {context['payment_purpose']}\n"
            f"• Описание: {context['description']}\n"
            f"• Месяц начисления: {context['accrual_month']}\n\n"
            f"<b>⏱ Статус</b>\n"
            f"• Срочность: {context['urgency']}\n"
            f"• Заявитель: {context['requester']}\n\n"
            f"🕒 Подано: {context['submitted_at']}"
        )


def _button_data(*, approval: Approval, decision: str) -> str:
    # Telegram callback_data has a strict 64-byte limit.
    # Keep payload compact: "v2_<approval_id>:<a|r>".
    code = "a" if decision == "approved" else "r"
    return f"v2_{approval.id}:{code}"


def _step_config_for_approval(*, approval: Approval) -> RequestApprovalStepConfig | None:
    return (
        RequestApprovalStepConfig.objects.select_related("payment_type_config__config")
        .filter(
            payment_type_config__config__tenant=approval.request.tenant,
            payment_type_config__payment_type=approval.request.payment_type,
            step=approval.step,
            step_type=approval.step_type,
        )
        .order_by("id")
        .first()
    )


def _resolve_payment_webapp_url(*, approval: Approval) -> str:
    step_cfg = _step_config_for_approval(approval=approval)
    template = (step_cfg.payment_webapp_url if step_cfg else "") or ""
    if not template.strip():
        return ""
    try:
        return template.format(
            request_id=approval.request_id,
            approval_id=approval.id,
            step=approval.step,
        )
    except Exception:
        logger.warning("Invalid payment_webapp_url template for approval step config id=%s", step_cfg.id if step_cfg else None)
        return template


def _inline_keyboard(*, approval: Approval) -> list[list[dict]]:
    if approval.step_type == Approval.STEP_TYPE_PAYMENT:
        step_cfg = _step_config_for_approval(approval=approval)
        mode = (
            step_cfg.payment_action_mode
            if step_cfg
            else RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK
        )
        first_btn: dict
        if mode == RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP:
            webapp_url = _resolve_payment_webapp_url(approval=approval)
            if webapp_url:
                first_btn = {"text": "Выплатить", "url": webapp_url}
            else:
                first_btn = {"text": "Выплатить", "callback_data": _button_data(approval=approval, decision="approved")}
        else:
            first_btn = {"text": "Выплатить", "callback_data": _button_data(approval=approval, decision="approved")}
        return [
            [
                first_btn,
                {"text": "Отменить", "callback_data": _button_data(approval=approval, decision="rejected")},
            ]
        ]
    return [
        [
            {"text": "✅Одобрить", "callback_data": _button_data(approval=approval, decision="approved")},
            {"text": "❌ Отклонить", "callback_data": _button_data(approval=approval, decision="rejected")},
        ]
    ]


def _dispatch_payload(
    *,
    action: str,
    request_obj: Request,
    approval: Approval,
    message_text: str,
    include_buttons: bool = True,
) -> dict:
    payload = {
        "action": action,
        "message": message_text,
        "parse_mode": "HTML",
        "chat_id": approval.approver_tg_id,
        "company": request_obj.company_payer or "",
        "approval_id": approval.id,
        "request_id": approval.request_id,
    }
    payload["inline_keyboard"] = _inline_keyboard(approval=approval) if include_buttons else []
    if action == "edit_approval_message" and approval.message_id:
        payload["message_id"] = approval.message_id
    return payload


def _post_to_bridge(*, request_obj: Request, payload: dict) -> dict | None:
    tenant = getattr(request_obj, "tenant", None)
    url = get_requests_telegram_integration_settings(tenant=tenant).dispatch_url
    if not url:
        url = _bridge_dispatch_url(tenant_subdomain=getattr(tenant, "subdomain", None))
    if not url:
        return None
    try:
        resp = requests.post(url, json=payload, headers=_bridge_headers(tenant=tenant), timeout=10)
        if resp.status_code >= 400:
            logger.warning("Telegram bridge returned HTTP %s for payload action=%s", resp.status_code, payload.get("action"))
            return None
        if not resp.content:
            return {}
        data = resp.json()
        # Some n8n flows return a one-item list with telegram response object.
        if isinstance(data, list):
            if not data:
                return {}
            first = data[0]
            return first if isinstance(first, dict) else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Failed to call Telegram bridge")
        return None


def _maybe_set_message_id(*, approval: Approval, response_data: dict | None) -> None:
    if not isinstance(response_data, dict):
        return
    raw = response_data.get("message_id")
    if raw in (None, ""):
        result = response_data.get("result") if isinstance(response_data.get("result"), dict) else {}
        raw = result.get("message_id")
    try:
        message_id = int(raw)
    except (TypeError, ValueError):
        return
    updates = []
    approval.message_id = message_id
    updates.append("message_id")
    if not approval.message_sent:
        approval.message_sent = True
        updates.append("message_sent")
    if updates:
        approval.save(update_fields=updates)


def _mark_approval_message_sent(*, approval: Approval) -> None:
    approval.message_sent = True
    approval.message_sent_at = timezone.now()
    approval.save(update_fields=["message_sent", "message_sent_at"])


def _current_pending_step(request_obj: Request) -> int | None:
    pending_steps = (
        Approval.objects.filter(request=request_obj, decision=Approval.DECISION_PENDING)
        .order_by("step")
        .values_list("step", flat=True)
    )
    return next(iter(pending_steps), None)


def current_pending_step_approvals_count(*, request_obj: Request) -> int:
    current_step = _current_pending_step(request_obj)
    if current_step is None:
        return 0
    return Approval.objects.filter(
        request=request_obj,
        step=current_step,
        decision=Approval.DECISION_PENDING,
        approver_tg_id__isnull=False,
    ).count()


@transaction.atomic
def dispatch_pending_approvals(*, request_obj: Request) -> int:
    current_step = _current_pending_step(request_obj)
    if current_step is None:
        return 0
    approvals = list(
        Approval.objects.select_for_update()
        .filter(
            request=request_obj,
            step=current_step,
            decision=Approval.DECISION_PENDING,
            message_sent=False,
            approver_tg_id__isnull=False,
        )
        .select_related("approver_user")
        .order_by("id")
    )
    if not approvals:
        return 0
    sent_count = 0
    for approval in approvals:
        message_text = build_approval_message(request_obj=request_obj, approval=approval)
        payload = _dispatch_payload(
            action=get_requests_telegram_integration_settings(tenant=request_obj.tenant).send_action,
            request_obj=request_obj,
            approval=approval,
            message_text=message_text,
        )
        response_data = _post_to_bridge(request_obj=request_obj, payload=payload)
        if response_data is None:
            continue
        _mark_approval_message_sent(approval=approval)
        _maybe_set_message_id(approval=approval, response_data=response_data)
        sent_count += 1
    return sent_count


def edit_approval_message(*, approval: Approval) -> bool:
    if not approval.message_id or approval.approver_tg_id is None:
        return False
    request_obj = approval.request
    payload = _dispatch_payload(
        action=get_requests_telegram_integration_settings(tenant=request_obj.tenant).edit_action,
        request_obj=request_obj,
        approval=approval,
        message_text=build_approval_message(request_obj=request_obj, approval=approval),
    )
    response_data = _post_to_bridge(request_obj=request_obj, payload=payload)
    _maybe_set_message_id(approval=approval, response_data=response_data)
    return response_data is not None


def deactivate_approval_message_buttons(*, approval: Approval) -> bool:
    if not approval.message_id or approval.approver_tg_id is None:
        return False
    request_obj = approval.request
    payload = _dispatch_payload(
        action=get_requests_telegram_integration_settings(tenant=request_obj.tenant).edit_action,
        request_obj=request_obj,
        approval=approval,
        message_text=build_approval_message(request_obj=request_obj, approval=approval),
        include_buttons=False,
    )
    response_data = _post_to_bridge(request_obj=request_obj, payload=payload)
    _maybe_set_message_id(approval=approval, response_data=response_data)
    return response_data is not None


def refresh_request_messages(*, request_obj: Request) -> int:
    approvals = list(
        Approval.objects.filter(request=request_obj, message_id__isnull=False)
        .select_related("request", "request__tenant", "approver_user")
        .order_by("id")
    )
    updated = 0
    for approval in approvals:
        if edit_approval_message(approval=approval):
            updated += 1
    return updated


@transaction.atomic
def resend_current_pending_step(*, request_obj: Request) -> int:
    current_step = _current_pending_step(request_obj)
    if current_step is None:
        return 0
    approvals = list(
        Approval.objects.select_for_update()
        .filter(
            request=request_obj,
            step=current_step,
            decision=Approval.DECISION_PENDING,
            approver_tg_id__isnull=False,
        )
        .select_related("request", "request__tenant", "approver_user")
        .order_by("id")
    )
    if not approvals:
        return 0

    resent = 0
    for approval in approvals:
        message_text = build_approval_message(request_obj=request_obj, approval=approval)
        if approval.message_id:
            deactivate_approval_message_buttons(approval=approval)
        payload = _dispatch_payload(
            action=get_requests_telegram_integration_settings(tenant=request_obj.tenant).send_action,
            request_obj=request_obj,
            approval=approval,
            message_text=message_text,
            include_buttons=True,
        )
        response_data = _post_to_bridge(request_obj=request_obj, payload=payload)
        if response_data is None:
            continue
        # Resend flow: old message is edited first, then new one is sent.
        # On successful send we always refresh send timestamp and message id.
        _mark_approval_message_sent(approval=approval)
        _maybe_set_message_id(approval=approval, response_data=response_data)
        resent += 1
    return resent

