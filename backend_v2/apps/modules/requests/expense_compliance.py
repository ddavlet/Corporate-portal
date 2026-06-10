from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from typing import Any

from django.db.models import Count, Exists, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.db.models import DecimalField, Value

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.payroll.constants import MODULE_KEY as PAYROLL_MODULE_KEY
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.requests.approval_workflow import min_pending_approval_step
from apps.modules.requests.expense_refs import resolve_request_expense_ref
from apps.modules.requests.models import Approval, Request
from apps.modules.requests.request_required import is_request_required_for_expense
from apps.modules.requests.serializers import build_request_approval_config_response
from apps.tenants.models import Tenant, TenantModuleConfig

DEFAULT_LIST_LIMIT = 500

ACTIVE_REQUEST_STATUSES = (
    Request.STATUS_DRAFT,
    Request.STATUS_PROGRESS_1,
    Request.STATUS_PROGRESS_2,
    Request.STATUS_PROGRESS_3,
    Request.STATUS_PROGRESS_4,
    Request.STATUS_PROGRESS_5,
    Request.STATUS_APPROVED,
)

PAYMENT_TYPE_KEYS = [pt for pt, _ in Request.PAYMENT_TYPE_CHOICES]


def _tenant_module_enabled(*, tenant, module_key: str) -> bool:
    return TenantModuleConfig.objects.filter(
        tenant=tenant,
        module_key=module_key,
        is_enabled=True,
    ).exists()


def _format_amount(value) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def _format_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone(dt_timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _payload_category(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    raw = (
        payload.get("category")
        or payload.get("cathegory")
        or payload.get("cat")
        or payload.get("cat_name")
    )
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _parse_optional_date(raw: str | None) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) == 7:
        text = f"{text}-01"
    return date.fromisoformat(text)


def _parse_limit(raw: str | None) -> int:
    if not raw:
        return DEFAULT_LIST_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIST_LIMIT
    return max(1, min(value, 5000))


def build_approval_rules_snapshot(*, tenant) -> dict[str, dict]:
    """payment_type -> ApprovalRulesSnapshot (without UI-only fields)."""
    full = build_request_approval_config_response(tenant=tenant)
    by_pt: dict[str, dict] = {}
    for row in full.get("payment_types") or []:
        pt = row.get("payment_type")
        if not pt:
            continue
        by_pt[pt] = {
            "payment_type": pt,
            "is_enabled": bool(row.get("is_enabled")),
            "request_not_required_field_options": list(row.get("request_not_required_field_options") or []),
            "request_not_required_rules": list(row.get("request_not_required_rules") or []),
            "steps": list(row.get("steps") or []),
            "purpose_exceptions": list(row.get("purpose_exceptions") or []),
        }
    for pt in PAYMENT_TYPE_KEYS:
        by_pt.setdefault(
            pt,
            {
                "payment_type": pt,
                "is_enabled": False,
                "request_not_required_field_options": [],
                "request_not_required_rules": [],
                "steps": [],
                "purpose_exceptions": [],
            },
        )
    return by_pt


def annotate_bank_expense_compliance(qs, *, tenant):
    request_subquery = Request.objects.filter(
        tenant=tenant,
        payment_type__in=(Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP),
        amount=OuterRef("debit_turnover"),
    ).filter(
        Q(expense_ref_id=OuterRef("id"))
        | (
            Q(expense_id=OuterRef("doc_no"))
            & Q(expense_year=OuterRef("expense_year"))
        )
    )
    paid_request_subquery = request_subquery.filter(status=Request.STATUS_PAYED)
    return qs.annotate(
        has_request=Exists(request_subquery),
        has_paid_request=Exists(paid_request_subquery),
        matched_request_id=Subquery(request_subquery.order_by("-created_at").values("id")[:1]),
    )


def annotate_cash_expense_compliance(qs, *, tenant):
    request_subquery = Request.objects.filter(
        tenant=tenant,
        payment_type=Request.PAYMENT_TYPE_CASH,
        amount=OuterRef("amount"),
    ).filter(Q(expense_ref_id=OuterRef("id")) | Q(expense_id=OuterRef("external_id")))
    paid_request_subquery = request_subquery.filter(status=Request.STATUS_PAYED)
    return qs.annotate(
        has_request=Exists(request_subquery),
        has_paid_request=Exists(paid_request_subquery),
        matched_request_id=Subquery(request_subquery.order_by("-created_at").values("id")[:1]),
    )


def annotate_card_expense_compliance(qs, *, tenant):
    request_subquery = Request.objects.filter(
        tenant=tenant,
        payment_type=Request.PAYMENT_TYPE_CARD,
        amount=OuterRef("amount"),
    ).filter(Q(expense_ref_id=OuterRef("id")))
    paid_request_subquery = request_subquery.filter(status=Request.STATUS_PAYED)
    return qs.annotate(
        has_request=Exists(request_subquery),
        has_paid_request=Exists(paid_request_subquery),
        matched_request_id=Subquery(request_subquery.order_by("-created_at").values("id")[:1]),
    )


def annotate_payroll_compliance(qs, *, tenant):
    payroll_total_subquery = (
        PayrollLine.objects.filter(document_id=OuterRef("pk"))
        .values("document_id")
        .annotate(total=Sum("sum"))
        .values("total")[:1]
    )
    request_subquery = Request.objects.filter(
        tenant=tenant,
        payment_type=Request.PAYMENT_TYPE_PAYROLL,
        amount=Subquery(payroll_total_subquery),
    ).filter(Q(expense_ref_id=OuterRef("pk")) | Q(expense_id=OuterRef("doc_id")))
    paid_request_subquery = request_subquery.filter(status=Request.STATUS_PAYED)
    return qs.annotate(
        has_request=Exists(request_subquery),
        has_paid_request=Exists(paid_request_subquery),
        matched_request_id=Subquery(request_subquery.order_by("-id").values("id")[:1]),
        total_sum=Coalesce(
            Sum("lines__sum"),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        ),
        lines_count=Count("lines", distinct=True),
    )


def _request_status_map(*, tenant, request_ids: set[int]) -> dict[int, Request]:
    if not request_ids:
        return {}
    return {
        row.id: row
        for row in Request.objects.filter(tenant=tenant, id__in=request_ids).only(
            "id",
            "status",
        )
    }


def _pending_step_for_request(*, request_id: int | None, request_by_id: dict[int, Request]) -> int | None:
    if not request_id:
        return None
    req = request_by_id.get(request_id)
    if req is None:
        return None
    if req.status in (Request.STATUS_PAYED, Request.STATUS_REJECTED, Request.STATUS_DELETED):
        return None
    return min_pending_approval_step(request_id=request_id)


def _is_linked_request_in_progress(*, matched_request_id, request_by_id: dict[int, Request]) -> bool:
    if not matched_request_id:
        return False
    req = request_by_id.get(int(matched_request_id))
    if req is None:
        return False
    return req.status not in (Request.STATUS_PAYED, Request.STATUS_REJECTED, Request.STATUS_DELETED)


def _base_expense_fields(
    *,
    obj_id: int,
    expense_type: str,
    amount,
    date_value,
    request_required: bool,
    has_paid_request: bool,
    matched_request_id,
    request_by_id: dict[int, Request],
) -> dict:
    matched_id = int(matched_request_id) if matched_request_id else None
    matched_req = request_by_id.get(matched_id) if matched_id else None
    return {
        "id": obj_id,
        "expense_type": expense_type,
        "amount": _format_amount(amount),
        "date": _format_date(date_value),
        "request_required": request_required,
        "has_paid_request": bool(has_paid_request),
        "matched_request_id": matched_id,
        "matched_request_status": matched_req.status if matched_req else None,
        "pending_approval_step": _pending_step_for_request(
            request_id=matched_id,
            request_by_id=request_by_id,
        ),
    }


def _serialize_cash_row(obj, *, tenant, request_by_id: dict[int, Request]) -> dict:
    request_required = is_request_required_for_expense(
        tenant=tenant,
        payment_type=Request.PAYMENT_TYPE_CASH,
        expense_obj=obj,
    )
    row = _base_expense_fields(
        obj_id=obj.id,
        expense_type="cash",
        amount=obj.amount,
        date_value=obj.expense_at,
        request_required=request_required,
        has_paid_request=obj.has_paid_request,
        matched_request_id=obj.matched_request_id,
        request_by_id=request_by_id,
    )
    row.update(
        {
            "external_id": obj.external_id,
            "title": obj.title or "",
            "expense_year": obj.expense_year,
            "vendor_name": getattr(obj.vendor, "name", None) if obj.vendor_id else None,
            "category": _payload_category(obj.payload),
        }
    )
    return row


def _serialize_bank_row(obj, *, tenant, request_by_id: dict[int, Request]) -> dict:
    request_required = is_request_required_for_expense(
        tenant=tenant,
        payment_type=Request.PAYMENT_TYPE_TRANSFER,
        expense_obj=obj,
    )
    row = _base_expense_fields(
        obj_id=obj.id,
        expense_type="bank",
        amount=obj.debit_turnover,
        date_value=obj.doc_date,
        request_required=request_required,
        has_paid_request=obj.has_paid_request,
        matched_request_id=obj.matched_request_id,
        request_by_id=request_by_id,
    )
    row.update(
        {
            "doc_no": obj.doc_no,
            "doc_date": _format_date(obj.doc_date),
            "payment_purpose": obj.payment_purpose,
            "vendor_name": getattr(obj.vendor, "name", None) if obj.vendor_id else None,
            "category": _payload_category(getattr(obj, "payload", None)),
            "expense_year": obj.expense_year,
        }
    )
    return row


def _serialize_card_row(obj, *, tenant, request_by_id: dict[int, Request]) -> dict:
    request_required = is_request_required_for_expense(
        tenant=tenant,
        payment_type=Request.PAYMENT_TYPE_CARD,
        expense_obj=obj,
    )
    row = _base_expense_fields(
        obj_id=obj.id,
        expense_type="card",
        amount=obj.amount,
        date_value=obj.expense_at,
        request_required=request_required,
        has_paid_request=obj.has_paid_request,
        matched_request_id=obj.matched_request_id,
        request_by_id=request_by_id,
    )
    row.update(
        {
            "title": obj.title or "",
            "category": _payload_category(obj.payload),
        }
    )
    return row


def _serialize_payroll_row(obj, *, request_by_id: dict[int, Request]) -> dict:
    row = _base_expense_fields(
        obj_id=obj.id,
        expense_type="payroll",
        amount=getattr(obj, "total_sum", None),
        date_value=obj.created_at,
        request_required=True,
        has_paid_request=obj.has_paid_request,
        matched_request_id=obj.matched_request_id,
        request_by_id=request_by_id,
    )
    row.update(
        {
            "doc_id": obj.doc_id,
            "total_sum": _format_amount(getattr(obj, "total_sum", None)),
            "lines_count": int(getattr(obj, "lines_count", 0) or 0),
            "created_at": _format_date(obj.created_at),
        }
    )
    return row


def _split_expense_rows(
    rows: list[dict],
    *,
    request_by_id: dict[int, Request],
    payroll: bool = False,
) -> tuple[list[dict], list[dict]]:
    missing: list[dict] = []
    linked: list[dict] = []
    for row in rows:
        if payroll:
            if not row["has_paid_request"]:
                missing.append(row)
        elif row["request_required"] and not row["has_paid_request"]:
            missing.append(row)
        if _is_linked_request_in_progress(
            matched_request_id=row.get("matched_request_id"),
            request_by_id=request_by_id,
        ):
            linked.append(row)
    return missing, linked


def _apply_date_filter_bank(qs, *, date_from: date | None, date_to: date | None):
    if date_from:
        qs = qs.filter(doc_date__gte=date_from)
    if date_to:
        qs = qs.filter(doc_date__lte=date_to)
    return qs


def _apply_date_filter_cash_card(qs, *, date_from: date | None, date_to: date | None):
    if date_from:
        qs = qs.filter(expense_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_at__date__lte=date_to)
    return qs


def _apply_date_filter_payroll(qs, *, date_from: date | None, date_to: date | None):
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    return qs


def _empty_expense_channel(*, payment_type: str, rules: dict) -> dict:
    return {
        "enabled": False,
        "payment_type": payment_type,
        "rules": rules,
        "missing_paid_request": [],
        "linked_request_in_progress": [],
        "counts": {"missing_paid_request": 0, "linked_request_in_progress": 0},
    }


def collect_cash_channel_payload(
    *,
    tenant,
    rules_by_pt: dict[str, dict],
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> dict:
    rules = rules_by_pt[Request.PAYMENT_TYPE_CASH]
    if not _tenant_module_enabled(tenant=tenant, module_key="cash"):
        return _empty_expense_channel(payment_type=Request.PAYMENT_TYPE_CASH, rules=rules)

    qs = CashExpense.objects.filter(tenant=tenant, wallet__is_visible_in_cash_section=True)
    qs = _apply_date_filter_cash_card(qs, date_from=date_from, date_to=date_to)
    qs = annotate_cash_expense_compliance(qs, tenant=tenant).select_related("vendor").order_by(
        "-expense_at", "-created_at", "-id"
    )[: limit * 4]

    request_ids = {int(obj.matched_request_id) for obj in qs if obj.matched_request_id}
    request_by_id = _request_status_map(tenant=tenant, request_ids=request_ids)
    serialized = [_serialize_cash_row(obj, tenant=tenant, request_by_id=request_by_id) for obj in qs]

    missing, linked = _split_expense_rows(serialized, request_by_id=request_by_id)
    return {
        "enabled": True,
        "payment_type": Request.PAYMENT_TYPE_CASH,
        "rules": rules,
        "missing_paid_request": missing[:limit],
        "linked_request_in_progress": linked[:limit],
        "counts": {
            "missing_paid_request": len(missing),
            "linked_request_in_progress": len(linked),
        },
    }


def collect_bank_channel_payload(
    *,
    tenant,
    rules_by_pt: dict[str, dict],
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> dict:
    empty_rules = {
        "Перечисление": rules_by_pt[Request.PAYMENT_TYPE_TRANSFER],
        "Пополнение": rules_by_pt[Request.PAYMENT_TYPE_TOPUP],
    }
    if not _tenant_module_enabled(tenant=tenant, module_key="bank"):
        return {
            "enabled": False,
            "rules_by_payment_type": empty_rules,
            "missing_paid_request": [],
            "linked_request_in_progress": [],
            "counts": {"missing_paid_request": 0, "linked_request_in_progress": 0},
        }

    qs = BankExpense.objects.filter(tenant=tenant)
    qs = _apply_date_filter_bank(qs, date_from=date_from, date_to=date_to)
    qs = annotate_bank_expense_compliance(qs, tenant=tenant).select_related("vendor").order_by(
        "-doc_date", "-process_date", "-id"
    )[: limit * 4]

    request_ids = {int(obj.matched_request_id) for obj in qs if obj.matched_request_id}
    request_by_id = _request_status_map(tenant=tenant, request_ids=request_ids)
    serialized = [_serialize_bank_row(obj, tenant=tenant, request_by_id=request_by_id) for obj in qs]

    missing, linked = _split_expense_rows(serialized, request_by_id=request_by_id)
    return {
        "enabled": True,
        "rules_by_payment_type": empty_rules,
        "missing_paid_request": missing[:limit],
        "linked_request_in_progress": linked[:limit],
        "counts": {
            "missing_paid_request": len(missing),
            "linked_request_in_progress": len(linked),
        },
    }


def collect_corporate_card_channel_payload(
    *,
    tenant,
    rules_by_pt: dict[str, dict],
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> dict:
    rules = rules_by_pt[Request.PAYMENT_TYPE_CARD]
    if not _tenant_module_enabled(tenant=tenant, module_key="corporate_card"):
        return _empty_expense_channel(payment_type=Request.PAYMENT_TYPE_CARD, rules=rules)

    qs = CardExpense.objects.filter(tenant=tenant)
    qs = _apply_date_filter_cash_card(qs, date_from=date_from, date_to=date_to)
    qs = annotate_card_expense_compliance(qs, tenant=tenant).order_by("-expense_at", "-created_at", "-id")[
        : limit * 4
    ]

    request_ids = {int(obj.matched_request_id) for obj in qs if obj.matched_request_id}
    request_by_id = _request_status_map(tenant=tenant, request_ids=request_ids)
    serialized = [_serialize_card_row(obj, tenant=tenant, request_by_id=request_by_id) for obj in qs]

    missing, linked = _split_expense_rows(serialized, request_by_id=request_by_id)
    return {
        "enabled": True,
        "payment_type": Request.PAYMENT_TYPE_CARD,
        "rules": rules,
        "missing_paid_request": missing[:limit],
        "linked_request_in_progress": linked[:limit],
        "counts": {
            "missing_paid_request": len(missing),
            "linked_request_in_progress": len(linked),
        },
    }


def collect_payroll_channel_payload(
    *,
    tenant,
    rules_by_pt: dict[str, dict],
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> dict:
    rules = rules_by_pt[Request.PAYMENT_TYPE_PAYROLL]
    base = {
        "payment_type": Request.PAYMENT_TYPE_PAYROLL,
        "rules": rules,
        "missing_paid_request": [],
        "linked_request_in_progress": [],
        "counts": {"missing_paid_request": 0, "linked_request_in_progress": 0},
    }
    if not _tenant_module_enabled(tenant=tenant, module_key=PAYROLL_MODULE_KEY):
        return {"enabled": False, **base}

    qs = PayrollDocument.objects.filter(tenant=tenant)
    qs = _apply_date_filter_payroll(qs, date_from=date_from, date_to=date_to)
    qs = annotate_payroll_compliance(qs, tenant=tenant).order_by("-created_at", "-id")[: limit * 4]

    request_ids = {int(obj.matched_request_id) for obj in qs if obj.matched_request_id}
    request_by_id = _request_status_map(tenant=tenant, request_ids=request_ids)
    serialized = [_serialize_payroll_row(obj, request_by_id=request_by_id) for obj in qs]

    missing, linked = _split_expense_rows(serialized, request_by_id=request_by_id, payroll=True)
    return {
        "enabled": True,
        **base,
        "missing_paid_request": missing[:limit],
        "linked_request_in_progress": linked[:limit],
        "counts": {
            "missing_paid_request": len(missing),
            "linked_request_in_progress": len(linked),
        },
    }


def _request_expense_linked(*, tenant, request_obj: Request) -> bool:
    if request_obj.expense_ref_id:
        return True
    resolved_id, _normalized = resolve_request_expense_ref(
        tenant=tenant,
        payment_type=request_obj.payment_type,
        category=request_obj.category,
        expense_id_raw=request_obj.expense_id,
        expense_year=request_obj.expense_year,
        amount=request_obj.amount,
    )
    return resolved_id is not None


def _pending_approver_user_ids(*, request_id: int, step: int | None) -> list[int]:
    if step is None:
        return []
    return list(
        Approval.objects.filter(
            request_id=request_id,
            step=step,
            decision=Approval.DECISION_PENDING,
        )
        .exclude(approver_user_id__isnull=True)
        .values_list("approver_user_id", flat=True)
        .distinct()
    )


def _serialize_pending_request(*, tenant, request_obj: Request) -> dict:
    expense_linked = _request_expense_linked(tenant=tenant, request_obj=request_obj)
    pending_step = min_pending_approval_step(request_id=request_obj.id)
    return {
        "id": request_obj.id,
        "status": request_obj.status,
        "payment_type": request_obj.payment_type,
        "amount": _format_amount(request_obj.amount),
        "currency": request_obj.currency,
        "vendor": request_obj.vendor or "",
        "category": request_obj.category or "",
        "payment_purpose": request_obj.payment_purpose or "",
        "billing_date": _format_date(request_obj.billing_date),
        "submitted_at": _format_date(request_obj.submitted_at),
        "expense_linked": expense_linked,
        "expense_id": (str(request_obj.expense_id).strip() if request_obj.expense_id else None) or None,
        "expense_ref_id": request_obj.expense_ref_id,
        "expense_ref_target": request_obj.expense_ref_target,
        "pending_approval_step": pending_step,
        "pending_approver_user_ids": _pending_approver_user_ids(
            request_id=request_obj.id,
            step=pending_step,
        ),
    }


def collect_requests_pending_approval(
    *,
    tenant,
    rules_by_pt: dict[str, dict],
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> dict:
    pending_request_ids = Approval.objects.filter(
        request__tenant=tenant,
        decision=Approval.DECISION_PENDING,
    ).values_list("request_id", flat=True)

    qs = Request.objects.filter(
        tenant=tenant,
        id__in=pending_request_ids,
        status__in=ACTIVE_REQUEST_STATUSES,
    ).exclude(status__in=(Request.STATUS_PAYED, Request.STATUS_REJECTED))

    if date_from:
        qs = qs.filter(billing_date__gte=date_from)
    if date_to:
        qs = qs.filter(billing_date__lte=date_to)

    qs = qs.order_by("-submitted_at", "-id")

    by_payment_type: dict[str, dict] = {}
    for pt in PAYMENT_TYPE_KEYS:
        without: list[dict] = []
        with_link: list[dict] = []
        for request_obj in qs.filter(payment_type=pt)[: limit * 4]:
            row = _serialize_pending_request(tenant=tenant, request_obj=request_obj)
            if row["expense_linked"]:
                with_link.append(row)
            else:
                without.append(row)
        by_payment_type[pt] = {
            "rules": rules_by_pt[pt],
            "without_expense_link": without[:limit],
            "with_expense_link": with_link[:limit],
            "counts": {
                "without_expense_link": len(without),
                "with_expense_link": len(with_link),
            },
        }
    return by_payment_type


def build_unmatched_expenses_payload(
    *,
    tenant: Tenant,
    date_from: date | None = None,
    date_to: date | None = None,
    channel: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict:
    rules_by_pt = build_approval_rules_snapshot(tenant=tenant)
    channel_key = (channel or "").strip().lower()

    payload: dict[str, Any] = {
        "generated_at": datetime.now(tz=dt_timezone.utc).isoformat(),
    }

    if channel_key in ("", "cash"):
        payload["cash"] = collect_cash_channel_payload(
            tenant=tenant,
            rules_by_pt=rules_by_pt,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    else:
        payload["cash"] = _empty_expense_channel(
            payment_type=Request.PAYMENT_TYPE_CASH,
            rules=rules_by_pt[Request.PAYMENT_TYPE_CASH],
        )

    if channel_key in ("", "bank"):
        payload["bank"] = collect_bank_channel_payload(
            tenant=tenant,
            rules_by_pt=rules_by_pt,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    else:
        payload["bank"] = {
            "enabled": False,
            "rules_by_payment_type": {
                "Перечисление": rules_by_pt[Request.PAYMENT_TYPE_TRANSFER],
                "Пополнение": rules_by_pt[Request.PAYMENT_TYPE_TOPUP],
            },
            "missing_paid_request": [],
            "linked_request_in_progress": [],
            "counts": {"missing_paid_request": 0, "linked_request_in_progress": 0},
        }

    if channel_key in ("", "corporate_card"):
        payload["corporate_card"] = collect_corporate_card_channel_payload(
            tenant=tenant,
            rules_by_pt=rules_by_pt,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    else:
        payload["corporate_card"] = _empty_expense_channel(
            payment_type=Request.PAYMENT_TYPE_CARD,
            rules=rules_by_pt[Request.PAYMENT_TYPE_CARD],
        )

    if channel_key in ("", "payroll"):
        payload["payroll"] = collect_payroll_channel_payload(
            tenant=tenant,
            rules_by_pt=rules_by_pt,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
    else:
        payload["payroll"] = {
            "enabled": False,
            "payment_type": Request.PAYMENT_TYPE_PAYROLL,
            "rules": rules_by_pt[Request.PAYMENT_TYPE_PAYROLL],
            "missing_paid_request": [],
            "linked_request_in_progress": [],
            "counts": {"missing_paid_request": 0, "linked_request_in_progress": 0},
        }

    payload["requests_pending_approval"] = collect_requests_pending_approval(
        tenant=tenant,
        rules_by_pt=rules_by_pt,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return payload


PORTAL_EXPENSE_MODULES = frozenset({"cash", "bank", "payroll", "corporate_card"})


def resolve_request_portal_expense_module(request_obj: Request, *, tenant) -> str | None:
    """Portal expense module for request; aligns with isPayedMissingLinkedExpense on the frontend."""
    ref_id = request_obj.expense_ref_id
    raw = str(getattr(request_obj, "expense_id", None) or "").strip()
    pt = request_obj.payment_type
    category = (request_obj.category or "").strip()

    if ref_id is not None and pt == Request.PAYMENT_TYPE_PAYROLL:
        if PayrollDocument.objects.filter(tenant=tenant, id=ref_id).exists():
            return "payroll"
    if ref_id is not None and pt == Request.PAYMENT_TYPE_CASH:
        if CashExpense.objects.filter(tenant=tenant, id=ref_id).exists():
            return "cash"
    if ref_id is not None and pt in (Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP):
        if BankExpense.objects.filter(tenant=tenant, id=ref_id).exists():
            return "bank"
    if ref_id is not None and pt == Request.PAYMENT_TYPE_CARD:
        if CardExpense.objects.filter(tenant=tenant, id=ref_id).exists():
            return "corporate_card"
    if raw:
        return "external"
    return None


def request_is_payed_missing_portal_expense(request_obj: Request, *, tenant) -> bool:
    if request_obj.status != Request.STATUS_PAYED:
        return False
    mod = resolve_request_portal_expense_module(request_obj, tenant=tenant)
    if mod is None:
        return True
    if mod == "external":
        return True
    if mod in PORTAL_EXPENSE_MODULES:
        return False
    return True


def filter_requests_payed_missing_expense(qs, *, tenant):
    qs = qs.filter(status=Request.STATUS_PAYED)
    matched_ids = [
        obj.pk
        for obj in qs.iterator(chunk_size=500)
        if request_is_payed_missing_portal_expense(obj, tenant=tenant)
    ]
    if not matched_ids:
        return qs.none()
    return qs.filter(pk__in=matched_ids)


def filter_expenses_missing_request(qs, *, tenant, payment_type: str, payroll: bool = False):
    matched_ids: list[int] = []
    for obj in qs.iterator(chunk_size=500):
        if payroll:
            if not obj.has_paid_request:
                matched_ids.append(obj.pk)
        elif is_request_required_for_expense(
            tenant=tenant,
            payment_type=payment_type,
            expense_obj=obj,
        ) and not obj.has_paid_request:
            matched_ids.append(obj.pk)
    if not matched_ids:
        return qs.none()
    return qs.filter(pk__in=matched_ids)


def parse_unmatched_expenses_query_params(*, query_params) -> tuple[date | None, date | None, str | None, int]:
    channel = (query_params.get("channel") or "").strip().lower() or None
    if channel and channel not in ("cash", "bank", "corporate_card", "payroll"):
        raise ValueError("channel")
    try:
        date_from = _parse_optional_date(query_params.get("date_from"))
        date_to = _parse_optional_date(query_params.get("date_to"))
    except ValueError as exc:
        raise ValueError("date") from exc
    limit = _parse_limit(query_params.get("limit"))
    return date_from, date_to, channel, limit
