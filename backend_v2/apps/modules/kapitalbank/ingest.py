"""Create-only import of one Kapitalbank statement (one linked account, one day).

Rows are created through the existing n8n batch upsert views, so validation, vendor
resolution, relinking and reconciliation behave exactly like the n8n workflow. Those
views UPDATE rows that already exist by external_id; this module is what makes the
import create-only: documents whose external_id already exists are never sent.

n8n creates bank expenses WITHOUT external_id (revenues and card rows carry it) and relies on
the natural-key unique index for duplicates; such a row counts as the document already being
in the portal (see ``_legacy_expense_rows``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
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
_NON_COMPARED_KEYS = {"external_id", "wallet_id", "payload", "row_no"}


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


def _ids_by_model(link: BankAccountLink, directions: dict[str, bool]):
    """Group external_ids by the model their direction maps to (True = incoming = revenue).

    One bank document can be an expense on one of our accounts and a revenue on another (a
    transfer between two linked accounts of one tenant). The n8n upsert views bind by
    external_id within one model only and the unique constraints are per model, so every
    "already exists" check looks only in the model the item goes to.
    """
    revenue_model, expense_model = _models(link)
    revenue_ids = {ext_id for ext_id, incoming in directions.items() if incoming}
    expense_ids = {ext_id for ext_id, incoming in directions.items() if not incoming}
    return [(model, ids) for model, ids in ((revenue_model, revenue_ids), (expense_model, expense_ids)) if ids]


def existing_external_ids(link: BankAccountLink, directions: dict[str, bool]) -> set[str]:
    """external_ids already on the link's wallet (in any tenant), each looked up only in the
    model its direction maps to. ``directions``: external_id -> is_incoming."""
    wallet = link.wallet()
    found: set[str] = set()
    for model, ids in _ids_by_model(link, directions):
        found.update(model.objects.filter(wallet=wallet, external_id__in=ids).values_list("external_id", flat=True))
    return found


def _tenant_external_ids(link: BankAccountLink, directions: dict[str, bool]) -> set[str]:
    """external_ids of this tenant on ANY wallet, in the model their direction maps to;
    the upsert views would update these."""
    found: set[str] = set()
    for model, ids in _ids_by_model(link, directions):
        found.update(
            model.objects.filter(tenant=link.tenant, external_id__in=ids).values_list("external_id", flat=True)
        )
    return found


def _expense_key(doc_date, doc_no, debit_turnover, payment_purpose) -> tuple:
    return (str(doc_date), str(doc_no).strip(), Decimal(str(debit_turnover)), str(payment_purpose).strip())


def _legacy_expense_rows(link: BankAccountLink, expense_items: dict[str, dict]) -> dict[str, BankExpense]:
    """external_id -> this tenant's BankExpense row WITHOUT external_id (any wallet) that is the
    same document: the key of ``uniq_bank_expense_tenant_doc_date_doc_no_turnover_purpose``
    (doc_date, doc_no, debit_turnover, payment_purpose), which is how n8n dedups expenses.
    Items without doc_no have no such key (the index skips empty doc_no)."""
    if link.is_card:
        return {}
    by_key = {
        _expense_key(i["doc_date"], i["doc_no"], i["debit_turnover"], i["payment_purpose"]): ext_id
        for ext_id, i in expense_items.items()
        if str(i.get("doc_no") or "").strip()
    }
    if not by_key:
        return {}
    rows = BankExpense.objects.filter(
        tenant=link.tenant,
        external_id="",
        doc_date__in={key[0] for key in by_key},
        doc_no__in={key[1] for key in by_key},
    ).order_by("id")
    found: dict[str, BankExpense] = {}
    for row in rows:
        ext_id = by_key.get(_expense_key(row.doc_date.isoformat(), row.doc_no, row.debit_turnover, row.payment_purpose))
        if ext_id is not None:
            found.setdefault(ext_id, row)
    return found


def present_on_wallet(link: BankAccountLink, docs: dict) -> set[str]:
    """general_ids of ``docs`` (general_id -> StatementDoc) already on the link's wallet: by
    external_id, or for bank expenses n8n created without one, by the natural key."""
    directions = {ext_id: mapping.is_incoming(doc, link.account_no) for ext_id, doc in docs.items()}
    found = existing_external_ids(link, directions)
    if link.is_card:
        return found
    expenses = {
        ext_id: mapping.bank_expense_item(doc)
        for ext_id, doc in docs.items()
        if not directions[ext_id] and ext_id not in found
    }
    wallet_id = link.wallet().id
    return found | {ext_id for ext_id, row in _legacy_expense_rows(link, expenses).items() if row.wallet_id == wallet_id}


def _check_bank_wallet(link: BankAccountLink) -> None:
    # Bank rows get their wallet from GET our_account_no/our_mfo (get_or_create BankAccount),
    # not from link.bank_account; make sure both resolve to the same wallet.
    ba = link.bank_account
    if ba.tenant_id != link.tenant_id or ba.account_no.strip() != link.account_no.strip() or ba.mfo.strip() != link.branch.strip():
        raise IngestError(
            f"Linked bank account {ba.pk} does not match statement account {link.account_no}/{link.branch}",
            status=409,
        )


def _check_card_account(link: BankAccountLink) -> None:
    # The card account's external_ref is the bank account number of the card; a link to
    # another card would put the statement on the wrong card wallet.
    card = link.card_account
    if card.tenant_id != link.tenant_id or card.external_ref.strip() != link.account_no.strip():
        raise IngestError(
            f"Linked card account {card.pk} does not match statement account {link.account_no}",
            status=409,
        )


def _has_inn(item: dict) -> bool:
    return str(item.get("inn") or "").strip() not in ("", "0")


def _post(view_cls, *, link, user, kind: str, data: list[dict], get: dict | None = None) -> int:
    request = _FakeRequest(
        data=data, tenant=link.tenant, user=user, path=f"/internal/kapitalbank/{kind}/", get=get or {}
    )
    response = view_cls().post(request)
    code = int(getattr(response, "status_code", 500))
    if code != 200:
        raise IngestError(getattr(response, "data", None), status=code)
    # "count" = items actually persisted; duplicates skipped by the view are reported separately.
    payload = getattr(response, "data", None) or {}
    return int(payload.get("count", 0)) if isinstance(payload, dict) else 0


def _normalize(model_field, value):
    if value is None:
        return ""
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
        return str(value).strip()
    return str(value).strip()


def _jsonable(value) -> str:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
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
            diffs.append(
                {
                    "external_id": item["external_id"],
                    "field": key,
                    "portal": _jsonable(portal),
                    "bank": _jsonable(bank),
                }
            )
    return diffs


def ingest_statement(link: BankAccountLink, statement: Statement, *, dry_run: bool = False) -> IngestResult:
    wallet = link.wallet()
    if wallet is None:
        raise IngestError(f"Account {link.account_no} is not linked to a wallet", status=409)
    user = User.objects.filter(pk=_SERVICE_USER_PK).first()
    if user is None:
        raise IngestError(f"Service user pk={_SERVICE_USER_PK} does not exist", status=503)
    if link.is_card:
        _check_card_account(link)
    else:
        _check_bank_wallet(link)

    # One entry per external_id; the first occurrence wins.
    docs = {}
    for doc in statement.docs:
        docs.setdefault(str(doc.general_id), doc)
    all_ids = set(docs)
    directions = {ext_id: mapping.is_incoming(doc, link.account_no) for ext_id, doc in docs.items()}

    on_wallet = existing_external_ids(link, directions)
    blocked = on_wallet | _tenant_external_ids(link, directions)

    items: dict[str, dict] = {}
    for row_no, (ext_id, doc) in enumerate(docs.items(), start=1):
        incoming = directions[ext_id]
        if link.is_card:
            item = (
                mapping.card_revenue_item(doc, wallet_id=wallet.id)
                if incoming
                else mapping.card_expense_item(doc, wallet_id=wallet.id)
            )
        else:
            item = mapping.bank_revenue_item(doc) if incoming else mapping.bank_expense_item(doc)
            if not incoming:
                # BankExpense.row_no is required by the serializer; the mapping does not emit it.
                item["row_no"] = row_no
        items[ext_id] = item

    # n8n's expense rows have no external_id: match them by the natural key. One on this wallet
    # is the document already loaded; one on another wallet of the tenant is not sent either
    # (the unique index would reject it).
    legacy = _legacy_expense_rows(
        link, {ext_id: item for ext_id, item in items.items() if not directions[ext_id] and ext_id not in blocked}
    )
    legacy_on_wallet = {ext_id for ext_id, row in legacy.items() if row.wallet_id == wallet.id}
    on_wallet = on_wallet | legacy_on_wallet
    blocked = blocked | set(legacy)

    revenue_items: list[dict] = []
    expense_items: list[dict] = []
    existing_items: list[tuple[bool, dict]] = []  # (is_revenue, item) for docs already on the wallet
    for ext_id, item in items.items():
        incoming = directions[ext_id]
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
            if row is None and not is_revenue:
                row = legacy.get(item["external_id"])
            if row is not None:
                result.field_diffs.extend(_diffs(model, row, item))
        result.missing_external_ids = sorted(all_ids - on_wallet)
        return result

    created = 0
    if to_create:
        with transaction.atomic():
            if link.is_card:
                if revenue_items:
                    created += _post(N8nCardRevenueBatchUpsertView, link=link, user=user, kind="card-revenue", data=revenue_items)
                if expense_items:
                    created += _post(N8nCardExpenseBatchUpsertView, link=link, user=user, kind="card-expense", data=expense_items)
            else:
                get = {"our_account_no": link.account_no, "our_mfo": link.branch}
                if expense_items:
                    new_vendors = _new_vendor_items(link, expense_items)
                    if new_vendors:
                        _post(N8nVendorBatchUpsertView, link=link, user=user, kind="vendors", data=new_vendors)
                    created += _post(
                        N8nBankExpenseBatchUpsertView,
                        link=link,
                        user=user,
                        kind="bank-expense",
                        data=expense_items,
                        get=get,
                    )
                if revenue_items:
                    created += _post(
                        N8nBankRevenueBatchUpsertView,
                        link=link,
                        user=user,
                        kind="bank-revenue",
                        data=revenue_items,
                        get=get,
                    )
    result.created = created
    result.missing_external_ids = sorted(all_ids - existing_external_ids(link, directions) - legacy_on_wallet)
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
