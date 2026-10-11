"""
Explicitly link PAYED "Начисление ЗП" заявки to a PayrollDocument chosen by a
human (request id -> doc_id), for cases the automatic doc_id + total
resolution in expense_refs can't handle: a mistyped doc number, or a request
amount that differs from the document total.

Never guesses: every pair is given explicitly and validated (same tenant,
PAYED payroll request not yet linked, document not claimed by another live
request). When the amount differs from the document total the pair is
refused unless `set_amount_from_document=True`, in which case the request
amount is replaced with the document total. On write, `expense_id` becomes
the document's doc_id and a RequestComment from "Система" records the old
number/amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from apps.modules.payroll.models import PayrollDocument
from apps.modules.requests.command_options import system_user
from apps.modules.requests.models import Request, RequestComment


@dataclass(frozen=True)
class PayrollLinkOutcome:
    request_id: int
    doc_id: str
    outcome: str  # "linked" | "linked_amount_fixed" | "error"
    detail: str
    old_amount: Decimal | None = None
    new_amount: Decimal | None = None


def _document_total(doc: PayrollDocument) -> Decimal:
    return doc.lines.aggregate(s=Sum("sum"))["s"] or Decimal("0")


def _claimed_by_live_request(*, tenant, doc: PayrollDocument, exclude_request_id: int) -> int | None:
    return (
        Request.objects.filter(
            tenant=tenant,
            expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
            expense_ref_id=doc.id,
        )
        .exclude(status=Request.STATUS_REJECTED)
        .exclude(pk=exclude_request_id)
        .values_list("id", flat=True)
        .first()
    )


def _check_pair(*, tenant, request_id: int, doc_id: str, set_amount_from_document: bool):
    req = Request.objects.filter(tenant=tenant, pk=request_id).first()
    if req is None:
        return None, None, None, "request not found in this tenant"
    if req.payment_type != Request.PAYMENT_TYPE_PAYROLL:
        return None, None, None, f"payment_type is {req.payment_type!r}, not payroll"
    if req.status != Request.STATUS_PAYED:
        return None, None, None, f"status is {req.status}, not PAYED"
    if req.expense_ref_id is not None:
        return None, None, None, f"already linked to {req.expense_ref_target} #{req.expense_ref_id}"
    doc = PayrollDocument.objects.filter(tenant=tenant, doc_id=doc_id).first()
    if doc is None:
        return None, None, None, "payroll document not found in this tenant"
    claimer = _claimed_by_live_request(tenant=tenant, doc=doc, exclude_request_id=req.pk)
    if claimer is not None:
        return None, None, None, f"document already linked to request #{claimer}"
    total = _document_total(doc)
    if total != req.amount and not set_amount_from_document:
        return None, None, None, f"amount {req.amount} != document total {total} (use set_amount_from_document)"
    return req, doc, total, None


def _comment(*, req: Request, doc: PayrollDocument, total: Decimal) -> str:
    parts = [f"Заявка привязана к ведомости ЗП №{doc.doc_id}"]
    if (req.expense_id or "") != doc.doc_id:
        parts.append(f"в заявке был указан №{req.expense_id or '—'}")
    if total != req.amount:
        parts.append(f"сумма заявки исправлена с {req.amount} на сумму ведомости {total}")
    return "; ".join(parts) + "."


def link_payroll_requests_to_documents(
    *, tenant, pairs: list[tuple[int, str]], set_amount_from_document: bool, apply_changes: bool,
) -> list[PayrollLinkOutcome]:
    results: list[PayrollLinkOutcome] = []
    seen_docs: set[str] = set()
    for request_id, doc_id in pairs:
        if doc_id in seen_docs:
            results.append(PayrollLinkOutcome(request_id, doc_id, "error", "document used twice in this run"))
            continue
        seen_docs.add(doc_id)

        req, doc, total, error = _check_pair(
            tenant=tenant, request_id=request_id, doc_id=doc_id, set_amount_from_document=set_amount_from_document,
        )
        if error is not None:
            results.append(PayrollLinkOutcome(request_id, doc_id, "error", error))
            continue

        amount_fixed = total != req.amount
        outcome = PayrollLinkOutcome(
            req.id, doc_id, "linked_amount_fixed" if amount_fixed else "linked",
            f"expense_id {req.expense_id or '—'} -> {doc.doc_id} (PayrollDocument #{doc.id})",
            old_amount=req.amount, new_amount=total,
        )
        if apply_changes:
            fields = {
                "expense_ref_id": doc.id,
                "expense_ref_target": Request.EXPENSE_REF_TARGET_PAYROLL,
                "expense_id": doc.doc_id,
            }
            if amount_fixed:
                fields["amount"] = total
            updated = Request.objects.filter(
                pk=req.pk, tenant_id=tenant.id, expense_ref_id__isnull=True, amount=req.amount,
            ).update(**fields)
            if not updated:
                results.append(PayrollLinkOutcome(req.id, doc_id, "error", "concurrent update — request changed"))
                continue
            author = system_user()
            if author is not None:
                RequestComment.objects.create(
                    request_id=req.pk, created_by=author, body=_comment(req=req, doc=doc, total=total),
                )
        results.append(outcome)
    return results
