"""Telegram text «Движение денежных средств» (pure function, HTML parse mode)."""

from __future__ import annotations

from html import escape

from apps.modules.cash_desk.models import CashDeskMessage
from apps.modules.cash_withdrawals.formatter import _KASSA_SUFFIX_RE, format_money, format_payed_date, wallet_label

_KIND_LABELS = {
    CashDeskMessage.Kind.EXPENSE: "Расход",
    CashDeskMessage.Kind.TRANSFER: "Перемещение",
}


def _text_or_dash(value) -> str:
    value = (str(value) if value is not None else "").strip()
    return escape(value) if value else "—"


def _date(request_obj) -> str:
    value = format_payed_date(request_obj)
    if value == "—":
        billing = getattr(request_obj, "billing_date", None)
        if billing:
            return billing.strftime("%d.%m.%Y")
    return value


def _balance_name(row: dict) -> str:
    name = _KASSA_SUFFIX_RE.sub("", (row.get("display_name") or "").strip()).strip()
    return escape(name)


def build_movement_text(
    *, request_obj, kind: str, from_wallet, destination, balances: list[dict], revenue_error: str | None = None
) -> str:
    kind_label = _KIND_LABELS.get(kind, _KIND_LABELS[CashDeskMessage.Kind.EXPENSE])
    register = escape(wallet_label(from_wallet))
    if kind == CashDeskMessage.Kind.TRANSFER and destination is not None:
        register = f"{register} → {escape(wallet_label(destination.wallet))}"

    currency = escape(request_obj.currency or "")
    lines = [
        "💰 <b>Движение денежных средств</b>",
        "",
        f"🆔 <b>ID:</b> {request_obj.pk}",
        f"📅 <b>Дата:</b> {_date(request_obj)}",
        f"🔄 <b>Вид движения:</b> {kind_label}",
        f"🏦 <b>Касса:</b> {register}",
    ]
    if revenue_error:
        lines.append(f"⚠️ <b>Приход в кассу-получатель не создан:</b> {escape(revenue_error)}")
    lines += [
        "",
        f"💵 <b>Сумма:</b> <code>{format_money(request_obj.amount)} {currency}</code>",
    ]
    if (
        kind == CashDeskMessage.Kind.TRANSFER
        and destination is not None
        and destination.currency != request_obj.currency
    ):
        lines.append(
            f"💱 <b>Зачислено:</b> <code>{format_money(destination.amount)} {escape(destination.currency or '')}</code>"
        )
    lines += [
        "",
        "📝 <b>Назначение платежа:</b>",
        _text_or_dash(request_obj.payment_purpose),
        f"👤 <b>Получатель:</b> {_text_or_dash(request_obj.vendor)}",
        "💬 <b>Комментарий:</b>",
        _text_or_dash(request_obj.description),
        "",
        f"💳 <b>Категория:</b> {_text_or_dash(request_obj.category)}",
        f"🏢 <b>Плательщик:</b> {_text_or_dash(request_obj.company_payer)}",
        "",
        "📊 <b>Остатки по всем кассам:</b>",
    ]

    affected = {from_wallet.id}
    if destination is not None:
        affected.add(destination.wallet.id)
    for row in balances:
        is_affected = row.get("wallet_id") in affected
        if not row.get("anchor_is_active") and not is_affected:
            continue
        text = f"{_balance_name(row)}: {format_money(row.get('current_balance'))} {escape(row.get('currency') or '')}"
        lines.append(f"👉 <b>{text}</b>" if is_affected else f"🏦 {text}")
    return "\n".join(lines)
