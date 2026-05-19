"""Shared utilities for MCP tool handlers."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_safe(obj: Any) -> Any:
    """Recursively convert Django ORM values to JSON-serializable types.

    Django's .values() can return datetime, date, and Decimal objects which
    the standard json module cannot serialize. This normalises them to strings.
    """
    if isinstance(obj, list):
        return [json_safe(item) for item in obj]
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    # datetime must be checked before date (datetime is a subclass of date)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    return obj


def validate_date(value: str, field_name: str) -> None:
    """Raise ValueError if value is not a valid ISO date string (YYYY-MM-DD).

    Call this before passing user-supplied date strings to Django ORM filters
    to prevent internal error details from leaking to the caller.
    """
    if not value:
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"'{field_name}' must be a valid date in YYYY-MM-DD format, got: {value!r}")
