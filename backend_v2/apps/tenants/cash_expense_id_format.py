"""Tenant-specific normalization for cashier (cash) expense `external_id` matching."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.tenants.models import Tenant

PREFIX_RE = re.compile(r"^[A-Za-z0-9_.-]{0,32}$")


def validate_cash_expense_external_id_prefix(value: str) -> str:
    s = "" if value is None else str(value).strip()
    if not PREFIX_RE.fullmatch(s):
        raise ValueError(
            "Префикс: до 32 символов — латинские буквы, цифры, «_», «-», «.». Оставьте пустым, если нужен только номер с нулями."
        )
    return s


def tenant_cash_expense_external_id_layout(tenant: Tenant) -> tuple[str, int]:
    p = getattr(tenant, "cash_expense_external_id_prefix", None)
    if p is None:
        p = "1-"
    prefix = "" if p is None else str(p).strip()

    raw_w = getattr(tenant, "cash_expense_external_id_digit_width", None)
    try:
        w = int(raw_w) if raw_w is not None else 9
    except (TypeError, ValueError):
        w = 9
    w = max(1, min(w, 32))
    return prefix, w


def format_canonical_cash_expense_external_id(*, tenant: Tenant, numeric: int) -> str:
    prefix, width = tenant_cash_expense_external_id_layout(tenant)
    return f"{prefix}{int(numeric):0{width}d}"


def cash_expense_external_id_match_candidates(raw: str, tenant: Tenant) -> list[str]:
    """
    Values to try against `CashExpense.external_id` for this tenant.

    Always includes the raw string (for non-numeric / legacy ids), plus plain and
    zero-padded numeric forms when the input can be parsed as such.
    """
    value = str(raw or "").strip()
    if not value:
        return []

    prefix, width = tenant_cash_expense_external_id_layout(tenant)
    candidates: list[str] = []

    def add(c: str) -> None:
        c = str(c).strip()
        if c and c not in candidates:
            candidates.append(c)

    add(value)

    numeric_part: int | None = None
    if value.isdigit():
        numeric_part = int(value)
    elif prefix and value.startswith(prefix):
        suffix = value[len(prefix) :]
        if suffix.isdigit():
            numeric_part = int(suffix)

    if numeric_part is None:
        return candidates

    plain = str(numeric_part)
    canonical = f"{prefix}{numeric_part:0{width}d}"
    for c in (plain, canonical):
        add(c)
    return candidates
