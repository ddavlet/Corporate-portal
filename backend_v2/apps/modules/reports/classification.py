"""Shared report vocabulary: ledger sections and payment-channel detection."""
from __future__ import annotations

SECTION_REVENUE = "revenue"
SECTION_OPERATIONAL = "operational"
SECTION_OTHER = "other"
SECTION_INVEST_RETURNS = "invest_returns"

# Order matters: the first phrase found wins.
CHANNEL_RULES: tuple[tuple[str, str], ...] = (
    ("CLICK", "CLICK"),
    ("PAYME", "PAYME"),
    ("UZUM", "UZUM"),
    ("UZCARD", "UZCARD"),
    ("HUMO", "HUMO"),
    ("IPS", "IPS"),
    ("VISA", "VISA"),
    ("ВЗНОС НА ЛИЦЕВОЙ СЧЕТ", "CASH_DEPOSIT"),
    ("ОПЛАТА ОТ КЛИЕНТА", "CLIENT_PAYMENT"),
)
CHANNEL_OTHER = "OTHER"


def extract_channel(*texts: str) -> str:
    """Payment channel from the first text that matches a rule (callers pass purpose first, then description)."""
    for text in texts:
        upper = str(text or "").upper()
        if not upper:
            continue
        for phrase, channel in CHANNEL_RULES:
            if phrase in upper:
                return channel
    return CHANNEL_OTHER
