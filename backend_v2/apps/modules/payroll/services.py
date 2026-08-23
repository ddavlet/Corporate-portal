from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.modules.payroll.constants import SALARY_CATEGORY
from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import _recalculate_request_status, route_request_approvals
from apps.modules.requests.models import Request

User = get_user_model()


def _system_user():
    """Same convention as apps.modules.n8n_integration.views._system_user() — the
    pk=1 service account used as actor for records created without a human
    initiator. Duplicated locally so this module has no dependency on a private
    helper in another app."""
    return User.objects.filter(pk=1).first()


def create_payroll_document(*, tenant, user, lines_data: list[dict]) -> PayrollDocument:
    """Create a PayrollDocument (doc_id=None, created_by=user) with PayrollLine rows
    for each entry in lines_data (line_no auto-assigned starting at 1, approval=True).
    If the tenant has create_payment_request_on_payroll_accrual enabled, also creates
    the linked payment Request after the document is committed."""
    with transaction.atomic():
        document = PayrollDocument.objects.create(tenant=tenant, doc_id=None, created_by=user)
        for idx, line_data in enumerate(lines_data, start=1):
            PayrollLine.objects.create(
                document=document,
                line_no=idx,
                employee=line_data["employee"],
                item=line_data["item"],
                description=line_data.get("description") or "",
                sum=line_data["sum"],
                days_plan=line_data.get("days_plan"),
                days_fact=line_data.get("days_fact"),
                period_start=line_data.get("period_start"),
                period_end=line_data.get("period_end"),
                approval=True,
            )
    maybe_create_linked_request(document, actor_user=user)
    return document


def maybe_create_linked_request(document: PayrollDocument, *, actor_user=None) -> Request | None:
    """No-op unless tenant.create_payment_request_on_payroll_accrual is True.
    Idempotent: if a Request already references this document via
    (expense_ref_id, expense_ref_target), returns it instead of creating a duplicate.
    Otherwise creates exactly one Request for the sum of all PayrollLine rows and
    bootstraps its approval chain the same way apps.modules.requests.auto_requests
    ._create_request_for_template does (Request.objects.create + create_approval_rows_
    for_request + route_request_approvals) — no changes to the requests module."""
    tenant = document.tenant
    if not tenant.create_payment_request_on_payroll_accrual:
        return None

    existing = Request.objects.filter(
        tenant=tenant,
        expense_ref_id=document.pk,
        expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
    ).first()
    if existing is not None:
        return existing

    total = document.lines.aggregate(s=Sum("sum")).get("s") or Decimal("0")
    actor = actor_user or _system_user()

    with transaction.atomic():
        request_obj = Request.objects.create(
            tenant=tenant,
            created_by=actor,
            requester=actor,
            company_payer="",
            category="",
            title=(tenant.name or "").strip()[:200],
            description="",
            amount=total,
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_PAYROLL,
            payment_purpose=SALARY_CATEGORY,
            submitted_at=timezone.now(),
            status=Request.STATUS_DRAFT,
            billing_date=timezone.now().date(),
            expense_ref_id=document.pk,
            expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
        )
        n = create_approval_rows_for_request(request_obj)
        if n and request_obj.status == Request.STATUS_DRAFT:
            _recalculate_request_status(request_obj)

    route_request_approvals(request_obj=request_obj)
    return request_obj
