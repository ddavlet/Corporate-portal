"""Report rules in plain Russian, for the «Как считается» panel and the Excel settings sheet."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.modules.investments.models import InvestReturn
from apps.modules.reports.periods import is_month_key

MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def _quoted(values: list[str]) -> str:
    return ", ".join(f"«{value}»" for value in values)


def _amount(raw: Any) -> str:
    try:
        value = Decimal(str(raw if raw is not None else "0"))
    except (InvalidOperation, ValueError):
        value = Decimal("0")
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _list(cfg: dict[str, Any], key: str) -> list[str]:
    raw = cfg.get(key)
    return [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []


def _bucket_text(cfg: dict[str, Any], purpose_key: str, type_key: str) -> str:
    type_labels = dict(InvestReturn.ReturnType.choices)
    purposes = _list(cfg, purpose_key)
    types = [type_labels.get(value, value) for value in _list(cfg, type_key)]
    parts = [f"назначения платежа {_quoted(purposes)}" if purposes else "назначения платежа не выбраны"]
    if types:
        parts.append(f"выплаты инвесторам типа {_quoted(types)}")
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."


def build_methodology(
    *, report: str, report_settings: dict[str, Any] | None, source: str, generated_at: datetime
) -> list[dict[str, str]]:
    cfg = report_settings if isinstance(report_settings, dict) else {}
    rules: list[dict[str, str]] = []
    start = str(cfg.get("start_month") or "")
    if is_month_key(start):
        year, month = start.split("-")
        rules.append({"label": "Период отчёта", "text": f"с {MONTHS_GENITIVE[int(month) - 1]} {year} года"})
        rules.append(
            {"label": "Начальный остаток", "text": f"{_amount(cfg.get('opening_balance'))} сум на 01.{month}.{year}"}
        )
    if cfg:
        if report == "pnl":
            bank = "Все поступления на расчётный счёт."
            if _list(cfg, "bank_exclude_purposes"):
                bank += (
                    " Не учитываются поступления, в назначении которых есть: "
                    f"{_quoted(_list(cfg, 'bank_exclude_purposes'))}."
                )
        else:
            bank = "Все поступления на расчётный счёт, без исключений."
        rules.append({"label": "Выручка: банк", "text": bank})
        cash = "Подтверждённые кассовые операции."
        if _list(cfg, "cash_exclude_operations"):
            cash += f" Не учитываются операции: {_quoted(_list(cfg, 'cash_exclude_operations'))}."
        rules.append({"label": "Выручка: касса", "text": cash})
        pay_types = _list(cfg, "request_payment_types_for_pnl")
        if pay_types:
            expenses = f"Оплаченные заявки с типами оплаты: {_quoted(pay_types)}."
        else:
            expenses = "Типы оплаты заявок не выбраны — расходы из заявок не учитываются."
        if _list(cfg, "request_exclude_categories"):
            expenses += f" Не учитываются категории: {_quoted(_list(cfg, 'request_exclude_categories'))}."
        rules.append({"label": "Расходы", "text": expenses})
        rules.append(
            {"label": "Операционные", "text": _bucket_text(cfg, "payment_purpose_operational", "invest_return_type_operational")}
        )
        rules.append({"label": "Прочие", "text": _bucket_text(cfg, "payment_purpose_other", "invest_return_type_other")})
        rules.append(
            {
                "label": "Выплаты инвесторам",
                "text": _bucket_text(cfg, "payment_purpose_invest_returns", "invest_return_type_invest_returns"),
            }
        )
        rules.append(
            {
                "label": "Дата расхода",
                "text": (
                    "Месяц начисления заявки; заявки с амортизацией делятся по месяцам графика."
                    if report == "pnl"
                    else "Дата фактической оплаты; амортизация не применяется."
                ),
            }
        )
    else:
        rules.append({"label": "Правила", "text": "Правила отчёта задаются в сценарии n8n."})
    origin = "данные системы" if source == "backend" else "сценарий n8n"
    rules.append({"label": "Источник данных", "text": f"{origin} · сформировано {generated_at:%d.%m.%Y %H:%M}"})
    return rules
