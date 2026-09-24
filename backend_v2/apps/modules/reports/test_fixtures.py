"""Shared report data for statement tests (engine and API). Totals are worked out in test_statements.py."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from apps.modules.reports.ledger import LedgerEntry, build_ledger
from apps.modules.reports.services import finalize_report_payload
from apps.modules.requests.models import Request

TODAY = date(2026, 9, 23)
START_MONTH = "2025-01"
OPENING = Decimal("5000")


def _bank(item_id: str, day: str, amount: str, text: str) -> dict[str, Any]:
    return {"id": item_id, "date": day, "amount": amount, "category": "Поступление в банк",
            "purpose": "Поступление", "description": text, "source": "bank"}


def _request(item_id: str, day: str, amount: str, category: str, text: str, **extra: Any) -> dict[str, Any]:
    return {"id": item_id, "date": day, "amount": amount, "category": category, "purpose": category,
            "description": text, "source": "request", "request_id": item_id, "vendor": "ООО Поставщик", **extra}


def sample_raw_payload() -> dict[str, Any]:
    return {
        "revenue": [
            _bank("1", "2026-07-10", "1000.00", "Зачисление по реестру PAYME №1"),
            _bank("2", "2026-08-05", "1500.00", "CLICK: перечисление"),
            {"id": "3", "date": "2026-08-20T10:00:00+05:00", "amount": "300.00", "category": "Продажа",
             "purpose": "Продажа", "description": "Покупатель", "source": "cash"},
            _bank("4", "2026-09-10", "700.00", "Оплата от клиента"),
            _bank("5", "2025-08-15", "800.00", ""),
        ],
        "operational_expenses": [
            _request("10", "2026-08-01", "200.00", "Аренда", "Аренда за август"),
            _request("11", "2026-07-01", "100.00", "Маркетинг", "Выставка", period_index=1, periods=3),
            _request("11", "2026-08-01", "100.00", "Маркетинг", "Выставка", period_index=2, periods=3),
            _request("11", "2026-09-01", "100.00", "Маркетинг", "Выставка", period_index=3, periods=3),
            _request("12", "2025-08-10", "150.00", "Аренда", "Аренда за август 2025"),
        ],
        "other_expenses": [
            _request("20", "2026-08-25", "50.00", "Налоги", "НДС"),
        ],
        "invest_returns": [
            {"id": "30", "date": "2026-08-01", "amount": "120.00", "category": "Тело инвестиций",
             "purpose": "Тело инвестиций", "description": "Получатель: инвестор", "source": "invest_return"},
        ],
        "metadata": {"start_month": START_MONTH},
        "report_settings": {
            "start_month": START_MONTH,
            "opening_balance": str(OPENING),
            "cash_exclude_operations": [],
            "bank_exclude_purposes": ["Возврат займа"],
            "request_exclude_categories": [],
            "request_payment_types_for_pnl": [Request.PAYMENT_TYPE_TRANSFER],
            "payment_purpose_operational": ["Аренда", "Маркетинг"],
            "payment_purpose_other": ["Налоги"],
            "payment_purpose_invest_returns": [],
            "invest_return_type_operational": ["дивиденды", "проценты"],
            "invest_return_type_other": ["доля_прибыли"],
            "invest_return_type_invest_returns": ["тело_инвестиций"],
        },
    }


def sample_payload() -> dict[str, Any]:
    return finalize_report_payload(payload_obj=sample_raw_payload(), endpoint="/n8n/pnl-data", source="backend")


def sample_entries() -> list[LedgerEntry]:
    return build_ledger(sample_payload())
