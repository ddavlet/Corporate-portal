"""Telegram HTML text of the weekly investor report.

Character-for-character copy of buildText() in the n8n draft «invReportAllTnt1»:
any difference against the draft on the same data is a migration bug.
"""

from __future__ import annotations

import html
import logging
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from apps.modules.investments.investor_report import InvestorReport

logger = logging.getLogger(__name__)

NBSP = " "
MINUS = "−"
INDENT = NBSP * 6
TELEGRAM_TEXT_LIMIT = 4096

MONTHS = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]
MONTHS_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
TYPE_NAMES = {
    "дивиденды": "дивиденды",
    "проценты": "проценты",
    "доля_прибыли": "доля прибыли",
    "тело_инвестиций": "тело инвестиций",
}


def _num(value, digits: int = 0) -> str:
    """JS ``Number.toFixed`` (ties away from zero) + NBSP thousands + decimal comma + «−»."""
    v = Decimal(value or 0)
    rounded = abs(v).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    int_part, _, frac = format(rounded, "f").partition(".")
    sign = MINUS if v < 0 and rounded != 0 else ""
    grouped = f"{int(int_part):,}".replace(",", NBSP)
    return sign + grouped + ("," + frac if frac else "")


def _usd(value) -> str:
    return f"{_num(value)}{NBSP}$"


def _pct(value, digits: int = 1) -> str:
    return f"{_num(value, digits)}%"


def _pp(value, digits: int = 1) -> str:
    return f"{'+' if value > 0 else ''}{_num(value, digits)}{NBSP}п.п."


def _pending(value) -> str:
    return f" (+{_usd(value)} на согласовании)" if value > 0 else ""


def _js_round(value: Decimal) -> Decimal:
    """JS ``Math.round``: halves go up (towards +∞)."""
    return (value + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)


def _month_range(start: int, end: int) -> str:
    return MONTHS[start - 1] if start == end else f"{MONTHS[start - 1]}–{MONTHS[end - 1]}"


def _esc(value) -> str:
    return html.escape(str(value or ""), quote=False)


def _payout_lines(report: InvestorReport) -> list[str]:
    lines = []
    for p in report.last_payouts:
        period = f"за {MONTHS[p.billing_date.month - 1]}"
        if p.billing_date.year != report.year:
            period += f" {p.billing_date.year}"
        kind = TYPE_NAMES.get(p.type, p.type or "")
        line = f"{p.date:%d.%m} — {_usd(p.usd)} · {_esc(kind)} {period}"
        lines.append(line.replace("  ", " ", 1))
    return lines


def _render(report: InvestorReport, *, tenant_name: str, payout_lines: list[str]) -> str:
    y = report.year
    out = [
        f"📊 <b>{_esc(tenant_name)}</b> · {report.today:%d.%m.%Y}",
        "",
        f"💰 Вложено всего: <b>{_usd(report.invested)}</b>{_pending(report.invested_pending)}",
        f"💵 Выплачено всего: <b>{_usd(report.paid_total)}</b>{_pending(report.paid_pending)}",
        f"{INDENT}за {y} год: {_usd(report.paid_year)}",
    ]

    if report.has_yield:
        roi = report.annual_rate
        out.append("")
        out.append(f"📈 Доходность сейчас: {_pct(roi / 12, 2)} в мес. · <b>{_pct(roi)} годовых</b>")

        if report.annual_rate_without_last is not None:
            prev = report.annual_rate_without_last
            out.append(
                f"{INDENT}без учёта {MONTHS_GEN[report.skipped_month - 1]}: "
                f"{_pct(prev / 12, 2)} в мес. · <b>{_pct(prev)} годовых</b>"
            )

        target = report.target_annual_rate
        if target:
            diff = roi - target
            out.append(f"🎯 Целевая: {_pct(target / 12, 2)} в мес. · <b>{_pct(target)} годовых</b>")
            out.append(
                f"{'✅ Опережение' if diff >= 0 else '⚠️ Отставание'}: "
                f"{_pp(diff / 12, 2)} в мес. · <b>{_pp(diff)} годовых</b>"
            )

            gap = report.gap
            out.append("")
            out.append(f"📅 <b>По плану на сегодня</b> ({_month_range(report.start_month, report.last_month)}):")
            out.append(f"Должно быть выплачено: {_usd(report.planned)}")
            out.append(f"Выплачено: {_usd(report.paid_period)}")
            if _js_round(gap) > 0:
                out.append(f"🔻 Дефицит: <b>{_usd(gap)}</b>{_pending(report.paid_pending)}")
            else:
                out.append(f"🟢 Сверх плана: <b>{_usd(-gap)}</b>{_pending(report.paid_pending)}")
    elif report.invested > 0:
        out.extend(["", f"📈 Доходность: в {y} году ещё нет завершённых месяцев для расчёта"])

    if payout_lines:
        out.append("")
        out.append("🧾 <b>Последние выплаты:</b>")
        out.extend(payout_lines)

    return "\n".join(out)


def format_investor_report(report: InvestorReport, *, tenant_name: str) -> str:
    payout_lines = _payout_lines(report)
    text = _render(report, tenant_name=tenant_name, payout_lines=payout_lines)
    if len(text) <= TELEGRAM_TEXT_LIMIT:
        return text
    logger.error(
        "investor_report: text is %s chars (> %s) for %r, trimming «last payouts»",
        len(text), TELEGRAM_TEXT_LIMIT, tenant_name,
    )
    while payout_lines and len(text) > TELEGRAM_TEXT_LIMIT:
        payout_lines = payout_lines[:-1]
        text = _render(report, tenant_name=tenant_name, payout_lines=payout_lines)
    return text[:TELEGRAM_TEXT_LIMIT]
