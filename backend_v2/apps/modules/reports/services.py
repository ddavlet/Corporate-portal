from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings

from apps.tenants.integration_settings import get_n8n_integration_settings


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_iso_date(raw: Any) -> datetime | None:
    if raw is None:
        return None
    value = str(raw).strip().replace('"', "")
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _extract_channel(purpose: str) -> str:
    text = purpose.upper()
    if "CLICK" in text:
        return "CLICK"
    if "PAYME" in text:
        return "PAYME"
    if "UZUM" in text:
        return "UZUM"
    if "UZCARD" in text:
        return "UZCARD"
    if "HUMO" in text:
        return "HUMO"
    if "IPS" in text:
        return "IPS"
    if "VISA" in text:
        return "VISA"
    if "ВЗНОС НА ЛИЦЕВОЙ СЧЕТ" in text:
        return "CASH_DEPOSIT"
    if "ОПЛАТА ОТ КЛИЕНТА" in text:
        return "CLIENT_PAYMENT"
    return "OTHER"


def _extract_category(item: dict[str, Any]) -> str:
    for key in ("category", "cathegory", "cat", "cat_name", "article", "item"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "Без категории"


def _normalize_rows(items: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        amount = _to_decimal(item.get("amount"))
        date = _parse_iso_date(item.get("date"))
        purpose = str(item.get("purpose") or "").strip()
        description = str(item.get("description") or "").strip()
        channel = _extract_channel(purpose)
        category = _extract_category(item)
        rows.append(
            {
                "id": str(item.get("id") or ""),
                "date": date.isoformat() if date else None,
                "amount": str(amount),
                "direction": direction,
                "category": category,
                "purpose": purpose,
                "description": description,
                "channel": channel,
                "raw": item,
            }
        )
    return rows


def _calc_monthly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"revenue": Decimal("0"), "expense": Decimal("0")})
    for row in rows:
        date_text = row.get("date")
        if not date_text:
            continue
        try:
            dt = datetime.fromisoformat(str(date_text).replace("Z", "+00:00"))
        except ValueError:
            continue
        key = dt.strftime("%Y-%m")
        amount = _to_decimal(row.get("amount"))
        if row.get("direction") == "revenue":
            monthly[key]["revenue"] += amount
        else:
            monthly[key]["expense"] += amount

    result: list[dict[str, Any]] = []
    for month in sorted(monthly.keys()):
        revenue = monthly[month]["revenue"]
        expense = monthly[month]["expense"]
        result.append(
            {
                "month": month,
                "revenue": str(revenue),
                "expense": str(expense),
                "net": str(revenue - expense),
            }
        )
    return result


def fetch_n8n_report_payload(*, tenant, user_id: int, endpoint: str, query_params: dict[str, Any]) -> dict[str, Any]:
    if not settings.BASE_DOMAIN:
        raise RuntimeError("BASE_DOMAIN is not configured.")
    token = get_n8n_integration_settings(tenant=tenant).integration_token
    if not token:
        token = (getattr(settings, "N8N_INTEGRATION_TOKEN", None) or "").strip()
    if not token:
        raise RuntimeError("N8N_INTEGRATION_TOKEN is not configured.")

    url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}/{endpoint.lstrip('/')}"
    response = requests.get(
        url,
        params=query_params,
        timeout=20,
        headers={
            "Accept": "application/json",
            "X-N8N-Integration-Token": token,
            "X-Tenant": tenant.subdomain,
            "X-User-Id": str(user_id),
        },
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        preview = (response.text or "")[:400].strip()
        raise ValueError(f"Invalid JSON from n8n. body_preview={preview!r}") from exc

    if isinstance(payload, list):
        payload_obj = payload[0] if payload else {}
    elif isinstance(payload, dict):
        payload_obj = payload
    else:
        payload_obj = {}

    revenue = payload_obj.get("revenue")
    expense = payload_obj.get("expense")
    metadata = payload_obj.get("metadata")
    if not isinstance(revenue, list):
        revenue = []
    if not isinstance(expense, list):
        expense = []
    if not isinstance(metadata, dict):
        metadata = {}

    revenue_rows = _normalize_rows(revenue, "revenue")
    expense_rows = _normalize_rows(expense, "expense")
    table_rows = sorted(
        revenue_rows + expense_rows,
        key=lambda row: (row.get("date") or "", row.get("id") or ""),
        reverse=True,
    )

    total_revenue = sum((_to_decimal(x.get("amount")) for x in revenue_rows), start=Decimal("0"))
    total_expense = sum((_to_decimal(x.get("amount")) for x in expense_rows), start=Decimal("0"))

    return {
        "metadata": {
            "company_name": metadata.get("company_name"),
            "start_month": metadata.get("start_month"),
            "source": "n8n",
            "endpoint": endpoint,
        },
        "totals": {
            "revenue": str(total_revenue),
            "expense": str(total_expense),
            "net": str(total_revenue - total_expense),
        },
        "monthly": _calc_monthly(table_rows),
        # Legacy-compatible fields for existing dashboard adapters.
        "revenue": revenue,
        "expense": expense,
        # Best-practice table payload.
        "rows": table_rows,
    }
