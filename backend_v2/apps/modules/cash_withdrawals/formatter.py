"""Telegram texts and buttons for cash-withdrawal receipts (pure functions, HTML parse mode)."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from html import escape

from django.utils import timezone

from apps.modules.telegram_approvals.formatter import build_request_draft_public_url

CALLBACK_PREFIX = "cwr:"
CONFIRM_BUTTON_LABEL = "✅ Деньги получены"
DENIED_TEXT = "Нет прав на подтверждение."

_KASSA_SUFFIX_RE = re.compile(r"\s*\(касса\)\s*$", re.IGNORECASE)


def format_money(amount) -> str:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return str(amount)
    if value == value.to_integral_value():
        return f"{value:,.0f}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ")


def wallet_label(wallet) -> str:
    register = getattr(wallet, "cash_register", None) if getattr(wallet, "cash_register_id", None) else None
    name = (getattr(register, "name", "") or "").strip()
    name = _KASSA_SUFFIX_RE.sub("", name).strip()
    return name or (wallet.currency or "Касса")


def short_user_name(user) -> str:
    if user is None:
        return "—"
    full = (getattr(user, "full_name", "") or "").strip()
    if not full:
        return getattr(user, "username", "") or "—"
    parts = full.split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[1][0]}."


def _names(users) -> str:
    names = [short_user_name(u) for u in users]
    return ", ".join(names) if names else "—"


def format_payed_date(request_obj) -> str:
    raw = getattr(request_obj, "payed_at", None)
    if not raw:
        return "—"
    s = str(raw)
    if len(s) != 8 or not s.isdigit():
        return "—"
    return f"{s[6:8]}.{s[4:6]}.{s[0:4]}"


def _request_ref(request_obj) -> str:
    label = f"Заявка №{request_obj.pk}"
    url = build_request_draft_public_url(request_obj=request_obj)
    ref = f'<a href="{escape(url)}">{label}</a>' if url else label
    purpose = (request_obj.payment_purpose or "").strip()
    return f"{ref} · {escape(purpose)}" if purpose else ref


def _amount(receipt) -> str:
    return f"{format_money(receipt.amount)} {escape(receipt.currency or '')}".strip()


def card_buttons(receipt) -> list[list[dict]]:
    return [[{"label": CONFIRM_BUTTON_LABEL, "value": f"{CALLBACK_PREFIX}{receipt.pk}"}]]


def _pending_text(receipt, confirmers) -> str:
    request_obj = receipt.request
    lines = [
        "💸 <b>Ожидается поступление в кассу</b>",
        "",
        f"Сумма: <b>{_amount(receipt)}</b>",
        f"Касса: {escape(wallet_label(receipt.wallet))}",
        _request_ref(request_obj),
    ]
    comment = (request_obj.description or "").strip()
    if comment:
        lines.append(f"Комментарий: {escape(comment)}")
    lines += ["", f"Подтвердить могут: {escape(_names(confirmers))}"]
    return "\n".join(lines)


def _confirmed_text(receipt) -> str:
    when = timezone.localtime(receipt.confirmed_at).strftime("%d.%m.%Y %H:%M") if receipt.confirmed_at else "—"
    return "\n".join(
        [
            "✅ <b>Поступило в кассу</b>",
            f"{_amount(receipt)} → {escape(wallet_label(receipt.wallet))}",
            f"Подтвердил: {escape(short_user_name(receipt.confirmed_by))} · {when}",
            _request_ref(receipt.request),
        ]
    )


def _closed_text(receipt) -> str:
    return "\n".join(
        [
            "⛔ <b>Закрыто без дохода</b>",
            f"{_amount(receipt)} · {_request_ref(receipt.request)}",
            f"Причина: {escape(receipt.closed_comment or '—')}",
        ]
    )


def build_card_text(*, receipt, confirmers: list) -> str:
    from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt

    if receipt.status == CashWithdrawalReceipt.Status.CONFIRMED:
        return _confirmed_text(receipt)
    if receipt.status == CashWithdrawalReceipt.Status.CLOSED:
        return _closed_text(receipt)
    return _pending_text(receipt, confirmers)


def build_alert_text(*, receipt, days: int, responsible: list) -> str:
    request_obj = receipt.request
    purpose = (request_obj.payment_purpose or "").strip()
    purpose_part = f" ({escape(purpose)})" if purpose else ""
    url = build_request_draft_public_url(request_obj=request_obj)
    ref = f'<a href="{escape(url)}">Заявка №{request_obj.pk}</a>' if url else f"Заявка №{request_obj.pk}"
    return "\n".join(
        [
            f"⚠️ <b>Деньги не оприходованы в кассу — {days} дн.</b>",
            "",
            f"{ref} оплачена {format_payed_date(request_obj)}{purpose_part}",
            f"Сумма: {_amount(receipt)} → {escape(wallet_label(receipt.wallet))}",
            "Дохода в кассе нет — никто не подтвердил получение.",
            "",
            f"Проверьте, поступили ли деньги, и нажмите «{CONFIRM_BUTTON_LABEL}» в исходной карточке.",
            f"Ответственные: {escape(_names(responsible))}",
        ]
    )


def build_currency_mismatch_text(*, request_obj, wallet) -> str:
    purpose = (request_obj.payment_purpose or "").strip()
    return (
        f"⚠️ Заявка №{request_obj.pk} ({escape(purpose)}): валюта {escape(request_obj.currency or '')} "
        f"не совпадает с кассой «{escape(wallet_label(wallet))}» ({escape(wallet.currency or '')}). "
        "Ожидание не создано — проверьте правило в настройках."
    )
