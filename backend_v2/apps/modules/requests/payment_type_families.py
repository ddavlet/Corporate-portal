"""Семейства типов заявок: инвест-типы ведут себя как наличные / перечисление."""
from __future__ import annotations

from typing import Iterable

from apps.modules.requests.models import Request

INVEST_PAYMENT_TYPES: tuple[str, str] = (
    Request.PAYMENT_TYPE_INVEST_CASH,
    Request.PAYMENT_TYPE_INVEST_TRANSFER,
)

_CANONICAL = {
    Request.PAYMENT_TYPE_INVEST_CASH: Request.PAYMENT_TYPE_CASH,
    Request.PAYMENT_TYPE_INVEST_TRANSFER: Request.PAYMENT_TYPE_TRANSFER,
}


def canonical_payment_type(payment_type: str) -> str:
    """Инвест-тип -> родительский тип; остальные значения без изменений."""
    return _CANONICAL.get(payment_type, payment_type)


def cash_like_payment_types() -> tuple[str, ...]:
    return (Request.PAYMENT_TYPE_CASH, Request.PAYMENT_TYPE_INVEST_CASH)


def bank_like_payment_types() -> tuple[str, ...]:
    return (
        Request.PAYMENT_TYPE_TRANSFER,
        Request.PAYMENT_TYPE_TOPUP,
        Request.PAYMENT_TYPE_INVEST_TRANSFER,
    )


def expand_with_invest_types(payment_types: Iterable[str]) -> list[str]:
    """Сохраняет порядок; добавляет инвест-типы к «Наличные»/«Перечисление» без дублей."""
    result: list[str] = []
    for pt in payment_types:
        if pt not in result:
            result.append(pt)
    for parent, invest in (
        (Request.PAYMENT_TYPE_CASH, Request.PAYMENT_TYPE_INVEST_CASH),
        (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_INVEST_TRANSFER),
    ):
        if parent in result and invest not in result:
            result.append(invest)
    return result
