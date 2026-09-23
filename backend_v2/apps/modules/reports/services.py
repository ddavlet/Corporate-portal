from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
import hashlib
import json
import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.modules.reports.classification import (
    SECTION_INVEST_RETURNS,
    SECTION_OPERATIONAL,
    SECTION_OTHER,
    SECTION_REVENUE,
    extract_channel,
)
from apps.modules.reports.layouts import StatementLayout
from apps.modules.reports.ledger import LedgerEntry, build_ledger
from apps.modules.reports.methodology import build_methodology
from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.periods import ColumnSet, PeriodSpec, build_column_set, is_month_key, month_key, range_label
from apps.modules.reports.report_templates import (
    REPORT_TEMPLATES,
    resolve_statement_layout,
    template_to_dict,
    tenant_template_settings,
)
from apps.modules.reports.statements import (
    LineIndex,
    build_line_index,
    build_statement,
    filter_entries,
    statement_to_dict,
)
from apps.tenants.integration_settings import get_n8n_integration_settings

if TYPE_CHECKING:
    from apps.modules.reports.xlsx_export import ExportFile

logger = logging.getLogger(__name__)


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


def _extract_category(item: dict[str, Any]) -> str:
    for key in ("category", "cathegory", "cat", "cat_name", "article", "item"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "Без категории"


def _normalize_rows(items: list[dict[str, Any]], direction: str, section: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        amount = _to_decimal(item.get("amount"))
        date = _parse_iso_date(item.get("date"))
        purpose = str(item.get("purpose") or "").strip()
        description = str(item.get("description") or "").strip()
        channel = extract_channel(purpose, description)
        category = _extract_category(item)
        rows.append(
            {
                "id": str(item.get("id") or ""),
                "date": date.isoformat() if date else None,
                "amount": str(amount),
                "direction": direction,
                "section": section,
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

    revenue_rows = _normalize_rows(revenue, "revenue", SECTION_REVENUE)
    operational_expense_rows = _normalize_rows(operational_expenses, "expense", SECTION_OPERATIONAL)
    other_expense_rows = _normalize_rows(other_expenses, "expense", SECTION_OTHER)
    expense_rows = operational_expense_rows + other_expense_rows
    invest_return_rows = _normalize_rows(invest_returns, "expense", SECTION_INVEST_RETURNS)
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
    opening_balance_dec = Decimal("0")
    if isinstance(report_settings, dict):
        opening_balance_dec = _to_decimal(report_settings.get("opening_balance"))

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
            "opening_balance": str(opening_balance_dec),
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


def fetch_n8n_report_payload(
    *,
    tenant,
    user_id: int,
    endpoint: str,
    query_params: dict[str, Any],
    force_refresh: bool = False,
) -> dict[str, Any]:
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
    if force_refresh:
        cache.delete(cache_key)
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


REPORT_ENDPOINTS = {"pnl": "/n8n/pnl-data", "cashflow": "/n8n/cashflow-data"}
MONEY = Decimal("0.01")


class ReportSourceError(Exception):
    """The report payload could not be loaded (settings, n8n, network); `original` keeps the cause."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


class TemplateNotAllowed(Exception):
    """The template exists but the tenant has not allowed it."""


class LineNotFound(LookupError):
    """The requested statement line is not a line of this report (a result row, or an unknown id)."""


def _ensure_line(index: LineIndex, line_id: str | None) -> None:
    if line_id and line_id not in index.nodes:
        raise LineNotFound(line_id)


def ensure_statement_template(*, tenant, template_key: str, report: str) -> StatementLayout:
    layout = resolve_statement_layout(template_key, report)
    row = TenantReportSettings.objects.filter(tenant_id=tenant.id).first()
    _default, allowed = tenant_template_settings(row)
    if template_key not in allowed:
        raise TemplateNotAllowed(template_key)
    return layout


def _fetch_report(*, tenant, user_id: int, report: str, refresh: bool = False) -> dict[str, Any]:
    try:
        return fetch_n8n_report_payload(
            tenant=tenant,
            user_id=user_id,
            endpoint=REPORT_ENDPOINTS[report],
            query_params={},
            force_refresh=refresh,
        )
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        raise ReportSourceError(exc) from exc


def _payload_start_month(payload: dict[str, Any], entries: list[LedgerEntry], today) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    snapshot = payload.get("report_settings") if isinstance(payload.get("report_settings"), dict) else {}
    raw = str(metadata.get("start_month") or snapshot.get("start_month") or "").strip()
    if is_month_key(raw):
        return raw
    if raw:
        logger.warning("reports payload has an invalid start_month=%r; using the earliest operation month", raw)
    if entries:
        return month_key(min(entry.date for entry in entries))
    return month_key(today)


def _payload_opening_balance(payload: dict[str, Any]) -> Decimal:
    snapshot = payload.get("report_settings") if isinstance(payload.get("report_settings"), dict) else {}
    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    raw = snapshot.get("opening_balance")
    return _to_decimal(raw if raw is not None else totals.get("opening_balance"))


def _statement_warnings(*, tenant, report: str, source: str) -> list[dict[str, Any]]:
    if source != "backend":
        return []
    from apps.modules.reports import cashflow_builder, pnl_builder

    row = TenantReportSettings.objects.filter(tenant_id=tenant.id).first()
    cfg = row.pnl_config if row is not None and isinstance(row.pnl_config, dict) else {}
    compute = {
        "pnl": pnl_builder.compute_unassigned_payment_purposes,
        "cashflow": cashflow_builder.compute_unassigned_payment_purposes_cashflow,
    }[report]
    try:
        items = compute(tenant_id=tenant.id, cfg=cfg)
    except pnl_builder.ReportSettingsInvalid as exc:
        logger.warning(
            "reports statement warnings skipped: tenant=%s report=%s error=%s", tenant.subdomain, report, exc
        )
        return []
    if not items:
        return []
    amount = sum((_to_decimal(item.get("amount")) for item in items), start=Decimal("0"))
    return [
        {
            "code": "unassigned_purposes",
            "count": sum(int(item["count"]) for item in items),
            "amount": str(amount.quantize(MONEY)),
            "purposes": [item["purpose"] for item in items],
        }
    ]


@dataclass(frozen=True)
class StatementBundle:
    """A built statement plus what an export needs beyond the page's JSON."""

    data: dict[str, Any]
    entries: list[LedgerEntry]
    layout: StatementLayout
    column_set: ColumnSet


def _build_statement_bundle(
    *,
    tenant,
    user_id: int,
    template_key: str,
    report: str,
    period_spec: PeriodSpec,
    refresh: bool,
    include_warnings: bool,
) -> StatementBundle:
    layout = ensure_statement_template(tenant=tenant, template_key=template_key, report=report)
    started = time.monotonic()
    payload = _fetch_report(tenant=tenant, user_id=user_id, report=report, refresh=refresh)
    entries = build_ledger(payload)
    today = timezone.localdate()
    start_month = _payload_start_month(payload, entries, today)
    column_set = build_column_set(period_spec, today=today, start_month=start_month)
    statement = build_statement(
        entries=entries,
        layout=layout,
        column_set=column_set,
        opening_balance=_payload_opening_balance(payload),
        start_month=start_month,
    )
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    source = str(metadata.get("source") or "")
    generated_at = timezone.localtime()
    main = column_set.main
    data = statement_to_dict(statement)
    data["template"] = template_key
    data["meta"] = {
        "company": getattr(tenant, "name", None),
        "source": source,
        "generated_at": generated_at.isoformat(),
        "start_month": start_month,
        "today": today.isoformat(),
        "period_label": range_label(main.date_from, main.date_to),
    }
    data["methodology"] = build_methodology(
        report=report, report_settings=payload.get("report_settings"), source=source, generated_at=generated_at
    )
    data["warnings"] = _statement_warnings(tenant=tenant, report=report, source=source) if include_warnings else []
    logger.info(
        "reports statement: tenant=%s report=%s template=%s entries=%s ms=%s",
        tenant.subdomain,
        report,
        template_key,
        len(entries),
        int((time.monotonic() - started) * 1000),
    )
    return StatementBundle(data=data, entries=entries, layout=layout, column_set=column_set)


def build_statement_for_tenant(
    *,
    tenant,
    user_id: int,
    template_key: str,
    report: str,
    period_spec: PeriodSpec,
    refresh: bool,
    include_warnings: bool,
) -> dict[str, Any]:
    return _build_statement_bundle(
        tenant=tenant,
        user_id=user_id,
        template_key=template_key,
        report=report,
        period_spec=period_spec,
        refresh=refresh,
        include_warnings=include_warnings,
    ).data


def _matches_query(entry: LedgerEntry, needle: str) -> bool:
    request_ref = str(entry.request_id) if entry.request_id is not None else ""
    haystack = " ".join((entry.title, entry.counterparty, entry.category, request_ref)).lower()
    return needle in haystack


def _select_entries(
    entries: list[LedgerEntry],
    index: LineIndex,
    *,
    line_id: str | None,
    date_from,
    date_to,
    source: str | None,
    query: str,
) -> list[LedgerEntry]:
    """The entries behind a cell (`line_id`) or behind every section of the layout, narrowed by source and search."""
    matched = filter_entries(entries, index, line_id or None, date_from, date_to)
    if source:
        matched = [entry for entry in matched if entry.source == source]
    needle = query.strip().lower()
    if needle:
        matched = [entry for entry in matched if _matches_query(entry, needle)]
    return matched


def _line_item(entry: LedgerEntry, index: LineIndex) -> dict[str, Any]:
    leaf_id = index.entry_leaf[entry.entry_id]
    amortization = None
    if entry.amortization_index and entry.amortization_count:
        amortization = {"index": entry.amortization_index, "count": entry.amortization_count}
    return {
        "entry_id": entry.entry_id,
        "date": entry.date.isoformat(),
        "amount": str(entry.amount.quantize(MONEY)),
        "section": entry.section,
        "source": entry.source,
        "category": entry.category,
        "title": entry.title,
        "counterparty": entry.counterparty,
        "request_id": entry.request_id,
        "channel": entry.channel,
        "line_id": leaf_id,
        "line_label": index.nodes[leaf_id].label,
        "amortization": amortization,
    }


def list_statement_lines(
    *,
    tenant,
    user_id: int,
    template_key: str,
    report: str,
    line_id: str | None,
    date_from,
    date_to,
    query: str,
    page: int,
    page_size: int,
    source: str | None = None,
) -> dict[str, Any]:
    layout = ensure_statement_template(tenant=tenant, template_key=template_key, report=report)
    entries = build_ledger(_fetch_report(tenant=tenant, user_id=user_id, report=report))
    index = build_line_index(entries, layout)
    _ensure_line(index, line_id)
    matched = _select_entries(
        entries, index, line_id=line_id, date_from=date_from, date_to=date_to, source=source, query=query
    )
    matched.sort(key=lambda entry: (entry.date, entry.amount, entry.entry_id), reverse=True)
    total = sum((entry.amount for entry in matched), start=Decimal("0"))
    start = (page - 1) * page_size
    return {
        "line": line_id or "",
        "total": str(total.quantize(MONEY)),
        "count": len(matched),
        "page": page,
        "page_size": page_size,
        "items": [_line_item(entry, index) for entry in matched[start:start + page_size]],
    }


def get_template_settings_response(*, tenant) -> dict[str, Any]:
    row = TenantReportSettings.objects.filter(tenant_id=tenant.id).first()
    default, allowed = tenant_template_settings(row)
    return {
        "default": default,
        "allowed": [template_to_dict(REPORT_TEMPLATES[key]) for key in allowed],
        "available": [template_to_dict(template) for template in REPORT_TEMPLATES.values()],
    }


def save_template_settings(*, tenant, default_template: str, allowed_templates: list[str]) -> dict[str, Any]:
    row, _ = TenantReportSettings.objects.get_or_create(tenant=tenant)
    row.default_template = default_template
    row.allowed_templates = allowed_templates
    row.save(update_fields=["default_template", "allowed_templates", "updated_at"])
    return get_template_settings_response(tenant=tenant)


def _section_labels(layout: StatementLayout) -> dict[str, str]:
    return {spec.id: spec.label for spec in layout.sections()}


def _chronological(entries: list[LedgerEntry]) -> list[LedgerEntry]:
    return sorted(entries, key=lambda entry: (entry.date, entry.entry_id))


def _line_title(index: LineIndex, line_id: str | None) -> str:
    """«Выручка › Касса» for a nested line; «Все разделы» when no line was given."""
    if not line_id:
        return "Все разделы"
    node = index.nodes.get(line_id)
    if node is None:
        return line_id
    labels: list[str] = []
    while node is not None:
        labels.append(node.label)
        node = index.nodes.get(node.parent) if node.parent else None
    return " › ".join(reversed(labels))


def export_statement_xlsx(
    *,
    tenant,
    user_id: int,
    template_key: str,
    report: str,
    period_spec: PeriodSpec,
    units: str,
    author: str,
) -> ExportFile:
    """The page's statement as a workbook; «Операции» lists every operation of the headline period."""
    # Imported here: openpyxl is needed only for exports, the rest of the reports keeps working without it.
    from apps.modules.reports.xlsx_export import ExportFile, StatementExport, StatementXlsxRenderer, statement_filename

    started = time.monotonic()
    bundle = _build_statement_bundle(
        tenant=tenant,
        user_id=user_id,
        template_key=template_key,
        report=report,
        period_spec=period_spec,
        refresh=False,
        include_warnings=False,
    )
    main = bundle.column_set.main
    index = build_line_index(bundle.entries, bundle.layout)
    selected = _select_entries(
        bundle.entries, index, line_id=None, date_from=main.date_from, date_to=main.date_to, source=None, query=""
    )
    operations = [_line_item(entry, index) for entry in _chronological(selected)]
    content = StatementXlsxRenderer().render(
        StatementExport(
            statement=bundle.data,
            operations=operations,
            section_labels=_section_labels(bundle.layout),
            units=units,
            author=author,
        )
    )
    logger.info(
        "reports export: tenant=%s report=%s kind=statement operations=%s ms=%s",
        tenant.subdomain,
        report,
        len(operations),
        int((time.monotonic() - started) * 1000),
    )
    filename = statement_filename(report, period_spec, main.date_to, tenant.subdomain, timezone.localdate())
    return ExportFile(filename=filename, content=content)


def export_statement_lines_xlsx(
    *,
    tenant,
    user_id: int,
    template_key: str,
    report: str,
    line_id: str | None,
    date_from,
    date_to,
    query: str,
    source: str | None,
    author: str,
) -> ExportFile:
    """The same selection as `statement/lines/`, without pagination, as a one-sheet workbook."""
    from apps.modules.reports.xlsx_export import ExportFile, LinesExport, LinesXlsxRenderer, lines_filename

    started = time.monotonic()
    layout = ensure_statement_template(tenant=tenant, template_key=template_key, report=report)
    entries = build_ledger(_fetch_report(tenant=tenant, user_id=user_id, report=report))
    index = build_line_index(entries, layout)
    _ensure_line(index, line_id)
    selected = _chronological(
        _select_entries(entries, index, line_id=line_id, date_from=date_from, date_to=date_to, source=source, query=query)
    )
    total = sum((entry.amount for entry in selected), start=Decimal("0"))
    content = LinesXlsxRenderer().render(
        LinesExport(
            report=report,
            title=_line_title(index, line_id),
            date_from=date_from,
            date_to=date_to,
            query=query.strip(),
            items=[_line_item(entry, index) for entry in selected],
            total=str(total.quantize(MONEY)),
            section_labels=_section_labels(layout),
            company=str(getattr(tenant, "name", "") or ""),
            author=author,
            generated_at=timezone.localtime(),
        )
    )
    logger.info(
        "reports export: tenant=%s report=%s kind=lines line=%s operations=%s ms=%s",
        tenant.subdomain,
        report,
        line_id or "*",
        len(selected),
        int((time.monotonic() - started) * 1000),
    )
    filename = lines_filename(report, date_from, date_to, tenant.subdomain, timezone.localdate())
    return ExportFile(filename=filename, content=content)
