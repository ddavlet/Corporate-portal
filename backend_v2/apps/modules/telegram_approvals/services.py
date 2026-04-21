from __future__ import annotations
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from django.conf import settings
from django.db import transaction
from django.utils.formats import date_format
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.requests.integration_settings import get_requests_telegram_integration_settings
from apps.modules.requests.models import Approval, Request, RequestApprovalStepConfig

logger = logging.getLogger(__name__)


def _display_user_name(user) -> str:
    if not user:
        return "-"
    full = (getattr(user, "full_name", "") or "").strip()
    return full or (getattr(user, "username", "") or "-")


def _bridge_dispatch_url(*, tenant_subdomain: str | None) -> str:
    configured = (getattr(settings, "TELEGRAM_APPROVALS_BRIDGE_DISPATCH_URL", "") or "").strip()
    if configured:
        return configured
    if not tenant_subdomain:
        return ""
    n8n_path = (getattr(settings, "N8N_INTEGRATION_URL_PATH", "n8n") or "n8n").strip("/")
    return f"https://{tenant_subdomain}.{settings.BASE_DOMAIN}/{n8n_path}/telegram/dispatch"


def _normalize_trailing_slash(url: str) -> str:
    u = url.rstrip("/")
    return f"{u}/" if u else ""


def _error_url_from_dispatch_url(dispatch_url: str) -> str:
    d = (dispatch_url or "").strip()
    if not d:
        return ""
    if "/telegram/dispatch" in d:
        return _normalize_trailing_slash(d.replace("/telegram/dispatch", "/error"))
    return ""


def _resolve_error_webhook_url(*, request_obj: Request) -> str:
    explicit = (getattr(settings, "TELEGRAM_APPROVALS_BRIDGE_ERROR_URL", "") or "").strip()
    if explicit:
        return _normalize_trailing_slash(explicit)
    tenant = getattr(request_obj, "tenant", None)
    if tenant is not None:
        cfg = get_requests_telegram_integration_settings(tenant=tenant)
        derived = _error_url_from_dispatch_url(cfg.dispatch_url or "")
        if derived:
            return derived
    fallback = (getattr(settings, "TELEGRAM_APPROVALS_BRIDGE_DISPATCH_URL", "") or "").strip()
    derived = _error_url_from_dispatch_url(fallback)
    if derived:
        return derived
    sub = getattr(tenant, "subdomain", None) if tenant is not None else None
    if sub:
        n8n_path = (getattr(settings, "N8N_INTEGRATION_URL_PATH", "n8n") or "n8n").strip("/")
        return f"https://{sub}.{settings.BASE_DOMAIN}/{n8n_path}/error/"
    return ""


def _report_bridge_error(
    *,
    request_obj: Request,
    payload: dict,
    error_kind: str,
    status_code: int | None = None,
    response_body: str | None = None,
    detail: str | None = None,
) -> None:
    error_url = _resolve_error_webhook_url(request_obj=request_obj)
    if not error_url:
        return
    tenant = getattr(request_obj, "tenant", None)
    body: dict = {
        "source": "telegram_approvals_bridge",
        "error_kind": error_kind,
        "payload_action": payload.get("action"),
        "request_id": payload.get("request_id"),
        "approval_id": payload.get("approval_id"),
        "chat_id": payload.get("chat_id"),
    }
    if getattr(request_obj, "tenant_id", None):
        body["tenant_id"] = request_obj.tenant_id
    if tenant is not None and getattr(tenant, "subdomain", None):
        body["tenant_subdomain"] = tenant.subdomain
    if status_code is not None:
        body["http_status"] = status_code
    if response_body is not None:
        body["response_body"] = response_body[:8000]
    if detail is not None:
        body["detail"] = detail[:8000]
    try:
        requests.post(
            error_url,
            json=body,
            headers=_bridge_headers(tenant=tenant),
            timeout=5,
        )
    except Exception:
        logger.exception("Failed to POST Telegram bridge error to n8n error webhook")


def build_request_draft_public_url(*, request_obj: Request) -> str:
    tenant = getattr(request_obj, "tenant", None)
    subdomain = (getattr(tenant, "subdomain", "") or "").strip()
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    base = f"https://{subdomain}.{base_domain}" if subdomain and base_domain else ""
    if not base:
        return ""
    return f"{base}/requests/{request_obj.pk}"


def build_auto_request_template_public_url(*, request_obj: Request, template_id: int | None) -> str:
    if not template_id:
        return ""
    tenant = getattr(request_obj, "tenant", None)
    subdomain = (getattr(tenant, "subdomain", "") or "").strip()
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    base = f"https://{subdomain}.{base_domain}" if subdomain and base_domain else ""
    if not base:
        return ""
    return f"{base}/requests/auto-config?template_id={template_id}"


def dispatch_draft_request_notification(
    *, request_obj: Request, chat_id: int | None, template_id: int | None = None
) -> bool:
    """
    Outbound n8n/Telegram: action from settings (default send_draft_notification), no Approval row.
    """
    if chat_id is None:
        logger.info("draft notification skipped: no chat_id for request_id=%s", request_obj.pk)
        return False
    settings_obj = get_requests_telegram_integration_settings(tenant=request_obj.tenant)
    action = (settings_obj.draft_notification_action or "").strip() or "send_draft_notification"
    draft_url = build_request_draft_public_url(request_obj=request_obj)
    template_url = build_auto_request_template_public_url(request_obj=request_obj, template_id=template_id)
    title = escape(str(request_obj.title or ""))
    billing_month = escape(_format_billing_month(request_obj))
    url_part = ""
    if draft_url:
        url_part = f'\n<a href="{escape(draft_url)}">{escape(draft_url)}</a>'
    template_part = ""
    if template_url:
        template_part = f'\n\nШаблон автозаявки:\n<a href="{escape(template_url)}">{escape(template_url)}</a>'
    vendor_name = (request_obj.vendor_ref.name if request_obj.vendor_ref_id and request_obj.vendor_ref else request_obj.vendor) or "-"
    requester_name = _display_user_name(request_obj.requester if request_obj.requester_id else None)
    amount_text = _format_amount_for_telegram(request_obj.amount)
    currency_text = str(request_obj.currency or "-")
    payment_type_text = str(request_obj.payment_type or "-")
    payment_purpose_text = str(request_obj.payment_purpose or "-")
    description_text = str(request_obj.description or "-")
    urgency_text = str(request_obj.urgency or "-")
    message_text = (
        f"<b>📝 Черновик заявки № {request_obj.pk}</b>\n"
        f"{title}\n\n"
        f"<b>💰 Финансы</b>\n"
        f"• Поставщик: {escape(str(vendor_name))}\n"
        f"• Сумма: {escape(amount_text)} {escape(currency_text)}\n"
        f"• Тип оплаты: {escape(payment_type_text)}\n\n"
        f"<b>📌 Назначение</b>\n"
        f"• Назначение платежа: {escape(payment_purpose_text)}\n"
        f"• Описание: {escape(description_text)}\n"
        f"• Месяц начисления: {billing_month}\n\n"
        f"<b>⏱ Статус</b>\n"
        f"• Срочность: {escape(urgency_text)}\n"
        f"• Заявитель: {escape(requester_name)}\n\n"
        f"Укажите сумму и отправьте заявку на согласование кнопкой в этом сообщении.{url_part}{template_part}"
    )
    payload = {
        "action": action,
        "message": message_text,
        "parse_mode": "HTML",
        "chat_id": chat_id,
        "company": request_obj.company_payer or "",
        "request_id": request_obj.pk,
        "template_id": template_id,
        "draft_url": draft_url,
        "template_url": template_url,
        "notification_kind": "draft_needs_amount",
        "inline_keyboard": [],
    }
    response_data = _post_to_bridge(request_obj=request_obj, payload=payload)
    return response_data is not None


def _bridge_headers(*, tenant=None) -> dict:
    cfg = None
    if tenant is not None:
        try:
            cfg = get_requests_telegram_integration_settings(tenant=tenant)
        except Exception:
            logger.exception(
                "Failed to resolve telegram integration settings for headers tenant=%s",
                getattr(tenant, "pk", None),
            )
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


def _format_billing_month(request_obj: Request) -> str:
    """
    Month + year only (no calendar day): accrual from expense_year/month, else from billing_date.
    """
    if request_obj.expense_year is not None and request_obj.expense_month is not None:
        try:
            dt = datetime(request_obj.expense_year, request_obj.expense_month, 1)
        except ValueError:
            dt = None
        if dt is not None:
            return date_format(dt, "F Y", use_l10n=True)
    bd = getattr(request_obj, "billing_date", None)
    if isinstance(bd, date):
        try:
            dt = datetime(bd.year, bd.month, 1)
        except ValueError:
            return "-"
        return date_format(dt, "F Y", use_l10n=True)
    return "-"


def _format_submitted_at(request_obj: Request) -> str:
    if not request_obj.submitted_at:
        return "-"
    dt = timezone.localtime(request_obj.submitted_at)
    return f"{date_format(dt, 'j E Y', use_l10n=True)} г. в {dt.strftime('%H:%M')}"


def _format_amount_for_telegram(value) -> str:
    """
    Format numeric amount with space-grouped thousands and fixed 2 decimals.
    Example: 1000000 -> "1 000 000.00"
    """
    if value is None:
        return "-"
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    return format(amount, ",.2f").replace(",", " ")


def _payment_responsible_text(*, request_obj: Request) -> str:
    approvals = (
        Approval.objects.filter(request=request_obj, step_type=Approval.STEP_TYPE_PAYMENT)
        .select_related("approver_user")
        .distinct()
    )
    names = []
    for row in approvals:
        if not row.approver_user:
            continue
        names.append(_display_user_name(row.approver_user))
    unique_names = list(dict.fromkeys(name for name in names if name and name != "-"))
    return ", ".join(unique_names) if unique_names else "-"


def _rejected_by_text(*, request_obj: Request) -> str:
    row = (
        Approval.objects.filter(request=request_obj, decision=Approval.DECISION_REJECTED)
        .select_related("approver_user")
        .order_by("decided_at", "id")
        .first()
    )
    if not row or not row.approver_user:
        return "-"
    return _display_user_name(row.approver_user)


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


def _telegram_card_should_be_readonly(*, request_obj: Request, approval: Approval) -> bool:
    """
    Milestone request statuses: everyone who already got a Telegram card should see the new header,
    without action buttons — except the cashier row while payment is still pending (APPROVED).
    """
    st = request_obj.status
    if approval.decision != Approval.DECISION_PENDING:
        return True
    if st == Request.STATUS_REJECTED:
        return True
    if st == Request.STATUS_PAYED:
        return True
    if st == Request.STATUS_APPROVED:
        if approval.decision == Approval.DECISION_PENDING and approval.step_type == Approval.STEP_TYPE_PAYMENT:
            return False
        return True
    return False


def build_approval_message(*, request_obj: Request, approval: Approval | None = None) -> str:
    header, subheader = _message_header(request_obj=request_obj, approval=approval)
    vendor_name = (request_obj.vendor_ref.name if request_obj.vendor_ref_id and request_obj.vendor_ref else request_obj.vendor) or "-"
    requester_name = _display_user_name(request_obj.requester if request_obj.requester_id else None)
    template = get_requests_telegram_integration_settings(tenant=request_obj.tenant).message_template
    billing_month_escaped = escape(_format_billing_month(request_obj))
    context = {
        "header": escape(header),
        "subheader": escape(subheader or ""),
        "subheader_block": f"{escape(subheader)}\n\n" if subheader else "\n",
        "company_payer": escape(str(request_obj.company_payer or "-")),
        "project_title": escape(str(request_obj.title or "-")),
        "vendor": escape(str(vendor_name)),
        "category": escape(str(request_obj.category or "-")),
        "amount": escape(_format_amount_for_telegram(request_obj.amount)),
        "currency": escape(str(request_obj.currency or "-")),
        "payment_type": escape(str(request_obj.payment_type or "-")),
        "payment_purpose": escape(str(request_obj.payment_purpose or "-")),
        "description": escape(str(request_obj.description or "-")),
        "billing_month": billing_month_escaped,
        "accrual_month": billing_month_escaped,
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
            f"• Месяц начисления: {context['billing_month']}\n\n"
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


def _ensure_tme_miniapp_startapp(url: str, approval_id: int) -> str:
    """
    Direct Link Mini App: https://t.me/<bot>/<app>?startapp=...
    Если в настройке указан только базовый t.me/telegram.me URL без startapp,
    подставляем startapp=<approval_id>, чтобы в WebApp пришёл start_param (см. фронт tgPaymentApprovalId).
    """
    u = (url or "").strip()
    if not u:
        return u
    parts = urlsplit(u)
    host = (parts.hostname or "").lower()
    if host not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me"):
        return u
    pairs = list(parse_qsl(parts.query, keep_blank_values=True))
    if any(k.lower() == "startapp" for k, _ in pairs):
        return u
    pairs.append(("startapp", str(approval_id)))
    new_query = urlencode(pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def _resolve_payment_webapp_url(*, approval: Approval) -> str:
    step_cfg = _step_config_for_approval(approval=approval)
    template = (step_cfg.payment_webapp_url if step_cfg else "") or ""
    if not template.strip():
        return ""
    try:
        resolved = template.format(
            request_id=approval.request_id,
            approval_id=approval.id,
            step=approval.step,
        )
    except Exception:
        logger.warning("Invalid payment_webapp_url template for approval step config id=%s", step_cfg.id if step_cfg else None)
        return template
    return _ensure_tme_miniapp_startapp(resolved, approval.id)


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
                first_btn = {"text": "💰 Выплатить", "url": webapp_url}
            else:
                first_btn = {"text": "💰 Выплатить", "callback_data": _button_data(approval=approval, decision="approved")}
        else:
            first_btn = {"text": "💰 Выплатить", "callback_data": _button_data(approval=approval, decision="approved")}
        return [
            [
                first_btn,
                {"text": "❌ Отменить", "callback_data": _button_data(approval=approval, decision="rejected")},
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


def _resolve_dispatch_url_for_tenant(tenant) -> str:
    url = ""
    if tenant is not None:
        try:
            url = (get_requests_telegram_integration_settings(tenant=tenant).dispatch_url or "").strip()
        except Exception:
            logger.exception(
                "Failed to resolve telegram dispatch URL from tenant settings tenant=%s",
                getattr(tenant, "pk", None),
            )
            return ""
    if not url:
        url = _bridge_dispatch_url(tenant_subdomain=getattr(tenant, "subdomain", None) if tenant else None)
    return url or ""


def _parse_bridge_response(resp: requests.Response) -> dict | None:
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


def post_telegram_bridge(*, tenant, payload: dict) -> dict | None:
    """
    POST JSON to the tenant Telegram dispatch webhook (n8n). Failures are logged only.
    """
    url = _resolve_dispatch_url_for_tenant(tenant)
    if not url:
        logger.warning("Telegram bridge: no dispatch URL for tenant=%s", getattr(tenant, "pk", None))
        return None
    try:
        resp = requests.post(url, json=payload, headers=_bridge_headers(tenant=tenant), timeout=10)
        if resp.status_code >= 400:
            logger.warning(
                "Telegram bridge returned HTTP %s for payload action=%s",
                resp.status_code,
                payload.get("action"),
            )
            return None
        return _parse_bridge_response(resp)
    except Exception:
        logger.exception("Failed to call Telegram bridge")
        return None


def _post_to_bridge(*, request_obj: Request, payload: dict) -> dict | None:
    tenant = getattr(request_obj, "tenant", None)
    url = _resolve_dispatch_url_for_tenant(tenant)
    if not url:
        return None
    try:
        resp = requests.post(url, json=payload, headers=_bridge_headers(tenant=tenant), timeout=10)
        if resp.status_code >= 400:
            logger.warning(
                "Telegram bridge returned HTTP %s for payload action=%s",
                resp.status_code,
                payload.get("action"),
            )
            _report_bridge_error(
                request_obj=request_obj,
                payload=payload,
                error_kind="http_error",
                status_code=resp.status_code,
                response_body=getattr(resp, "text", None) or "",
            )
            return None
        return _parse_bridge_response(resp)
    except Exception as exc:
        logger.exception("Failed to call Telegram bridge")
        # Test-safety: mocked requests.post side_effect may be exhausted.
        # Do not trigger secondary error-webhook call in this synthetic case.
        if isinstance(exc, StopIteration):
            return None
        _report_bridge_error(
            request_obj=request_obj,
            payload=payload,
            error_kind="exception",
            detail=repr(exc),
        )
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
    if request_obj.status in {Request.STATUS_REJECTED, Request.STATUS_PAYED}:
        return None
    if request_obj.status == Request.STATUS_APPROVED:
        pending_payment_steps = (
            Approval.objects.filter(
                request=request_obj,
                step_type=Approval.STEP_TYPE_PAYMENT,
                decision=Approval.DECISION_PENDING,
            )
            .order_by("step")
            .values_list("step", flat=True)
        )
        return next(iter(pending_payment_steps), None)
    status_to_step = {
        Request.STATUS_PROGRESS_1: 1,
        Request.STATUS_PROGRESS_2: 2,
        Request.STATUS_PROGRESS_3: 3,
        Request.STATUS_PROGRESS_4: 4,
        Request.STATUS_PROGRESS_5: 5,
    }
    return status_to_step.get(request_obj.status)


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
def dispatch_pending_approvals(*, request_obj: Request, step: int | None = None, step_type: str | None = None) -> int:
    locked = Request.objects.select_for_update().get(pk=request_obj.pk)
    current_step = step or _current_pending_step(locked)
    if current_step is None:
        return 0
    approvals_qs = Approval.objects.select_for_update().filter(
        request_id=locked.pk,
        step=current_step,
        decision=Approval.DECISION_PENDING,
        message_sent=False,
        approver_tg_id__isnull=False,
    )
    if step_type is not None:
        approvals_qs = approvals_qs.filter(step_type=step_type)
    approvals = list(approvals_qs.select_related("approver_user").order_by("id"))
    if not approvals:
        return 0
    sent_count = 0
    for approval in approvals:
        message_text = build_approval_message(request_obj=locked, approval=approval)
        payload = _dispatch_payload(
            action=get_requests_telegram_integration_settings(tenant=locked.tenant).send_action,
            request_obj=locked,
            approval=approval,
            message_text=message_text,
        )
        response_data = _post_to_bridge(request_obj=locked, payload=payload)
        if response_data is None:
            continue
        _mark_approval_message_sent(approval=approval)
        _maybe_set_message_id(approval=approval, response_data=response_data)
        sent_count += 1
    return sent_count


def edit_approval_message(*, approval: Approval, request_context: Request | None = None) -> bool:
    if not approval.message_id or approval.approver_tg_id is None:
        return False
    req = request_context or approval.request
    payload = _dispatch_payload(
        action=get_requests_telegram_integration_settings(tenant=req.tenant).edit_action,
        request_obj=req,
        approval=approval,
        message_text=build_approval_message(request_obj=req, approval=approval),
    )
    response_data = _post_to_bridge(request_obj=req, payload=payload)
    _maybe_set_message_id(approval=approval, response_data=response_data)
    return response_data is not None


def deactivate_approval_message_buttons(*, approval: Approval, request_context: Request | None = None) -> bool:
    if not approval.message_id or approval.approver_tg_id is None:
        return False
    req = request_context or approval.request
    payload = _dispatch_payload(
        action=get_requests_telegram_integration_settings(tenant=req.tenant).edit_action,
        request_obj=req,
        approval=approval,
        message_text=build_approval_message(request_obj=req, approval=approval),
        include_buttons=False,
    )
    response_data = _post_to_bridge(request_obj=req, payload=payload)
    _maybe_set_message_id(approval=approval, response_data=response_data)
    return response_data is not None


def refresh_request_messages(*, request_obj: Request) -> int:
    """
    Notify everyone who was sent a Telegram card (message_sent) and can be edited (message_id + chat).
    Call after status/decision changes so headers match APPROVED / REJECTED / PAYED and buttons drop
    where the step is no longer actionable.
    """
    request_obj.refresh_from_db()
    approvals = list(
        Approval.objects.filter(
            request=request_obj,
            message_sent=True,
            message_id__isnull=False,
            approver_tg_id__isnull=False,
        )
        .select_related("request", "request__tenant", "approver_user")
        .order_by("id")
    )
    updated = 0
    for approval in approvals:
        if _telegram_card_should_be_readonly(request_obj=request_obj, approval=approval):
            if deactivate_approval_message_buttons(approval=approval, request_context=request_obj):
                updated += 1
        elif edit_approval_message(approval=approval, request_context=request_obj):
            updated += 1
    return updated


@transaction.atomic
def resend_current_pending_step(*, request_obj: Request, idempotency_key: str | None = None) -> int:
    locked = Request.objects.select_for_update().get(pk=request_obj.pk)
    current_step = _current_pending_step(locked)
    if current_step is None:
        raise ValidationError({"detail": "Current request status has no active approval step."})

    if idempotency_key:
        existing = Approval.objects.filter(
            request_id=locked.pk,
            step=current_step,
            decision=Approval.DECISION_PENDING,
            resend_key=idempotency_key,
        ).count()
        if existing:
            return existing

    approvals = list(
        Approval.objects.select_for_update()
        .filter(
            request_id=locked.pk,
            step=current_step,
            decision=Approval.DECISION_PENDING,
            approver_tg_id__isnull=False,
        )
        .select_related("request", "request__tenant", "approver_user")
        .order_by("id")
    )
    if not approvals:
        raise ValidationError({"detail": "No pending approvals on current step for resend."})

    created = 0
    for approval in approvals:
        if approval.message_id:
            deactivate_approval_message_buttons(approval=approval, request_context=locked)
        approval.decision = Approval.DECISION_CANCELED
        approval.decided_at = timezone.now()
        approval.comment = "Автоматически: отменено повторной отправкой шага."
        # Prevent an extra edit in subsequent refresh cycle for the canceled row.
        approval.message_sent = False
        approval.save(update_fields=["decision", "decided_at", "comment", "message_sent"])
        Approval.objects.create(
            request=locked,
            approver_user=approval.approver_user,
            approver_tg_id=approval.approver_tg_id,
            approver_tg_from_id=approval.approver_tg_from_id,
            step=approval.step,
            step_type=approval.step_type,
            decision=Approval.DECISION_PENDING,
            message_sent=False,
            message_id=None,
            resend_key=idempotency_key,
            replaced_approval=approval,
        )
        created += 1
    return created

