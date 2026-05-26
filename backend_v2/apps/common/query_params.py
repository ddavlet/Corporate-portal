from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError


def parse_bool_query(request, key: str) -> bool | None:
    raw = (request.query_params.get(key) or "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    raise ValidationError({key: "Use one of: 1, true, yes, 0, false, no."})


def parse_date_query(request, key: str) -> date | None:
    raw = (request.query_params.get(key) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError({key: "Use YYYY-MM-DD format."}) from exc


def parse_decimal_query(request, key: str) -> Decimal | None:
    raw = (request.query_params.get(key) or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({key: "Invalid decimal value."}) from exc


def parse_int_query(request, key: str) -> int | None:
    raw = (request.query_params.get(key) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({key: "Invalid integer value."}) from exc
