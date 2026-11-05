"""MCP tool search_everywhere: substring search over every document and directory the user can see.

Every text field of each source model is searched automatically (case-insensitive
substring), plus the names of linked people and directory entries. A numeric query
also matches record ids and numeric fields (amounts) exactly; a date matches date
fields. To cover a new document type, add a SearchSource to SOURCES — the search
code itself does not change.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.module_loading import import_string

from apps.mcp_server.auth import require_member
from apps.mcp_server.utils import json_safe

logger = logging.getLogger(__name__)

ADMIN_OR_DIRECTOR = "admin_or_director"

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50
_MIN_TEXT_LEN = 2
_SNIPPET_LEN = 160
_MAX_NUMBER = Decimal(10) ** 15
_SENSITIVE_FIELD_RE = re.compile(r"(token|secret|password|hash|_key$)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"[#№]?\s*(-?\d+(?:[.,]\d+)?)")
_SPACES_RE = re.compile(r"[\s  ]")
_USER_NAME_FIELDS = ("first_name", "last_name", "username")

_TITLE_FIELDS = (
    "title", "name", "description", "payment_purpose", "purpose", "message",
    "comment", "body", "text", "note", "client_name", "full_name", "file_name",
)
_AMOUNT_FIELDS = ("amount", "debit_turnover", "credit_turnover", "limit_amount", "total_amount")
_DATE_FIELDS = ("doc_date", "expense_at", "revenue_at", "billing_date", "date", "created_at")


@dataclass(frozen=True)
class SearchSource:
    kind: str
    model_path: str
    access: str  # module key, or ADMIN_OR_DIRECTOR
    tenant_lookup: str = "tenant"
    manager: str = "objects"
    exclude_fields: tuple[str, ...] = ()
    parent: tuple[str, str] | None = None  # (parent kind, attribute holding the parent id)
    scope: Callable[[Any, Any, Any], Any] | None = None  # (queryset, user, tenant) -> queryset


def _not_deleted_request(qs, user, tenant):
    from apps.modules.requests.models import Request

    return qs.exclude(request__status=Request.STATUS_DELETED)


def _visible_tasks(qs, user, tenant):
    from apps.modules.tasks.querysets.resolver import resolve_scope_for_user

    return resolve_scope_for_user(user, tenant).filter_queryset(qs, user, tenant)


def _visible_task_comments(qs, user, tenant):
    from apps.modules.tasks.models import Task

    return qs.filter(task__in=_visible_tasks(Task.objects.filter(tenant=tenant), user, tenant))


def _own_notes(qs, user, tenant):
    return qs.filter(Q(created_by=user) | Q(recipient_user=user))


_REQUEST_PARENT = ("request", "request_id")

SOURCES: tuple[SearchSource, ...] = (
    # Request.title is always the tenant name (see Request.save), so it would match everything.
    SearchSource("request", "apps.modules.requests.models.Request", "requests", exclude_fields=("title",)),
    SearchSource(
        "request_comment", "apps.modules.requests.models.RequestComment", "requests",
        tenant_lookup="request__tenant", parent=_REQUEST_PARENT, scope=_not_deleted_request,
    ),
    SearchSource(
        "request_approval", "apps.modules.requests.models.Approval", "requests",
        tenant_lookup="request__tenant", parent=_REQUEST_PARENT, scope=_not_deleted_request,
    ),
    SearchSource(
        "request_attachment", "apps.modules.requests.models.RequestAttachment", "requests",
        parent=_REQUEST_PARENT, scope=_not_deleted_request,
    ),
    SearchSource("request_category", "apps.modules.requests.models.RequestCategory", "requests"),
    SearchSource("cash_expense", "apps.modules.cashier.models.CashExpense", "cash"),
    SearchSource("cash_revenue", "apps.modules.cashier.models.CashRevenue", "cash"),
    SearchSource("bank_expense", "apps.modules.bank_expenses.models.BankExpense", "bank"),
    SearchSource("bank_revenue", "apps.modules.bank_expenses.models.BankRevenue", "bank"),
    SearchSource("card_expense", "apps.modules.corporate_card.models.CardExpense", "corporate_card"),
    SearchSource("card_revenue", "apps.modules.corporate_card.models.CardRevenue", "corporate_card"),
    SearchSource("payroll_document", "apps.modules.payroll.models.PayrollDocument", "payroll"),
    SearchSource(
        "payroll_line", "apps.modules.payroll.models.PayrollLine", "payroll",
        tenant_lookup="document__tenant", parent=("payroll_document", "document_id"),
    ),
    SearchSource(
        "payroll_payout", "apps.modules.payroll.models.PayrollPayout", "payroll",
        parent=("payroll_document", "document_id"),
    ),
    SearchSource("employee", "apps.modules.payroll.models.Employee", "payroll"),
    SearchSource("invest_company", "apps.modules.investments.models.InvestCompany", "investments"),
    SearchSource("invest_return", "apps.modules.investments.models.InvestReturn", "investments"),
    SearchSource("project_investment", "apps.modules.investments.models.ProjectInvestment", "investments"),
    SearchSource("invest_payout_schedule", "apps.modules.investments.models.InvestPayoutSchedule", "investments"),
    SearchSource("contract", "apps.modules.contracts.models.Contract", "contracts"),
    SearchSource("vendor", "apps.modules.vendors.models.Vendor", "vendors"),
    SearchSource("budget", "apps.modules.budgets.models.Budget", "budgets"),
    SearchSource("client_debt", "apps.modules.clients_debt.models.ClientDebtSnapshot", "clients_debt"),
    SearchSource("wallet", "apps.modules.wallets.models.Wallet", "wallets"),
    SearchSource("cash_register", "apps.modules.wallets.models.CashRegister", "wallets"),
    SearchSource("bank_account", "apps.modules.wallets.models.BankAccount", "wallets"),
    SearchSource("card_account", "apps.modules.wallets.models.CorporateCardAccount", "wallets"),
    SearchSource("task", "apps.modules.tasks.models.Task", "tasks", scope=_visible_tasks),
    SearchSource(
        "task_comment", "apps.modules.tasks.models.TaskComment", "tasks",
        tenant_lookup="task__tenant", parent=("task", "task_id"), scope=_visible_task_comments,
    ),
    SearchSource("note", "apps.modules.notes.models.Note", "notes", scope=_own_notes),
    SearchSource(
        "cash_withdrawal_receipt", "apps.modules.cash_withdrawals.models.CashWithdrawalReceipt", ADMIN_OR_DIRECTOR,
    ),
)

SOURCE_KINDS: tuple[str, ...] = tuple(s.kind for s in SOURCES)


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParsedQuery:
    text: str
    number: Decimal | None
    day: date | None


def parse_query(query: str) -> ParsedQuery:
    text = (query or "").strip()
    number = _parse_number(text)
    day = _parse_day(text)
    if number is None and day is None and len(text) < _MIN_TEXT_LEN:
        raise ValueError(f"query must be at least {_MIN_TEXT_LEN} characters, or a number or a date")
    return ParsedQuery(text=text, number=number, day=day)


def _parse_number(text: str) -> Decimal | None:
    m = _NUMBER_RE.fullmatch(_SPACES_RE.sub("", text))
    if not m:
        return None
    try:
        value = Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    return value if abs(value) < _MAX_NUMBER else None


def _parse_day(text: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Field discovery and matching
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Fields:
    text: tuple[str, ...]  # ORM lookups searched with icontains (may cross one FK)
    integers: tuple[str, ...]
    decimals: tuple[tuple[str, int | None], ...]  # (name, max digits before the point)
    dates: tuple[str, ...]
    datetimes: tuple[str, ...]
    related: tuple[str, ...]  # FK names to select_related


def _is_searchable_name(name: str, source: SearchSource) -> bool:
    return name not in source.exclude_fields and not _SENSITIVE_FIELD_RE.search(name)


def _related_text_lookups(field) -> list[str]:
    from django.contrib.auth import get_user_model

    target = field.related_model
    if target is get_user_model():
        return [f"{field.name}__{n}" for n in _USER_NAME_FIELDS]
    name_field = next((f for f in target._meta.concrete_fields if f.name == "name"), None)
    if isinstance(name_field, (models.CharField, models.TextField)):
        return [f"{field.name}__name"]
    return []


def _discover_fields(model, source: SearchSource) -> _Fields:
    from apps.tenants.models import Tenant

    text: list[str] = []
    integers: list[str] = []
    decimals: list[tuple[str, int | None]] = []
    dates: list[str] = []
    datetimes: list[str] = []
    related: list[str] = []
    for f in model._meta.concrete_fields:
        if not _is_searchable_name(f.name, source):
            continue
        if isinstance(f, models.ForeignKey):
            if f.related_model is Tenant:
                continue
            lookups = _related_text_lookups(f)
            if lookups:
                text.extend(lookups)
                related.append(f.name)
        elif isinstance(f, (models.CharField, models.TextField)):
            text.append(f.name)
        elif isinstance(f, models.IntegerField) and not f.primary_key:
            integers.append(f.name)
        elif isinstance(f, models.DecimalField):
            decimals.append((f.name, f.max_digits - f.decimal_places))
        elif isinstance(f, models.FloatField):
            decimals.append((f.name, None))
        elif isinstance(f, models.DateTimeField):
            datetimes.append(f.name)
        elif isinstance(f, models.DateField):
            dates.append(f.name)
    return _Fields(tuple(text), tuple(integers), tuple(decimals), tuple(dates), tuple(datetimes), tuple(related))


def _is_integral(number: Decimal) -> bool:
    return number == number.to_integral_value()


def _fits(number: Decimal, int_digits: int | None) -> bool:
    """A value with more integer digits than the column allows can never match (and may not bind)."""
    return int_digits is None or len(str(abs(int(number)))) <= max(int_digits, 1)


def _numeric_fields(fields: _Fields, number: Decimal) -> list[str]:
    names = list(fields.integers) if _is_integral(number) else []
    names += [name for name, digits in fields.decimals if _fits(number, digits)]
    return names


def _match_filter(fields: _Fields, q: ParsedQuery) -> Q:
    cond = Q()
    if len(q.text) >= _MIN_TEXT_LEN:
        for lookup in fields.text:
            cond |= Q(**{f"{lookup}__icontains": q.text})
    if q.number is not None:
        if _is_integral(q.number) and q.number > 0:
            cond |= Q(pk=int(q.number))
        for name in _numeric_fields(fields, q.number):
            cond |= Q(**{name: q.number})
    if q.day is not None:
        for name in fields.dates:
            cond |= Q(**{name: q.day})
        for name in fields.datetimes:
            cond |= Q(**{f"{name}__date": q.day})
    return cond


def _resolve(obj, lookup: str):
    value = obj
    for part in lookup.split("__"):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _snippet(value) -> str:
    s = " ".join(str(value).split())
    return s if len(s) <= _SNIPPET_LEN else s[: _SNIPPET_LEN - 1] + "…"


def _matched_fields(obj, fields: _Fields, q: ParsedQuery) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    needle = q.text.casefold()
    if q.number is not None and q.number == obj.pk:
        out.append({"field": "id", "value": str(obj.pk)})
    if len(needle) >= _MIN_TEXT_LEN:
        for lookup in fields.text:
            value = _resolve(obj, lookup)
            if value and needle in str(value).casefold():
                out.append({"field": lookup, "value": _snippet(value)})
    if q.number is not None:
        for name in _numeric_fields(fields, q.number):
            value = getattr(obj, name, None)
            if value is not None and Decimal(str(value)) == q.number:
                out.append({"field": name, "value": str(value)})
    if q.day is not None:
        for name in fields.dates:
            if getattr(obj, name, None) == q.day:
                out.append({"field": name, "value": q.day.isoformat()})
        for name in fields.datetimes:
            value = getattr(obj, name, None)
            if value is not None and timezone.localtime(value).date() == q.day:
                out.append({"field": name, "value": q.day.isoformat()})
    return out


def _first_attr(obj, names: tuple[str, ...]):
    for name in names:
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return None


def _hit(obj, source: SearchSource, fields: _Fields, q: ParsedQuery) -> dict[str, Any]:
    title = _first_attr(obj, tuple(n for n in _TITLE_FIELDS if n not in source.exclude_fields))
    hit: dict[str, Any] = {
        "type": source.kind,
        "id": obj.pk,
        "title": _snippet(title) if title is not None else None,
        "date": _first_attr(obj, _DATE_FIELDS),
        "amount": _first_attr(obj, _AMOUNT_FIELDS),
        "currency": getattr(obj, "currency", None),
        "status": getattr(obj, "status", None),
        "matched": _matched_fields(obj, fields, q),
    }
    if source.parent:
        parent_kind, attr = source.parent
        hit["parent"] = {"type": parent_kind, "id": getattr(obj, attr, None)}
    return {k: v for k, v in hit.items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def _make_access_check(user, tenant) -> Callable[[str], bool]:
    from apps.tenants.models import TenantUserRole
    from apps.tenants.permissions import has_effective_module_access

    cache: dict[str, bool] = {}

    def allowed(access: str) -> bool:
        if access not in cache:
            if access == ADMIN_OR_DIRECTOR:
                cache[access] = TenantUserRole.objects.filter(
                    tenant=tenant, user=user,
                    role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR],
                ).exists()
            else:
                cache[access] = has_effective_module_access(user=user, tenant=tenant, module_key=access)
        return cache[access]

    return allowed


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

def _parse_types(types: str) -> set[str] | None:
    wanted = {t.strip() for t in (types or "").split(",") if t.strip()}
    if not wanted:
        return None
    unknown = wanted - set(SOURCE_KINDS)
    if unknown:
        raise ValueError(f"Unknown types: {', '.join(sorted(unknown))}; allowed: {', '.join(SOURCE_KINDS)}")
    return wanted


def _search_source(source: SearchSource, user, tenant, q: ParsedQuery, limit: int) -> dict[str, Any] | None:
    model = import_string(source.model_path)
    fields = _discover_fields(model, source)
    cond = _match_filter(fields, q)
    if not cond:
        return None
    qs = getattr(model, source.manager).filter(**{source.tenant_lookup: tenant})
    if source.scope:
        qs = source.scope(qs, user, tenant)
    qs = qs.filter(cond)
    total = qs.count()
    if not total:
        return None
    rows = qs.select_related(*fields.related).order_by("-pk")[:limit]
    return {"type": source.kind, "total": total, "items": [_hit(obj, source, fields, q) for obj in rows]}


def search_everywhere(tenant_id: int, query: str, types: str = "", limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """Search every source the user may see; see the MCP tool docstring in server.py."""
    user, tenant = require_member(tenant_id)
    q = parse_query(query)
    wanted = _parse_types(types)
    limit = min(max(1, int(limit)), _MAX_LIMIT)
    allowed = _make_access_check(user, tenant)

    groups: list[dict[str, Any]] = []
    no_access: list[str] = []
    failed: list[str] = []
    for source in SOURCES:
        if wanted is not None and source.kind not in wanted:
            continue
        if not allowed(source.access):
            no_access.append(source.kind)
            continue
        try:
            # Savepoint: a failing source must not abort the surrounding transaction for the rest.
            with transaction.atomic():
                group = _search_source(source, user, tenant, q, limit)
        except Exception:
            logger.exception("search_everywhere: source %s failed (tenant=%s)", source.kind, tenant.id)
            failed.append(source.kind)
            continue
        if group:
            groups.append(group)

    result: dict[str, Any] = {
        "query": q.text,
        "total": sum(g["total"] for g in groups),
        "groups": groups,
    }
    if no_access:
        result["not_searched_no_access"] = no_access
    if failed:
        result["failed"] = failed
    return json_safe(result)
