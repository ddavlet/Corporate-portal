from __future__ import annotations
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.utils.formats import date_format
from django.utils import timezone

from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalStepConfig,
    RequestAttachment,
    RequestComment,
)

logger = logging.getLogger(__name__)


def _display_user_name(user) -> str:
    if not user:
        return "-"
    full = (getattr(user, "full_name", "") or "").strip()
    return full or (getattr(user, "username", "") or "-")


def build_request_draft_public_url(*, request_obj: Request) -> str:
    tenant = getattr(request_obj, "tenant", None)
    subdomain = (getattr(tenant, "subdomain", "") or "").strip()
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    base = f"https://{subdomain}.{base_domain}" if subdomain and base_domain else ""
    if not base:
        return ""
    return f"{base}/app/requests/{request_obj.pk}"


def build_contract_public_url(*, request_obj: Request) -> str:
    """Public web-app URL that opens the request's contract on the Contracts page.

    Empty string when the request has no linked contract or the tenant base URL
    cannot be resolved — the caller then omits the button (graceful degradation).
    """
    contract_id = getattr(request_obj, "contract_ref_id", None)
    if not contract_id:
        return ""
    tenant = getattr(request_obj, "tenant", None)
    subdomain = (getattr(tenant, "subdomain", "") or "").strip()
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    base = f"https://{subdomain}.{base_domain}" if subdomain and base_domain else ""
    if not base:
        return ""
    return f"{base}/app/contracts?contract={contract_id}"


def build_auto_request_template_public_url(*, request_obj: Request, template_id: int | None) -> str:
    if not template_id:
        return ""
    tenant = getattr(request_obj, "tenant", None)
    subdomain = (getattr(tenant, "subdomain", "") or "").strip()
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    base = f"https://{subdomain}.{base_domain}" if subdomain and base_domain else ""
    if not base:
        return ""
    return f"{base}/app/requests/auto-config?template_id={template_id}"


def _format_contract_block(request_obj: Request) -> str:
    """Telegram contract section. Empty string when the request has no contract — no placeholder line."""
    contract = getattr(request_obj, "contract_ref", None)
    if not contract:
        return ""
    number = escape(str(contract.contract_number or "").strip() or "-")
    date_from = contract.date_from
    date_to = contract.date_to
    if date_from and date_to:
        period = f"{date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}"
    elif date_from:
        period = date_from.strftime("%d.%m.%Y")
    else:
        period = "-"
    return f"\n\n<b>📄 Договор</b>\n• Номер: {number}\n• Период: {escape(period)}"


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
    settings_obj = get_requests_messaging_gateway_settings(tenant=request_obj.tenant)
    ctx = {
        "request_id": request_obj.id,
        "rejected_by": _rejected_by_text(request_obj=request_obj),
    }
    def _fmt(template: str) -> str:
        try:
            return template.format_map(ctx)
        except Exception:
            logger.warning("Invalid telegram header template")
            return template

    if request_obj.status == Request.STATUS_APPROVED:
        return _fmt(settings_obj.header_fully_approved_template), None
    if request_obj.status == Request.STATUS_PAYED:
        return _fmt(settings_obj.header_closed_template), None
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
    if approval.step_type == Approval.STEP_TYPE_NOTIFICATION:
        return True
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


def _expected_decision_footer(*, request_obj: Request, approval: Approval | None) -> str:
    """
    Для карточек в группе: кто должен нажать кнопку (согласование или подтверждение оплаты).
    Не дублируем строку, если решение уже принято или карточка только для чтения.
    """
    if approval is None:
        return ""
    if approval.decision != Approval.DECISION_PENDING:
        return ""
    if _telegram_card_should_be_readonly(request_obj=request_obj, approval=approval):
        return ""
    who = _display_user_name(approval.approver_user if approval.approver_user_id else None)
    if not who or who == "-":
        return ""
    return f"\n\n✍️ Сейчас ожидается решение от: <b>{escape(who)}</b>"


def _format_comments_indicator(*, request_obj: Request) -> str:
    total = RequestComment.objects.filter(request=request_obj).count()
    if total == 0:
        return ""
    last = (
        RequestComment.objects.filter(request=request_obj)
        .select_related("created_by")
        .order_by("-created_at")
        .first()
    )
    author = _display_user_name(getattr(last, "created_by", None)) if last else "-"
    excerpt = (last.body if last else "").strip().replace("\n", " ")
    if len(excerpt) > 120:
        excerpt = excerpt[:120].rstrip() + "…"
    return (
        f"\n\n💬 <b>Комментариев: {total}</b>\n"
        f"Последний от {escape(author)}:\n"
        f"<i>«{escape(excerpt)}»</i>"
    )


def build_approval_message(*, request_obj: Request, approval: Approval | None = None) -> str:
    header, subheader = _message_header(request_obj=request_obj, approval=approval)
    vendor_name = (request_obj.vendor_ref.name if request_obj.vendor_ref_id and request_obj.vendor_ref else request_obj.vendor) or "-"
    requester_name = _display_user_name(request_obj.requester if request_obj.requester_id else None)
    template = get_requests_messaging_gateway_settings(tenant=request_obj.tenant).message_template
    billing_month_escaped = escape(_format_billing_month(request_obj))
    # Already pre-escaped HTML — must not be re-escaped when interpolated.
    contract_block = _format_contract_block(request_obj)
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
        "contract_block": contract_block,
    }
    try:
        body = template.format_map(context)
    except Exception:
        logger.exception("Failed to render tenant telegram approvals template")
        # Safe fallback to keep sending operational.
        body = (
            f"<b>{context['header']}</b>\n"
            f"{context['subheader_block']}"
            f"Компания: {context['company_payer']}\n"
            f"Проект: {context['project_title']}\n\n"
            f"<b>💰 Финансы</b>\n"
            f"• Поставщик: {context['vendor']}\n"
            f"• Категория: {context['category']}\n"
            f"• Сумма: {context['amount']} {context['currency']}\n"
            f"• Тип оплаты: {context['payment_type']}"
            f"{context['contract_block']}\n\n"
            f"<b>📌 Назначение</b>\n"
            f"• Назначение платежа: {context['payment_purpose']}\n"
            f"• Описание: {context['description']}\n"
            f"• Месяц начисления: {context['billing_month']}\n\n"
            f"<b>⏱ Статус</b>\n"
            f"• Срочность: {context['urgency']}\n"
            f"• Заявитель: {context['requester']}\n\n"
            f"🕒 Подано: {context['submitted_at']}"
        )
    comments_block = _format_comments_indicator(request_obj=request_obj)
    return f"{body}{comments_block}{_expected_decision_footer(request_obj=request_obj, approval=approval)}"


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


def _resolve_comment_webapp_url(*, request_obj: Request) -> str:
    cfg = RequestApprovalConfig.objects.filter(tenant=request_obj.tenant).first()
    template = (cfg.comment_webapp_url if cfg else "") or ""
    if not template.strip():
        return ""
    u = template.strip()
    parts = urlsplit(u)
    host = (parts.hostname or "").lower()
    if host not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me"):
        return u
    pairs = list(parse_qsl(parts.query, keep_blank_values=True))
    if not any(k.lower() == "startapp" for k, _ in pairs):
        pairs.append(("startapp", f"req_{request_obj.pk}"))
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


def _buttons(*, approval: Approval) -> list[list[dict]]:
    """Build universal {label, value} / {label, url} button rows for the messaging gateway."""
    if approval.step_type == Approval.STEP_TYPE_NOTIFICATION:
        return []
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
                first_btn = {"label": "💰 Выплатить", "url": webapp_url}
            else:
                first_btn = {"label": "💰 Выплатить", "value": _button_data(approval=approval, decision="approved")}
        else:
            first_btn = {"label": "💰 Выплатить", "value": _button_data(approval=approval, decision="approved")}
        rows = [
            [
                first_btn,
                {"label": "❌ Отменить", "value": _button_data(approval=approval, decision="rejected")},
            ]
        ]
    else:
        rows = [
            [
                {"label": "✅Одобрить", "value": _button_data(approval=approval, decision="approved")},
                {"label": "❌ Отклонить", "value": _button_data(approval=approval, decision="rejected")},
            ]
        ]
    file_btns: list[dict] = []
    contract_url = build_contract_public_url(request_obj=approval.request)
    if contract_url:
        file_btns.append({"label": "📄 Договор", "url": contract_url})
    if RequestAttachment.objects.filter(request_id=approval.request_id).exists():
        attachments_url = build_request_draft_public_url(request_obj=approval.request)
        if attachments_url:
            file_btns.append({"label": "📎 Вложения", "url": attachments_url})
    if file_btns:
        rows.append(file_btns)
    comment_url = _resolve_comment_webapp_url(request_obj=approval.request)
    if comment_url:
        rows.append([{"label": "💬 Комментарии", "url": comment_url}])
    return rows
