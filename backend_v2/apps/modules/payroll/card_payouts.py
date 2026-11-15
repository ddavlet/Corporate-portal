"""Salary card payouts (transit account 23106) against payroll documents.

- attach_pending: a stored card row with a known portal employee goes to the salary document of
  its period (M−1 of the payment); see pick_document.
- expected card: prefilled from last month's card fact, editable; it is reserved from the cash limit.
- maybe_close / close_sweep: a document covered by card + cash closes only with
  PayrollCardSettings.auto_close_enabled (it fires n8n new-payed-request).
- attention_state, link_bank_employee, assign_payout: the review screen API.

Nothing here runs for a tenant until PayrollCardSettings.card_start_period is set; documents and
rows of earlier periods are never touched. Rows are never deleted.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Exists, Max, Min, OuterRef, Subquery, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.modules.payroll.card_balance import (
    ZERO,
    card_enabled_for_document,
    card_start_period,
    document_card_summary,
    previous_month,
)
from apps.modules.payroll.models import (
    Employee,
    PayrollBankEmployeeLink,
    PayrollCardPayout,
    PayrollCardSettings,
    PayrollDocument,
    PayrollExpectedCard,
    PayrollLine,
    PayrollPayout,
)
from apps.modules.payroll.payouts import _close, document_label, payout_state
from apps.modules.payroll.services import current_request_for_document
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)

ATTENTION_LIMIT = 200
MISSING_CARD_FROM_DAY = 15
OVERPAID_MONTHS = 12  # the overpaid group looks at the last 12 periods with card money only
_OPEN_OR_CLOSED = (PayrollDocument.STATUS_ACCEPTED, PayrollDocument.STATUS_CLOSED)


# ── employees of card rows ──────────────────────────────────────────────────────────────────


def fill_employees_from_links(*, tenant=None) -> int:
    """Rows of a linked bank employee get the portal employee (all periods: history rows feed the
    expected-card prefill)."""
    link = PayrollBankEmployeeLink.objects.filter(
        tenant_id=OuterRef("tenant_id"), bank_employee_id=OuterRef("bank_employee_id")
    )
    qs = PayrollCardPayout.objects.filter(employee__isnull=True, bank_employee__isnull=False, tenant__isnull=False)
    if tenant is not None:
        qs = qs.filter(tenant=tenant)
    return qs.filter(Exists(link)).update(employee_id=Subquery(link.values("employee_id")[:1]))


# ── attaching rows to documents ─────────────────────────────────────────────────────────────


def _employee_remaining(document: PayrollDocument, employee_id: int) -> Decimal:
    accrued = (
        PayrollLine.objects.filter(document=document, employee_fk_id=employee_id).aggregate(s=Sum("sum"))["s"] or ZERO
    )
    cash = PayrollPayout.objects.filter(document=document, employee_id=employee_id).aggregate(s=Sum("amount"))["s"] or ZERO
    card = (
        PayrollCardPayout.objects.filter(document=document, employee_id=employee_id).aggregate(s=Sum("amount"))["s"]
        or ZERO
    )
    return accrued - cash - card


def _attachable(document: PayrollDocument) -> bool:
    """Card money goes only to a salary portal document that is closed, or accepted with its request
    already approved: a request still in approval may be rejected, and a rejected document must be
    able to go back to draft (revert_document_to_draft_on_reject refuses once card rows are on it)."""
    if (
        document.kind != PayrollDocument.KIND_SALARY
        or document.payout_mode != PayrollDocument.PAYOUT_MODE_PORTAL
        or document.status not in _OPEN_OR_CLOSED
    ):
        return False
    if document.status == PayrollDocument.STATUS_CLOSED:
        return True
    request_obj = current_request_for_document(document)
    return request_obj is not None and request_obj.status == Request.STATUS_APPROVED


def pick_document(*, tenant_id: int, employee_id: int, period_month: date) -> PayrollDocument | None:
    """Salary document of the period (portal, closed or accepted with an approved request, see
    _attachable) where the employee has lines: the earliest accepted one with something left to
    pay, else the earliest. Advance and bonus documents never get card money automatically."""
    candidates = list(
        PayrollDocument.objects.filter(
            tenant_id=tenant_id,
            kind=PayrollDocument.KIND_SALARY,
            period_month=period_month,
            payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL,
            status__in=_OPEN_OR_CLOSED,
        )
        .filter(Exists(PayrollLine.objects.filter(document_id=OuterRef("pk"), employee_fk_id=employee_id)))
        .order_by("created_at", "id")
    )
    candidates = [document for document in candidates if _attachable(document)]
    for document in candidates:
        if document.status == PayrollDocument.STATUS_ACCEPTED and _employee_remaining(document, employee_id) > ZERO:
            return document
    return candidates[0] if candidates else None


def maybe_close(locked: PayrollDocument) -> bool:
    """Close like a full cash payout (closed, system comment, request PAYED → n8n) when card and
    cash covered everything; only with auto_close_enabled. Call with the document row locked."""
    if locked.status != PayrollDocument.STATUS_ACCEPTED or locked.payout_mode != PayrollDocument.PAYOUT_MODE_PORTAL:
        return False
    if not PayrollCardSettings.objects.filter(tenant_id=locked.tenant_id, auto_close_enabled=True).exists():
        return False
    state = payout_state(locked)
    if state["card_paid_total"] <= ZERO or state["remaining_total"] > ZERO:
        return False
    request_obj = current_request_for_document(locked)
    if request_obj is None or request_obj.status != Request.STATUS_APPROVED:
        return False
    try:
        with transaction.atomic():
            _close(locked, request_obj=request_obj, actor=None, underpaid_comment=None)
    except Exception:
        logger.exception("payroll card: auto-close failed document_id=%s", locked.pk)
        locked.refresh_from_db()
        return False
    return True


def _attach_one(*, payout_id: int, document: PayrollDocument, now: datetime) -> bool:
    with transaction.atomic():
        # Same lock as a cash payout: card and cash never change one document concurrently.
        locked = PayrollDocument.objects.select_for_update(of=("self",)).select_related("tenant").get(pk=document.pk)
        # pick_document read without the lock: a reject (back to draft) or a cancel may have won.
        if not _attachable(locked):
            return False
        updated = PayrollCardPayout.objects.filter(pk=payout_id, document__isnull=True).update(
            document=locked, attached_at=now
        )
        if not updated:
            return False
        maybe_close(locked)
    return True


def attach_pending(*, tenant=None, now: datetime) -> int:
    """Attach every unattached row with a known employee whose period is not before the tenant's
    card_start_period. Failures are logged per row and retried by the next run."""
    settings_qs = PayrollCardSettings.objects.filter(card_start_period__isnull=False)
    if tenant is not None:
        settings_qs = settings_qs.filter(tenant=tenant)
    starts = dict(settings_qs.values_list("tenant_id", "card_start_period"))
    if not starts:
        return 0
    fill_employees_from_links(tenant=tenant)
    rows = (
        PayrollCardPayout.objects.filter(document__isnull=True, employee__isnull=False, tenant_id__in=list(starts))
        .order_by("paid_on", "id")
        .values_list("pk", "tenant_id", "employee_id", "period_month")
    )
    attached = 0
    # (tenant, employee, period) without a document: the rest of that group is skipped in this run
    # instead of repeating pick_document for every stuck row.
    no_document: set[tuple[int, int, date]] = set()
    for payout_id, tenant_id, employee_id, period_month in rows:
        if period_month < starts[tenant_id]:
            continue
        group = (tenant_id, employee_id, period_month)
        if group in no_document:
            continue
        try:
            document = pick_document(tenant_id=tenant_id, employee_id=employee_id, period_month=period_month)
            if document is None:
                no_document.add(group)
                continue
            if _attach_one(payout_id=payout_id, document=document, now=now):
                attached += 1
        except Exception:
            logger.exception("payroll card: attach failed payout_id=%s", payout_id)
    return attached


def safe_attach_pending(*, tenant=None, now: datetime | None = None) -> int:
    try:
        return attach_pending(tenant=tenant, now=now or timezone.now())
    except Exception:
        logger.exception("payroll card: attach run failed tenant_id=%s", getattr(tenant, "pk", None))
        return 0


def close_sweep(*, tenant=None) -> int:
    """Nightly: close documents covered by card + cash (flag on), e.g. after the flag was switched on."""
    tenants = PayrollCardSettings.objects.filter(auto_close_enabled=True, card_start_period__isnull=False)
    if tenant is not None:
        tenants = tenants.filter(tenant=tenant)
    doc_ids = list(
        PayrollDocument.objects.filter(
            tenant_id__in=tenants.values("tenant_id"),
            status=PayrollDocument.STATUS_ACCEPTED,
            payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL,
        )
        .filter(Exists(PayrollCardPayout.objects.filter(document_id=OuterRef("pk"))))
        .values_list("pk", flat=True)
    )
    closed = 0
    for doc_id in doc_ids:
        try:
            with transaction.atomic():
                locked = PayrollDocument.objects.select_for_update(of=("self",)).select_related("tenant").get(pk=doc_id)
                if maybe_close(locked):
                    closed += 1
        except Exception:
            logger.exception("payroll card: close sweep failed document_id=%s", doc_id)
    return closed


# ── expected card ───────────────────────────────────────────────────────────────────────────


def prefill_expected(document: PayrollDocument) -> int:
    """Expected card per employee = card fact of the previous period in this tenant (history rows
    before card_start_period count). Values changed by hand are never overwritten."""
    if document.kind != PayrollDocument.KIND_SALARY:
        return 0
    if document.status not in (PayrollDocument.STATUS_DRAFT, PayrollDocument.STATUS_ACCEPTED):
        return 0
    if not card_enabled_for_document(document):
        return 0
    fill_employees_from_links(tenant=document.tenant)
    facts = dict(
        PayrollCardPayout.objects.filter(
            tenant_id=document.tenant_id, period_month=previous_month(document.period_month), employee__isnull=False
        )
        .values("employee_id")
        .annotate(s=Sum("amount"))
        .values_list("employee_id", "s")
    )
    employee_ids = set(
        PayrollLine.objects.filter(document=document, employee_fk__isnull=False).values_list("employee_fk_id", flat=True)
    )
    existing = {row.employee_id: row for row in PayrollExpectedCard.objects.filter(document=document)}
    now = timezone.now()
    changed = 0
    for employee_id in employee_ids:
        amount = facts.get(employee_id) or ZERO
        row = existing.get(employee_id)
        if row is None:
            if amount > ZERO:
                PayrollExpectedCard.objects.create(document=document, employee_id=employee_id, amount=amount, updated_at=now)
                changed += 1
        elif not row.is_manual and row.amount != amount:
            row.amount = amount
            row.updated_at = now
            row.save(update_fields=["amount", "updated_at"])
            changed += 1
    return changed


def safe_prefill_expected(document_id: int) -> None:
    """Never fails the caller (draft create / update): an error is logged, the draft stays as it is.
    Runs in a savepoint so a failed statement never breaks a caller's outer transaction."""
    try:
        with transaction.atomic():
            document = PayrollDocument.objects.select_related("tenant").get(pk=document_id)
            prefill_expected(document)
    except Exception:
        logger.exception("payroll card: expected card prefill failed document_id=%s", document_id)


def on_document_accepted(document_id: int) -> None:
    """Runs after the accept transaction commits: recalculates the expected card and attaches rows
    that were waiting for this document. Errors are logged; the next sync retries the attach."""
    safe_prefill_expected(document_id)
    try:
        tenant = PayrollDocument.objects.select_related("tenant").get(pk=document_id).tenant
    except Exception:
        logger.exception("payroll card: accepted document_id=%s not readable", document_id)
        return
    safe_attach_pending(tenant=tenant)


def set_expected(*, document: PayrollDocument, items: list[dict], actor) -> dict:
    if not card_enabled_for_document(document):
        raise ValidationError({"detail": "Учёт выплат на карту для этого начисления не включён."})
    with transaction.atomic():
        locked = PayrollDocument.objects.select_for_update(of=("self",)).select_related("tenant").get(pk=document.pk)
        if locked.status not in (PayrollDocument.STATUS_DRAFT, PayrollDocument.STATUS_ACCEPTED):
            raise ValidationError(
                {"detail": "Ожидаемую карту можно менять только у черновика или принятого начисления."}
            )
        employee_ids = set(
            PayrollLine.objects.filter(document=locked, employee_fk__isnull=False).values_list("employee_fk_id", flat=True)
        )
        seen: set[int] = set()
        for item in items:
            employee_id = item["employee_id"]
            amount = Decimal(item["amount"])
            if employee_id in seen:
                raise ValidationError({"items": "Сотрудник указан дважды."})
            seen.add(employee_id)
            if employee_id not in employee_ids:
                raise ValidationError({"items": f"Сотрудника id={employee_id} нет в начислении."})
            if amount < ZERO:
                raise ValidationError({"items": "Сумма не может быть меньше нуля."})
        now = timezone.now()
        existing = {row.employee_id: row for row in PayrollExpectedCard.objects.filter(document=locked)}
        for item in items:
            amount = Decimal(item["amount"])
            current = existing.get(item["employee_id"])
            # An amount the user did not change stays as it is: a prefilled value keeps following
            # last month's card fact instead of becoming «set by hand».
            if (current.amount if current is not None else ZERO) == amount:
                continue
            PayrollExpectedCard.objects.update_or_create(
                document=locked,
                employee_id=item["employee_id"],
                defaults={"amount": amount, "is_manual": True, "updated_by": actor, "updated_at": now},
            )
    return payout_state(locked)


# ── name matching (candidate only: a person confirms the link) ────────────────────────────────

_LATIN_DIGRAPHS = (
    ("o'", "ў"), ("o‘", "ў"), ("oʻ", "ў"), ("o`", "ў"), ("o’", "ў"),
    ("g'", "ғ"), ("g‘", "ғ"), ("gʻ", "ғ"), ("g`", "ғ"), ("g’", "ғ"),
    ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е"),
    ("ts", "ц"), ("zh", "ж"), ("kh", "х"),
)
_LATIN_LETTERS = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ", "i": "и", "j": "ж",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т",
    "u": "у", "v": "в", "w": "в", "x": "х", "y": "й", "z": "з", "'": "ъ", "’": "ъ", "ʼ": "ъ",
}
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)
_SIMPLIFY = str.maketrans({"ё": "е", "э": "е", "ў": "у", "ғ": "г", "қ": "к", "ҳ": "х", "й": "и", "ъ": None, "ь": None})


def _word_to_cyrillic(word: str) -> str:
    out = []
    i = 0
    while i < len(word):
        pair = word[i : i + 2]
        hit = next((cyr for lat, cyr in _LATIN_DIGRAPHS if pair == lat), None)
        if hit is not None:
            out.append(hit)
            i += 2
            continue
        ch = word[i]
        if ch == "e" and i == 0:
            out.append("э")
        else:
            out.append(_LATIN_LETTERS.get(ch, ch))
        i += 1
    return "".join(out)


def latin_to_cyrillic(text: str) -> str:
    """Uzbek/Russian Latin transliteration of a name: 'ISMOILOV SHERZOD' → 'Исмоилов Шерзод'."""
    words = (text or "").lower().split()
    return " ".join(w.capitalize() for w in (_word_to_cyrillic(word) for word in words) if w)


def _name_tokens(text: str) -> list[str]:
    if _LATIN_RE.search(text or ""):
        text = latin_to_cyrillic(text)
    simplified = (text or "").lower().translate(_SIMPLIFY).replace("дж", "ж")
    return [t for t in re.split(r"[^а-яa-z0-9]+", simplified) if t]


def suggest_employee(name: str, employee_tokens: list[tuple[Employee, list[str]]]) -> Employee | None:
    """The only portal employee whose surname and first name both occur in the bank's name.
    employee_tokens: [(employee, _name_tokens(employee.full_name))], computed once per screen."""
    bank_tokens = set(_name_tokens(name))
    if not bank_tokens:
        return None
    matches = [e for e, tokens in employee_tokens if len(tokens) >= 2 and set(tokens[:2]) <= bank_tokens]
    return matches[0] if len(matches) == 1 else None


# ── review screen ───────────────────────────────────────────────────────────────────────────


def _mask_account(account_no: str) -> str:
    return f"{account_no[:5]}…{account_no[-4:]}" if len(account_no) >= 12 else account_no


def _empty_attention(enabled: bool) -> dict:
    groups = ("unlinked", "awaiting_document", "missing_card", "overpaid")
    out: dict = {"enabled": enabled, "count": 0, "counts": {key: 0 for key in groups}}
    out.update({key: [] for key in groups})
    return out


def attention_state(tenant: Tenant, *, today: date | None = None) -> dict:
    if tenant.payroll_payout_mode != Tenant.PAYROLL_PAYOUT_MODE_PORTAL:
        return _empty_attention(False)
    start = card_start_period(tenant.pk)
    if start is None:
        return _empty_attention(False)
    today = today or timezone.localdate()
    links = {
        link.bank_employee_id: (link.employee_id, link.employee.full_name)
        for link in PayrollBankEmployeeLink.objects.filter(tenant=tenant).select_related("employee")
    }
    employees = list(Employee.objects.filter(tenant=tenant).only("id", "full_name"))
    employee_tokens: list[tuple[Employee, list[str]]] | None = None
    first_portal_period = PayrollDocument.objects.filter(
        tenant=tenant, payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL, period_month__isnull=False
    ).aggregate(m=Min("period_month"))["m"]

    unlinked: list[dict] = []
    awaiting: list[dict] = []
    rows = (
        PayrollCardPayout.objects.filter(tenant=tenant, document__isnull=True, period_month__gte=start)
        .select_related("bank_employee", "employee", "batch")
        .order_by("paid_on", "id")
    )
    for row in rows:
        if row.employee_id is not None:
            resolved = (row.employee_id, row.employee.full_name)
        else:
            resolved = links.get(row.bank_employee_id) if row.bank_employee_id else None
        if resolved is None:
            bank = row.bank_employee
            candidate = None
            # Only the rows the screen shows get a name suggestion (cut to ATTENTION_LIMIT below).
            if len(unlinked) < ATTENTION_LIMIT:
                if employee_tokens is None:
                    employee_tokens = [(e, _name_tokens(e.full_name)) for e in employees]
                candidate = suggest_employee(
                    (bank.full_name if bank else "") or row.name_from_purpose, employee_tokens
                )
            unlinked.append(
                {
                    "payout_id": row.pk,
                    "bank_employee_id": row.bank_employee_id,
                    "bank_full_name": bank.full_name if bank else None,
                    "name_from_purpose": row.name_from_purpose,
                    "masked_card": (bank.masked_card or None) if bank else None,
                    "card_account_masked": _mask_account(row.card_account),
                    "amount": row.amount,
                    "paid_on": row.paid_on,
                    "batch_num": row.batch.num if row.batch else None,
                    "batch_date": row.batch.doc_date if row.batch else None,
                    "candidate": {"id": candidate.pk, "full_name": candidate.full_name} if candidate else None,
                }
            )
        elif first_portal_period is not None and row.period_month >= first_portal_period:
            awaiting.append(
                {
                    "payout_id": row.pk,
                    "employee_id": resolved[0],
                    "full_name": resolved[1],
                    "period_month": row.period_month,
                    "amount": row.amount,
                    "paid_on": row.paid_on,
                }
            )

    missing = _missing_card(tenant, start=start, today=today, links=links)
    overpaid = _overpaid(tenant, start=start)
    groups = {"unlinked": unlinked, "awaiting_document": awaiting, "missing_card": missing, "overpaid": overpaid}
    # counts: full size of every group; the lists below are cut to ATTENTION_LIMIT rows.
    out = {
        "enabled": True,
        "count": sum(len(v) for v in groups.values()),
        "counts": {key: len(value) for key, value in groups.items()},
    }
    out.update({key: value[:ATTENTION_LIMIT] for key, value in groups.items()})
    return out


def _months_back(day: date, months: int) -> date:
    """First day of the month ``months`` before ``day``."""
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


def _missing_card(tenant: Tenant, *, start: date, today: date, links: dict) -> list[dict]:
    if today.day < MISSING_CARD_FROM_DAY:
        return []
    period = previous_month(today)
    if period < start:
        return []
    expected = (
        PayrollExpectedCard.objects.filter(
            document__tenant=tenant,
            document__status=PayrollDocument.STATUS_ACCEPTED,
            document__payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL,
            document__kind=PayrollDocument.KIND_SALARY,
            document__period_month=period,
            amount__gt=0,
        )
        # Expected card of an employee no longer in the document's lines is stale, not missing.
        .filter(
            Exists(
                PayrollLine.objects.filter(document_id=OuterRef("document_id"), employee_fk_id=OuterRef("employee_id"))
            )
        )
        .select_related("document", "employee")
        .order_by("employee__full_name", "document_id")
    )
    arrived: set[int] = set()
    for employee_id, bank_employee_id in PayrollCardPayout.objects.filter(tenant=tenant, period_month=period).values_list(
        "employee_id", "bank_employee_id"
    ):
        if employee_id is not None:
            arrived.add(employee_id)
        elif bank_employee_id in links:
            arrived.add(links[bank_employee_id][0])
    return [
        {
            "document_id": row.document_id,
            "document_label": document_label(row.document),
            "employee_id": row.employee_id,
            "full_name": row.employee.full_name,
            "expected": row.amount,
        }
        for row in expected
        if row.employee_id not in arrived
    ]


def _overpaid(tenant: Tenant, *, start: date) -> list[dict]:
    with_card = PayrollDocument.objects.filter(
        tenant=tenant,
        payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL,
        status__in=_OPEN_OR_CLOSED,
        period_month__gte=start,
    ).filter(Exists(PayrollCardPayout.objects.filter(document_id=OuterRef("pk"))))
    latest = with_card.aggregate(m=Max("period_month"))["m"]
    if latest is None:
        return []
    docs = {doc.pk: doc for doc in with_card.filter(period_month__gte=_months_back(latest, OVERPAID_MONTHS - 1))}
    summary = document_card_summary(list(docs))
    names = dict(Employee.objects.filter(tenant=tenant).values_list("id", "full_name"))
    out = []
    for doc_id, data in summary.items():
        document = docs[doc_id]
        for employee_id, numbers in data["employees"].items():
            if numbers["overpaid"] <= ZERO:
                continue
            out.append(
                {
                    "document_id": doc_id,
                    "document_label": document_label(document),
                    "period_month": document.period_month,
                    "employee_id": employee_id,
                    "full_name": names.get(employee_id, ""),
                    "accrued": numbers["accrued"],
                    "cash": numbers["cash"],
                    "card": numbers["card"],
                    "overpaid": numbers["overpaid"],
                }
            )
    out.sort(key=lambda r: (r["period_month"], r["document_id"], r["full_name"]), reverse=True)
    return out


def link_bank_employee(*, tenant: Tenant, bank_employee_id: int, employee_id: int, actor) -> PayrollBankEmployeeLink:
    """All rows of the bank employee in this tenant (past and future) now belong to the employee."""
    if not PayrollCardPayout.objects.filter(tenant=tenant, bank_employee_id=bank_employee_id).exists():
        raise NotFound("Сотрудник банка не найден.")
    employee = Employee.objects.filter(tenant=tenant, pk=employee_id).first()
    if employee is None:
        raise NotFound("Сотрудник не найден.")

    def already_linked():
        existing = (
            PayrollBankEmployeeLink.objects.filter(tenant=tenant, bank_employee_id=bank_employee_id)
            .select_related("employee")
            .first()
        )
        if existing is not None:
            raise ValidationError(
                {"detail": f"Этот сотрудник банка уже привязан к «{existing.employee.full_name}»."}
            )

    already_linked()
    try:
        with transaction.atomic():
            link = PayrollBankEmployeeLink.objects.create(
                tenant=tenant, bank_employee_id=bank_employee_id, employee=employee, decided_by=actor
            )
    except IntegrityError:
        already_linked()
        raise
    fill_employees_from_links(tenant=tenant)
    safe_attach_pending(tenant=tenant)
    return link


def assign_payout(*, tenant: Tenant, payout_id: int, employee_id: int, actor) -> PayrollCardPayout:
    """One-off: a row without a bank employee_id is given to an employee. Not a link by card or account."""
    employee = Employee.objects.filter(tenant=tenant, pk=employee_id).first()
    with transaction.atomic():
        payout = PayrollCardPayout.objects.select_for_update().filter(tenant=tenant, pk=payout_id).first()
        if payout is None:
            raise NotFound("Выплата не найдена.")
        if employee is None:
            raise NotFound("Сотрудник не найден.")
        if payout.bank_employee_id is not None:
            raise ValidationError({"detail": "У выплаты есть ID сотрудника банка — используйте привязку."})
        if payout.employee_id is not None:
            raise ValidationError({"detail": "Выплата уже отнесена к сотруднику."})
        payout.employee = employee
        payout.employee_assigned_manually = True
        payout.assigned_by = actor
        payout.save(update_fields=["employee", "employee_assigned_manually", "assigned_by"])
    safe_attach_pending(tenant=tenant)
    payout.refresh_from_db()
    return payout
