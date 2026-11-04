"""Расчёт стоимости обращения к модели по ценам из config.MODEL_PRICES_USD_PER_MTOK."""

import logging
from decimal import Decimal

from .config import MODEL_PRICES_USD_PER_MTOK

logger = logging.getLogger(__name__)

_MTOK = Decimal(1_000_000)
_QUANT = Decimal("0.000001")


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> Decimal:
    """Стоимость в USD; для модели без цены — Decimal("0") и предупреждение в лог."""
    prices = MODEL_PRICES_USD_PER_MTOK.get(model)
    if prices is None:
        logger.warning("ai_assistant pricing: no price for model=%s, cost counted as 0", model)
        return Decimal("0")
    total = (
        Decimal(int(input_tokens or 0)) * Decimal(prices["input"])
        + Decimal(int(output_tokens or 0)) * Decimal(prices["output"])
        + Decimal(int(cache_read_tokens or 0)) * Decimal(prices["cache_read"])
        + Decimal(int(cache_creation_tokens or 0)) * Decimal(prices["cache_write"])
    ) / _MTOK
    return total.quantize(_QUANT)
