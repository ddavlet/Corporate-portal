"""Tenant-specific normalization for payroll document `doc_id` matching."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.tenants.cash_expense_id_format import (
    expense_doc_match_candidates,
    validate_cash_expense_external_id_prefix,
)

if TYPE_CHECKING:
    from apps.tenants.models import Tenant


def validate_payroll_doc_id_prefix(value: str) -> str:
    return validate_cash_expense_external_id_prefix(value)


def tenant_payroll_doc_id_layout(tenant: Tenant) -> tuple[str, int]:
    p = getattr(tenant, "payroll_doc_id_prefix", None)
    prefix = str(p).strip() if p is not None else "1-"

    raw_w = getattr(tenant, "payroll_doc_id_digit_width", None)
    try:
        w = int(raw_w) if raw_w is not None else 9
    except (TypeError, ValueError):
        w = 9
    w = max(1, min(w, 32))
    return prefix, w


def format_canonical_payroll_doc_id(*, tenant: Tenant, numeric: int) -> str:
    prefix, width = tenant_payroll_doc_id_layout(tenant)
    return f"{prefix}{int(numeric):0{width}d}"


def payroll_doc_id_match_candidates(raw: str, tenant: Tenant) -> list[str]:
    """Values to try against `PayrollDocument.doc_id` for this tenant."""
    prefix, width = tenant_payroll_doc_id_layout(tenant)
    return expense_doc_match_candidates(raw, prefix=prefix, width=width)
