"""Parse bank doc_date / process_date: YYYY-MM-DD or ISO 8601 datetime → date in Asia/Tashkent."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from rest_framework import serializers

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")
UTC = timezone.utc


def _string_looks_like_datetime(s: str) -> bool:
    t = s.strip()
    if not t:
        return False
    if "T" in t or t.endswith("Z"):
        return True
    if " " in t and len(t) > 10:
        return True
    # e.g. ...+05:00 or ...-05:00 at end
    for sep in ("+", "-"):
        idx = t.rfind(sep)
        if idx > 10 and ":" in t[idx:]:
            return True
    return False


def doc_date_candidates_for_composite_lookup(raw) -> list[date]:
    """
    Dates to try when matching BankExpense unique (doc_no, doc_date, debit_turnover, payment_purpose).

    Rows may have been stored with a plain YYYY-MM-DD while clients send ISO datetimes that normalize
    to the next calendar day in Asia/Tashkent — include legacy «date prefix» and UTC calendar day.
    Order: canonical Tashkent first (new rows), then prefix / UTC (legacy / bank statement date).
    """
    if raw in (None, ""):
        return []

    out: list[date] = []
    seen: set[date] = set()

    def add(d: date) -> None:
        if d not in seen:
            seen.add(d)
            out.append(d)

    if isinstance(raw, str):
        s = raw.strip()
        add(coerce_input_to_tashkent_date(s))
        if _string_looks_like_datetime(s) and len(s) >= 10 and s[4] == "-" and s[7] == "-":
            try:
                add(date.fromisoformat(s[:10]))
            except ValueError:
                pass
            try:
                s_parse = s[:-1] + "+00:00" if s.endswith("Z") else s
                dt = datetime.fromisoformat(s_parse)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TASHKENT_TZ)
                add(dt.astimezone(UTC).date())
            except ValueError:
                pass
    elif isinstance(raw, datetime):
        add(coerce_input_to_tashkent_date(raw))
        dt = raw
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TASHKENT_TZ)
        add(dt.astimezone(UTC).date())
    elif isinstance(raw, date):
        add(raw)
    return out


def _parse_date_string(s: str) -> date:
    s = s.strip()
    if not s:
        raise ValueError("Empty date string.")

    # Literal calendar day only (no time component in the string shape we treat as date-only).
    if len(s) == 10 and s[4] == "-" and s[7] == "-" and "T" not in s and " " not in s:
        return date.fromisoformat(s)

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError("Use YYYY-MM-DD or ISO 8601 datetime.") from exc

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TASHKENT_TZ)
    else:
        dt = dt.astimezone(TASHKENT_TZ)
    return dt.date()


def coerce_input_to_tashkent_date(value):
    """
    Accept date, datetime, or str (YYYY-MM-DD or ISO datetime with optional Z/offset).
    Date-only strings are not shifted; datetimes are converted to calendar date in Asia/Tashkent.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TASHKENT_TZ)
        else:
            dt = dt.astimezone(TASHKENT_TZ)
        return dt.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return _parse_date_string(value)
    raise TypeError(f"Unsupported type for date: {type(value).__name__}")


class TashkentFlexibleDateField(serializers.DateField):
    """Like DateField but accepts ISO 8601 datetimes; normalizes to date in Asia/Tashkent."""

    def to_internal_value(self, value):
        if value in (None, ""):
            return super().to_internal_value(value)
        try:
            return coerce_input_to_tashkent_date(value)
        except (ValueError, TypeError) as exc:
            raise serializers.ValidationError(str(exc)) from exc
