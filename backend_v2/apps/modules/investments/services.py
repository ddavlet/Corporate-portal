"""Investment module integrations (CBU rates, etc.)."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests

logger = logging.getLogger(__name__)

CBU_ARCHIVE_JSON_URL = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/"


class CbuRateFetchError(Exception):
    """Failed to load or parse CBU USD bulletin."""


def fetch_cbu_usd_uzs_rate(*, timeout: int = 12) -> Decimal:
    """
    Official CBU rate: UZS per 1 USD (Ccy USD, Nominal 1).

    Source: https://cbu.uz/ru/arkhiv-kursov-valyut/json/
    """
    try:
        resp = requests.get(CBU_ARCHIVE_JSON_URL, timeout=timeout)
        resp.raise_for_status()
        rows = resp.json()
    except (OSError, ValueError, requests.RequestException) as exc:
        logger.exception("CBU USD rate request failed")
        raise CbuRateFetchError("Не удалось получить курс USD с сайта ЦБ РУз.") from exc

    if not isinstance(rows, list):
        raise CbuRateFetchError("Неожиданный ответ ЦБ РУз (ожидался список курсов).")

    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("Ccy", "")).strip().upper() != "USD":
            continue
        try:
            nominal = Decimal(str(row.get("Nominal", "1")).replace(",", "."))
            rate = Decimal(str(row.get("Rate", "")).replace(",", "."))
        except (InvalidOperation, TypeError) as exc:
            raise CbuRateFetchError("Не удалось разобрать курс USD в ответе ЦБ РУз.") from exc
        if nominal <= 0:
            raise CbuRateFetchError("Некорректный номинал USD в ответе ЦБ РУз.")
        uzs_per_usd = (rate / nominal).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        return uzs_per_usd

    raise CbuRateFetchError("В ответе ЦБ РУз не найден курс USD.")
