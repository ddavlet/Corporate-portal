"""Telegram text for a paid «Пополнение» request (pure function, HTML parse mode, as in n8n Neuron)."""

from __future__ import annotations

from html import escape

from apps.modules.cash_desk.formatter import _date, _text_or_dash
from apps.modules.cash_withdrawals.formatter import format_money

MOVEMENT_LABEL = "Пополнение корпоративной карты"


def build_card_topup_text(*, request_obj, card: dict | None) -> str:
    """`card` is {"name", "current_balance", "currency"} or None when the tenant has no corporate card."""
    currency = escape(request_obj.currency or "")
    lines = [
        "💰 <b>Движение денежных средств</b>",
        "",
        f"🆔 <b>ID:</b> {request_obj.pk}",
        f"📅 <b>Дата:</b> {_date(request_obj)}",
        f"🔄 <b>Вид движения:</b> {MOVEMENT_LABEL}",
        "",
        f"💵 <b>Сумма:</b> <code>{format_money(request_obj.amount)} {currency}</code>",
        "",
        "📝 <b>Назначение платежа:</b>",
        _text_or_dash(request_obj.payment_purpose),
        f"👤 <b>Получатель:</b> {_text_or_dash(request_obj.vendor)}",
        "💬 <b>Комментарий:</b>",
        _text_or_dash(request_obj.description),
        "",
        f"💳 <b>Категория:</b> {_text_or_dash(request_obj.category)}",
        f"🏢 <b>Плательщик:</b> {_text_or_dash(request_obj.company_payer)}",
    ]
    if card is not None:
        balance = f"{format_money(card.get('current_balance'))} {escape(card.get('currency') or '')}".strip()
        lines += [
            "",
            f"💳 <b>Карта:</b> {_text_or_dash(card.get('name'))}",
            f"💰 <b>Остаток на карте:</b> <code>{balance}</code>",
        ]
    return "\n".join(lines)
