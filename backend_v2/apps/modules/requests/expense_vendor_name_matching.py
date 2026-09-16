"""
Generalized vendor free-text -> Vendor directory resolution, used as a
fallback by expense_reconciliation_core when a request has no vendor_ref
but does have a free-text `vendor` value. Originally written as a
Lemonfit Aqua-only one-off (see git history of the now-removed
lemonaqua_transfer_bank_expense_name_matching.py); generalized here to
work for any tenant/vendor kind.
"""

from __future__ import annotations

import re
from collections import defaultdict

from apps.modules.vendors.models import Vendor

_LEGAL_ENTITY_TOKENS = {
    "MCHJ", "OOO", "ООО", "XK", "ХК", "QK", "AJ", "АЖ", "IP", "ИП", "ЧП", "ЯТТ",
}
_QUOTE_CHARS = str.maketrans("", "", "\"'«»`")


def normalize_vendor_name(value: str) -> str:
    """Uppercase, drop quotes and legal-entity suffix tokens, collapse whitespace."""
    value = (value or "").translate(_QUOTE_CHARS).upper()
    value = re.sub(r"[.,]", " ", value)
    tokens = [t for t in re.split(r"\s+", value) if t and t not in _LEGAL_ENTITY_TOKENS]
    return " ".join(tokens)


def build_vendor_name_index(*, tenant_id: int, kind: str) -> dict[str, list[int]]:
    """Normalized vendor name -> list of vendor ids sharing that normalized name."""
    index: dict[str, list[int]] = defaultdict(list)
    for vendor_id, name in Vendor.objects.filter(tenant_id=tenant_id, kind=kind).values_list("id", "name"):
        index[normalize_vendor_name(name)].append(vendor_id)
    return dict(index)


def resolve_vendor_id_from_index(free_text_name: str, index: dict[str, list[int]]) -> int | None:
    """Returns the vendor id only when exactly one vendor's normalized name matches. Never guesses."""
    normalized = normalize_vendor_name(free_text_name)
    if not normalized:
        return None
    vendor_ids = index.get(normalized)
    if vendor_ids and len(vendor_ids) == 1:
        return vendor_ids[0]
    return None
