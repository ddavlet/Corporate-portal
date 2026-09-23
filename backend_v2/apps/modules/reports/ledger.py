"""Report payload → flat ledger entries: one entry per transaction line, tagged with its section."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

from apps.modules.reports.classification import (
    SECTION_INVEST_RETURNS,
    SECTION_OPERATIONAL,
    SECTION_OTHER,
    SECTION_REVENUE,
    extract_channel,
)

logger = logging.getLogger(__name__)
_WHITESPACE = re.compile(r"\s+")

SOURCE_BANK = "bank"
SOURCE_CASH = "cash"
SOURCE_REQUEST = "request"
SOURCE_INVEST_RETURN = "invest_return"
SOURCE_UNKNOWN = "unknown"
_KNOWN_SOURCES = frozenset({SOURCE_BANK, SOURCE_CASH, SOURCE_REQUEST, SOURCE_INVEST_RETURN})

UNCATEGORIZED = "Без категории"

_PAYLOAD_BLOCKS: tuple[tuple[str, str], ...] = (
    (SECTION_REVENUE, "revenue"),
    (SECTION_OPERATIONAL, "operational_expenses"),
    (SECTION_OTHER, "other_expenses"),
    (SECTION_INVEST_RETURNS, "invest_returns"),
)
_CATEGORY_KEYS = ("category", "cathegory", "cat", "cat_name", "article", "item")


@dataclass(frozen=True)
class LedgerEntry:
    entry_id: str
    section: str
    source: str
    date: date
    amount: Decimal
    category: str
    title: str
    counterparty: str
    request_id: int | None
    channel: str
    amortization_index: int | None
    amortization_count: int | None


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _parse_amount(raw: Any) -> Decimal | None:
    text = _WHITESPACE.sub("", _text(raw)).replace(",", ".")
    if not text:
        return None
    try:
        return abs(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(raw: Any) -> date | None:
    text = _text(raw).strip('"')
    if not text:
        return None
    if len(text) == 10:
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_aware(parsed):
        parsed = timezone.localtime(parsed, timezone.get_default_timezone())
    return parsed.date()


def _parse_int(raw: Any) -> int | None:
    text = _text(raw)
    return int(text) if text.isdigit() else None


def _category(item: dict[str, Any]) -> str:
    for key in _CATEGORY_KEYS:
        value = _text(item.get(key))
        if value:
            return value
    return UNCATEGORIZED


def _title_and_counterparty(source: str, item: dict[str, Any], category: str) -> tuple[str, str]:
    purpose = _text(item.get("purpose"))
    description = _text(item.get("description"))
    if source == SOURCE_CASH:
        return purpose or category, description
    if source == SOURCE_REQUEST:
        return description or purpose or category, _text(item.get("vendor"))
    if source == SOURCE_INVEST_RETURN:
        return purpose or category, description
    return description or purpose or category, ""


def build_ledger(payload: dict[str, Any]) -> list[LedgerEntry]:
    entries: list[LedgerEntry] = []
    seen: dict[str, int] = {}
    total = 0
    skipped: list[str] = []
    for section, block in _PAYLOAD_BLOCKS:
        items = payload.get(block)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            total += 1
            entry_date = _parse_date(item.get("date"))
            amount = _parse_amount(item.get("amount"))
            if entry_date is None or amount is None:
                skipped.append(f"{section}:{_text(item.get('id'))}")
                continue
            source = _text(item.get("source"))
            if source not in _KNOWN_SOURCES:
                source = SOURCE_UNKNOWN
            category = _category(item)
            title, counterparty = _title_and_counterparty(source, item, category)
            period_index = _parse_int(item.get("period_index"))
            base_id = f"{section}:{source}:{_text(item.get('id'))}:{period_index or 0}"
            duplicates = seen.get(base_id, 0)
            seen[base_id] = duplicates + 1
            request_id = _parse_int(item.get("request_id"))
            if request_id is None and source == SOURCE_REQUEST:
                request_id = _parse_int(item.get("id"))
            channel = ""
            if section == SECTION_REVENUE and source in (SOURCE_BANK, SOURCE_UNKNOWN):
                channel = extract_channel(item.get("purpose"), item.get("description"))
            entries.append(
                LedgerEntry(
                    entry_id=base_id if duplicates == 0 else f"{base_id}#{duplicates}",
                    section=section,
                    source=source,
                    date=entry_date,
                    amount=amount,
                    category=category,
                    title=title,
                    counterparty=counterparty,
                    request_id=request_id,
                    channel=channel,
                    amortization_index=period_index,
                    amortization_count=_parse_int(item.get("periods")),
                )
            )
    if skipped:
        logger.warning(
            "reports ledger skipped %s of %s rows with an unreadable date or amount: %s",
            len(skipped),
            total,
            ", ".join(skipped[:10]),
        )
    return entries
