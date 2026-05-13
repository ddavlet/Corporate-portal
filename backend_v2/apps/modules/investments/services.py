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
    """Failed to load or parse CBU USD bulletin."""


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


def fetch_cbu_usd_uzs_rate(*, rate_date: date, timeout: int = 12) -> Decimal:
    """
    Официальный курс ЦБ РУз: сум за 1 USD (Ccy USD, с учётом Nominal).

    Запрос по конкретной дате: ``/json/all/YYYY-MM-DD/``
    (без даты в URL ответ относится к прошлой неделе, не к нужному дню).
    """
    d = clamp_rate_date_to_cbu_availability(requested=rate_date)
    url = f"{CBU_JSON_BASE}/all/{d.isoformat()}/"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        rows = _cbu_rows_from_payload(resp.json())
    except (OSError, ValueError, requests.RequestException) as exc:
        logger.exception("CBU USD rate request failed for %s", url)
        raise CbuRateFetchError("Не удалось получить курс USD с сайта ЦБ РУз.") from exc

    if not rows:
        raise CbuRateFetchError("Неожиданный ответ ЦБ РУз (ожидался список курсов).")

    for row in rows:
        if str(row.get("Ccy", "")).strip().upper() != "USD":
            continue
        try:
            nominal = Decimal(str(row.get("Nominal", "1")).replace(",", "."))
            rate = Decimal(str(row.get("Rate", "")).replace(",", "."))
        except (InvalidOperation, TypeError) as exc:
            raise CbuRateFetchError("Не удалось разобрать курс USD в ответе ЦБ РУз.") from exc
        if nominal <= 0:
            raise CbuRateFetchError("Некорректный номинал USD в ответе ЦБ РУз.")
        return (rate / nominal).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    raise CbuRateFetchError("В ответе ЦБ РУз не найден курс USD.")
