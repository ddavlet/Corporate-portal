from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
import hashlib
import json

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.modules.reports.models import TenantReportSettings
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
            if timezone.is_aware(dt):
                dt = timezone.localtime(dt, timezone=timezone.get_default_timezone())
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


def _reports_cache_key(
    *,
    tenant_subdomain: str,
    user_id: int,
    endpoint: str,
    query_params: dict[str, Any],
    payload_source: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "tenant": tenant_subdomain,
            "user_id": user_id,
            "endpoint": endpoint,
            "query_params": query_params,
            "payload_source": payload_source,
        },
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"reports:payload:{digest}"


def _is_pnl_endpoint(endpoint: str) -> bool:
    ep = endpoint.lstrip("/").lower()
    return ep.endswith("pnl-data") or ep.endswith("n8n/pnl-data")


def _is_cashflow_endpoint(endpoint: str) -> bool:
    ep = endpoint.lstrip("/").lower()
    return ep.endswith("cashflow-data") or ep.endswith("n8n/cashflow-data")


def resolve_pnl_source_for_tenant(*, tenant) -> str:
    """
    Resolve per-tenant PnL source from TenantReportSettings.
    For non-model test doubles (without id), fallback to n8n.
    """
    tenant_id = getattr(tenant, "id", None)
    if not tenant_id:
        return TenantReportSettings.PNL_SOURCE_N8N
    try:
        row = TenantReportSettings.objects.only("pnl_source").get(tenant_id=tenant_id)
    except TenantReportSettings.DoesNotExist as exc:
        raise RuntimeError(f"No tenant_report_settings for tenant_id={tenant_id}") from exc
    source = (row.pnl_source or "").strip().lower()
    if source not in {TenantReportSettings.PNL_SOURCE_N8N, TenantReportSettings.PNL_SOURCE_BACKEND}:
        raise RuntimeError(f"Invalid pnl_source={source!r} for tenant_id={tenant_id}")
    return source


def resolve_cashflow_source_for_tenant(*, tenant) -> str:
    """
    Resolve per-tenant Cashflow source from TenantReportSettings.
    For non-model test doubles (without id), fallback to n8n.
    """
    tenant_id = getattr(tenant, "id", None)
    if not tenant_id:
        return TenantReportSettings.CASHFLOW_SOURCE_N8N
    try:
        row = TenantReportSettings.objects.only("cashflow_source").get(tenant_id=tenant_id)
    except TenantReportSettings.DoesNotExist as exc:
        raise RuntimeError(f"No tenant_report_settings for tenant_id={tenant_id}") from exc
    source = (row.cashflow_source or "").strip().lower()
    if source not in {TenantReportSettings.CASHFLOW_SOURCE_N8N, TenantReportSettings.CASHFLOW_SOURCE_BACKEND}:
        raise RuntimeError(f"Invalid cashflow_source={source!r} for tenant_id={tenant_id}")
    return source


def finalize_report_payload(
    *,
    payload_obj: dict[str, Any],
    endpoint: str,
    source: str,
) -> dict[str, Any]:
    """
    Normalize raw report dict (n8n or backend) into API shape with totals, rows, monthly.
    """
    revenue = payload_obj.get("revenue")
    expense = payload_obj.get("expense")
    operational_expenses = payload_obj.get("operational_expenses")
    other_expenses = payload_obj.get("other_expenses")
    invest_returns = payload_obj.get("invest_returns")
    metadata = payload_obj.get("metadata")
    report_settings = payload_obj.get("report_settings")

    if not isinstance(revenue, list):
        revenue = []
    if not isinstance(expense, list):
        expense = []
    if not isinstance(operational_expenses, list):
        operational_expenses = []
    if not isinstance(other_expenses, list):
        other_expenses = []
    if not isinstance(invest_returns, list):
        invest_returns = []
    if not isinstance(metadata, dict):
        metadata = {}

    # Backward compatibility with old n8n shape where all expenses were in one array.
    if not operational_expenses and not other_expenses and expense:
        other_expenses = expense

    revenue_rows = _normalize_rows(revenue, "revenue")
    operational_expense_rows = _normalize_rows(operational_expenses, "expense")
    other_expense_rows = _normalize_rows(other_expenses, "expense")
    expense_rows = operational_expense_rows + other_expense_rows
    invest_return_rows = _normalize_rows(invest_returns, "expense")
    for row in invest_return_rows:
        row["category"] = "Выплаты по инвестициям"
    table_rows = sorted(
        revenue_rows + expense_rows + invest_return_rows,
        key=lambda row: (row.get("date") or "", row.get("id") or ""),
        reverse=True,
    )
    pnl_rows = revenue_rows + expense_rows

    total_revenue = sum((_to_decimal(x.get("amount")) for x in revenue_rows), start=Decimal("0"))
    total_operational_expense = sum((_to_decimal(x.get("amount")) for x in operational_expense_rows), start=Decimal("0"))
    total_other_expense = sum((_to_decimal(x.get("amount")) for x in other_expense_rows), start=Decimal("0"))
    total_expense = total_operational_expense + total_other_expense
    total_invest_returns = sum((_to_decimal(x.get("amount")) for x in invest_return_rows), start=Decimal("0"))
    total_ebit = total_revenue - total_operational_expense
    total_net = total_ebit - total_other_expense
    total_balance = total_net - total_invest_returns

    result = {
        "metadata": {
            "company_name": metadata.get("company_name"),
            "start_month": metadata.get("start_month"),
            "source": source,
            "endpoint": endpoint,
        },
        "totals": {
            "revenue": str(total_revenue),
            "operational_expense": str(total_operational_expense),
            "other_expense": str(total_other_expense),
            "expense": str(total_expense),
            "ebit": str(total_ebit),
            "net": str(total_net),
            "invest_returns": str(total_invest_returns),
            "balance": str(total_balance),
        },
        "monthly": _calc_monthly(pnl_rows),
        "revenue": revenue,
        "operational_expenses": operational_expenses,
        "other_expenses": other_expenses,
        "expense": expense,
        "invest_returns": invest_returns,
        "rows": table_rows,
    }
    if isinstance(report_settings, dict) and report_settings:
        result["report_settings"] = report_settings
    return result


def fetch_n8n_report_payload(*, tenant, user_id: int, endpoint: str, query_params: dict[str, Any]) -> dict[str, Any]:
    if not settings.BASE_DOMAIN:
        raise RuntimeError("BASE_DOMAIN is not configured.")

    pnl_backend = _is_pnl_endpoint(endpoint) and resolve_pnl_source_for_tenant(tenant=tenant) == TenantReportSettings.PNL_SOURCE_BACKEND
    cashflow_backend = (
        _is_cashflow_endpoint(endpoint)
        and resolve_cashflow_source_for_tenant(tenant=tenant) == TenantReportSettings.CASHFLOW_SOURCE_BACKEND
    )
    payload_source = "backend" if (pnl_backend or cashflow_backend) else "n8n"

    cache_key = _reports_cache_key(
        tenant_subdomain=tenant.subdomain,
        user_id=user_id,
        endpoint=endpoint,
        query_params=query_params,
        payload_source=payload_source,
    )
    cached_payload = cache.get(cache_key)
    if cached_payload is not None:
        return cached_payload

    if pnl_backend:
        from apps.modules.reports.pnl_builder import (
            ReportSettingsInvalid,
            ReportSettingsMissing,
            build_pnl_payload_from_db,
        )

        try:
            raw = build_pnl_payload_from_db(tenant=tenant, query_params=query_params)
        except (ReportSettingsMissing, ReportSettingsInvalid) as exc:
            raise RuntimeError(str(exc)) from exc

        result = finalize_report_payload(payload_obj=raw, endpoint=endpoint, source="backend")
        cache_ttl = int(getattr(settings, "REPORTS_CACHE_TTL_SECONDS", 60))
        cache.set(cache_key, result, timeout=max(1, cache_ttl))
        return result

    if cashflow_backend:
        from apps.modules.reports.cashflow_builder import (
            ReportSettingsInvalid,
            ReportSettingsMissing,
            build_cashflow_payload_from_db,
        )

        try:
            raw = build_cashflow_payload_from_db(tenant=tenant, query_params=query_params)
        except (ReportSettingsMissing, ReportSettingsInvalid) as exc:
            raise RuntimeError(str(exc)) from exc

        result = finalize_report_payload(payload_obj=raw, endpoint=endpoint, source="backend")
        cache_ttl = int(getattr(settings, "REPORTS_CACHE_TTL_SECONDS", 60))
        cache.set(cache_key, result, timeout=max(1, cache_ttl))
        return result

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

    result = finalize_report_payload(payload_obj=payload_obj, endpoint=endpoint, source="n8n")
    cache_ttl = int(getattr(settings, "REPORTS_CACHE_TTL_SECONDS", 60))
    cache.set(cache_key, result, timeout=max(1, cache_ttl))
    return result
