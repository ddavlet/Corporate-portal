"""Create-only import of one Kapitalbank statement (one linked account, one day).

Rows are created through the existing n8n batch upsert views, so validation, vendor
resolution, relinking and reconciliation behave exactly like the n8n workflow. Those
views UPDATE rows that already exist by external_id; this module is what makes the
import create-only: documents whose external_id already exists are never sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.n8n_integration.views import (
    N8nBankExpenseBatchUpsertView,
    N8nBankRevenueBatchUpsertView,
    N8nCardExpenseBatchUpsertView,
    N8nCardRevenueBatchUpsertView,
    N8nVendorBatchUpsertView,
)
from apps.modules.vendors.models import Vendor

from . import mapping
from .client import Statement
from .models import BankAccountLink

logger = logging.getLogger(__name__)
User = get_user_model()

_SERVICE_USER_PK = 1  # same user the n8n views use internally (`_system_user()`)
_NON_COMPARED_KEYS = {"external_id", "wallet_id", "payload"}


class IngestError(Exception):
    def __init__(self, detail, status: int = 400):
        self.status = status
        self.detail = detail
        super().__init__(f"Kapitalbank ingest failed (HTTP {status}): {detail}")


@dataclass
class IngestResult:
    created: int = 0
    skipped_existing: int = 0
    missing_external_ids: list[str] = field(default_factory=list)
    would_create: list[dict] = field(default_factory=list)
    field_diffs: list[dict] = field(default_factory=list)


class _FakeRequest:
    def __init__(self, *, data, tenant, user, path, get):
        self.data = data
        self.tenant = tenant
        self.user = user
        self.META = {}
        self.method = "POST"
        self.path = path
        self.GET = get


def _models(link: BankAccountLink):
    return (CardRevenue, CardExpense) if link.is_card else (BankRevenue, BankExpense)


def existing_external_ids(link: BankAccountLink, external_ids: set[str]) -> set[str]:
    """external_ids already present on the link's wallet, in any tenant."""
    if not external_ids:
        return set()
    wallet = link.wallet()
    found: set[str] = set()
    for model in _models(link):
        found.update(
            model.objects.filter(wallet=wallet, external_id__in=external_ids).values_list("external_id", flat=True)
        )
    return found


def _tenant_external_ids(link: BankAccountLink, external_ids: set[str]) -> set[str]:
    """external_ids of this tenant on ANY wallet; the upsert views would update these."""
    found: set[str] = set()
    for model in _models(link):
        found.update(
            model.objects.filter(tenant=link.tenant, external_id__in=external_ids).values_list("external_id", flat=True)
        )
    return found


def _check_bank_wallet(link: BankAccountLink) -> None:
    # Bank rows get their wallet from GET our_account_no/our_mfo (get_or_create BankAccount),
    # not from link.bank_account; make sure both resolve to the same wallet.
    ba = link.bank_account
    if ba.tenant_id != link.tenant_id or ba.account_no.strip() != link.account_no.strip() or ba.mfo.strip() != link.branch.strip():
        raise IngestError(
            f"Linked bank account {ba.pk} does not match statement account {link.account_no}/{link.branch}",
            status=409,
        )


def _has_inn(item: dict) -> bool:
    return str(item.get("inn") or "").strip() not in ("", "0")


def _post(view_cls, *, link, user, kind: str, data: list[dict], get: dict | None = None) -> None:
    request = _FakeRequest(
        data=data, tenant=link.tenant, user=user, path=f"/internal/kapitalbank/{kind}/", get=get or {}
    )
    response = view_cls().post(request)
    code = int(getattr(response, "status_code", 500))
    if code != 200:
        raise IngestError(getattr(response, "data", None), status=code)


def _normalize(model_field, value):
    if value is None:
        return None
    internal = model_field.get_internal_type()
    try:
        if internal == "DecimalField":
            return Decimal(str(value))
        if internal == "DateTimeField":
            return value if not isinstance(value, str) else parse_datetime(value)
        if internal == "DateField":
            if isinstance(value, str):
                return date.fromisoformat(value)
            return value
    except (InvalidOperation, ValueError):
        return value
    return str(value)


def _diffs(model, row, item: dict) -> list[dict]:
    diffs = []
    concrete = {f.name: f for f in model._meta.concrete_fields}
    for key, bank_value in item.items():
        if key in _NON_COMPARED_KEYS or key not in concrete:
            continue
        model_field = concrete[key]
        portal = _normalize(model_field, getattr(row, key))
        bank = _normalize(model_field, bank_value)
        if portal != bank:
            diffs.append({"external_id": item["external_id"], "field": key, "portal": portal, "bank": bank})
    return diffs


def ingest_statement(link: BankAccountLink, statement: Statement, *, dry_run: bool = False) -> IngestResult:
    wallet = link.wallet()
    if wallet is None:
        raise IngestError(f"Account {link.account_no} is not linked to a wallet", status=409)
    user = User.objects.filter(pk=_SERVICE_USER_PK).first()
    if user is None:
        raise IngestError(f"Service user pk={_SERVICE_USER_PK} does not exist", status=503)
    if not link.is_card:
        _check_bank_wallet(link)

    # One entry per external_id; the first occurrence wins.
    docs = {}
    for doc in statement.docs:
        docs.setdefault(str(doc.general_id), doc)
    all_ids = set(docs)

    on_wallet = existing_external_ids(link, all_ids)
    blocked = on_wallet | _tenant_external_ids(link, all_ids)

    revenue_items: list[dict] = []
    expense_items: list[dict] = []
    existing_items: list[tuple[bool, dict]] = []  # (is_revenue, item) for docs already on the wallet
    for ext_id, doc in docs.items():
        incoming = mapping.is_incoming(doc, link.account_no)
        if link.is_card:
            item = (
                mapping.card_revenue_item(doc, wallet_id=wallet.id)
                if incoming
                else mapping.card_expense_item(doc, wallet_id=wallet.id)
            )
        else:
            item = mapping.bank_revenue_item(doc) if incoming else mapping.bank_expense_item(doc)
        if ext_id in on_wallet:
            existing_items.append((incoming, item))
        if ext_id in blocked:
            continue
        (revenue_items if incoming else expense_items).append(item)

    result = IngestResult(skipped_existing=len(on_wallet))
    to_create = expense_items + revenue_items

    if dry_run:
        result.would_create = to_create
        revenue_model, expense_model = _models(link)
        for is_revenue, item in existing_items:
            model = revenue_model if is_revenue else expense_model
            row = model.objects.filter(wallet=wallet, external_id=item["external_id"]).first()
            if row is not None:
                result.field_diffs.extend(_diffs(model, row, item))
        result.missing_external_ids = sorted(all_ids - on_wallet)
        return result

    if to_create:
        with transaction.atomic():
            if link.is_card:
                if revenue_items:
                    _post(N8nCardRevenueBatchUpsertView, link=link, user=user, kind="card-revenue", data=revenue_items)
                if expense_items:
                    _post(N8nCardExpenseBatchUpsertView, link=link, user=user, kind="card-expense", data=expense_items)
            else:
                get = {"our_account_no": link.account_no, "our_mfo": link.branch}
                if expense_items:
                    new_vendors = _new_vendor_items(link, expense_items)
                    if new_vendors:
                        _post(N8nVendorBatchUpsertView, link=link, user=user, kind="vendors", data=new_vendors)
                    _post(
                        N8nBankExpenseBatchUpsertView,
                        link=link,
                        user=user,
                        kind="bank-expense",
                        data=expense_items,
                        get=get,
                    )
                if revenue_items:
                    _post(
                        N8nBankRevenueBatchUpsertView,
                        link=link,
                        user=user,
                        kind="bank-revenue",
                        data=revenue_items,
                        get=get,
                    )
    result.created = len(to_create)
    result.missing_external_ids = sorted(all_ids - existing_external_ids(link, all_ids))
    return result


def _new_vendor_items(link: BankAccountLink, expense_items: list[dict]) -> list[dict]:
    """Vendors for new expenses. Skips counterparties without INN (VendorSerializer rejects
    transfer vendors without it and the batch is atomic) and vendors that already exist
    (the vendors view would update them, but this import is create-only)."""
    candidates = [v for v in mapping.vendor_items(expense_items) if _has_inn(v)]
    if not candidates:
        return []
    known = set(
        Vendor.objects.filter(
            tenant=link.tenant, account_number__in=[v["account_no"] for v in candidates]
        ).values_list("account_number", flat=True)
    )
    return [v for v in candidates if v["account_no"] not in known]
