"""Investment module integrations (CBU rates, etc.)."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

# Без даты в пути API отдаёт курсы прошлой недели, а не «на сегодня».
# Документация: .../json/all/YYYY-MM-DD/ — все валюты на дату.
CBU_JSON_BASE = "https://cbu.uz/ru/arkhiv-kursov-valyut/json"
UZ_TASHKENT = ZoneInfo("Asia/Tashkent")


class CbuRateFetchError(Exception):
    """Failed to load or parse CBU bulletin."""


def tashkent_today() -> date:
    """Текущая календарная дата в часовом поясе Ташкента (для даты курса при создании заявки)."""
    return timezone.now().astimezone(UZ_TASHKENT).date()


def clamp_rate_date_to_cbu_availability(*, requested: date) -> date:
    """В архиве ЦБ нет «будущих» дат — не выходим за сегодня по Ташкенту."""
    today = tashkent_today()
    if requested > today:
        return today
    return requested


def _cbu_rows_from_payload(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def fetch_cbu_rows_for_date(*, rate_date: date, timeout: int = 12) -> list[dict]:
    """Сырые строки бюллетеня ЦБ РУз на дату ``rate_date`` (UZS за Nominal единиц валюты)."""
    d = clamp_rate_date_to_cbu_availability(requested=rate_date)
    url = f"{CBU_JSON_BASE}/all/{d.isoformat()}/"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        rows = _cbu_rows_from_payload(resp.json())
    except (OSError, ValueError, requests.RequestException) as exc:
        logger.exception("CBU bulletin request failed for %s", url)
        raise CbuRateFetchError("Не удалось получить курсы с сайта ЦБ РУз.") from exc

    if not rows:
        raise CbuRateFetchError("Неожиданный ответ ЦБ РУз (ожидался список курсов).")
    return rows


def _parse_cbu_nominal_rate(row: dict) -> tuple[Decimal, Decimal]:
    nominal = Decimal(str(row.get("Nominal", "1")).replace(",", "."))
    rate = Decimal(str(row.get("Rate", "")).replace(",", "."))
    if nominal <= 0:
        raise CbuRateFetchError("Некорректный номинал валюты в ответе ЦБ РУз.")
    return nominal, rate


def usd_uzs_rate_from_cbu_rows(rows: list[dict]) -> Decimal:
    """UZS за 1 USD по строке USD в бюллетене."""
    for row in rows:
        if str(row.get("Ccy", "")).strip().upper() != "USD":
            continue
        try:
            nominal, rate = _parse_cbu_nominal_rate(row)
        except (InvalidOperation, TypeError) as exc:
            raise CbuRateFetchError("Не удалось разобрать курс USD в ответе ЦБ РУз.") from exc
        return (rate / nominal).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    raise CbuRateFetchError("В ответе ЦБ РУз не найден курс USD.")


def uzs_per_unit_for_currency_from_cbu_rows(rows: list[dict], currency: str) -> Decimal | None:
    """
    Сколько сум за 1 единицу валюты ``currency`` (с учётом Nominal в строке ЦБ).
    Для UZS возвращает 1 (сумма уже в сумах).
    """
    cur = str(currency or "").strip().upper()
    if cur == "UZS":
        return Decimal("1")
    for row in rows:
        if str(row.get("Ccy", "")).strip().upper() != cur:
            continue
        try:
            nominal, rate = _parse_cbu_nominal_rate(row)
        except (InvalidOperation, TypeError):
            return None
        return (rate / nominal).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return None


def invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin(
    *,
    sum_val: Decimal,
    currency: str,
    rows: list[dict],
) -> tuple[Decimal, Decimal]:
    """
    По бюллетеню ЦБ на одну дату: (cbu_usd_uzs_rate, sum_uzs).

    ``cbu_usd_uzs_rate`` — UZS за 1 USD; ``sum_uzs`` = sum * (UZS за единицу валюты выплаты).
    """
    usd_rate = usd_uzs_rate_from_cbu_rows(rows)
    mult = uzs_per_unit_for_currency_from_cbu_rows(rows, currency)
    if mult is None:
        raise CbuRateFetchError(f"В ответе ЦБ РУз не найдена валюта {str(currency or '').strip().upper()!r}.")
    sum_uzs = (sum_val * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return usd_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), sum_uzs


def fetch_cbu_usd_uzs_rate(*, rate_date: date, timeout: int = 12) -> Decimal:
    """
    Официальный курс ЦБ РУз: UZS за 1 USD на дату ``rate_date``.
    """
    rows = fetch_cbu_rows_for_date(rate_date=rate_date, timeout=timeout)
    return usd_uzs_rate_from_cbu_rows(rows)
