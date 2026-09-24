import calendar
import logging
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.payroll.constants import KIND_LABELS, SALARY_CATEGORY
from apps.modules.payroll.models import PayrollDocument, PayrollLine, PayrollPayout
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import _recalculate_request_status, route_request_approvals
from apps.modules.requests.models import Request, RequestComment
from apps.modules.requests.services import resolve_payment_type_form_defaults

User = get_user_model()

logger = logging.getLogger(__name__)


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


def maybe_create_linked_request(
    document: PayrollDocument, *, actor_user=None, force: bool = False
) -> Request | None:
    """No-op unless tenant.create_payment_request_on_payroll_accrual is True, unless
    force=True (portal accept — see accept_document), in which case a Request is
    created regardless of the tenant flag.
    Idempotent: if a Request already references this document via
    (expense_ref_id, expense_ref_target), returns it instead of creating a duplicate.
    force=True additionally excludes REJECTED requests from that "already exists"
    check, so a re-accepted draft (after its previous linked Request was rejected)
    gets a new Request instead of returning the rejected one.
    Otherwise creates exactly one Request for the sum of all PayrollLine rows and
    bootstraps its approval chain the same way apps.modules.requests.auto_requests
    ._create_request_for_template does (Request.objects.create + create_approval_rows_
    for_request + route_request_approvals)."""
    tenant = document.tenant
    if not force and not tenant.create_payment_request_on_payroll_accrual:
        return None

    # select_for_update() on the document row closes the race where two near-
    # simultaneous calls for the same PayrollDocument (e.g. a retried n8n batch
    # import) could both pass the "no existing Request" check before either
    # commits its create. A second caller blocks on the row lock until the
    # first caller's transaction commits, then re-checks and finds the
    # just-created Request instead of creating a duplicate. Different
    # documents don't block each other (the lock is per-row).
    with transaction.atomic():
        locked_document = PayrollDocument.objects.select_for_update().get(pk=document.pk)

        existing_qs = Request.objects.filter(
            tenant=tenant,
            expense_ref_id=locked_document.pk,
            expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
        )
        if force:
            existing_qs = existing_qs.exclude(status=Request.STATUS_REJECTED)
        existing = existing_qs.order_by("-id").first()
        if existing is not None:
            return existing

        total = locked_document.lines.aggregate(s=Sum("sum")).get("s") or Decimal("0")
        actor = actor_user or _system_user()
        tenant_name = (tenant.name or "").strip()

        # Same form-config lookup apps.modules.requests.auto_requests uses for
        # recurring templates. Falls back to the tenant's own name for
        # company_payer/vendor since a payroll accrual has no external
        # counterparty — the organization pays and "receives" its own payroll.
        defaults = resolve_payment_type_form_defaults(
            tenant=tenant,
            payment_type=Request.PAYMENT_TYPE_PAYROLL,
            payment_purpose=SALARY_CATEGORY,
        )
        company_payer = defaults["company_payer"] or tenant_name
        vendor_ref = defaults["vendor_ref"]
        vendor = vendor_ref.name if vendor_ref else tenant_name
        description = (
            f"Автоматически создано на основании начисления ЗП №{locked_document.pk} "
            f"от {timezone.localtime(locked_document.created_at):%d.%m.%Y}"
        )

        request_obj = Request.objects.create(
            tenant=tenant,
            created_by=actor,
            requester=actor,
            company_payer=company_payer,
            category=defaults["category"],
            vendor=vendor,
            vendor_ref=vendor_ref,
            title=tenant_name[:200],
            description=description,
            amount=total,
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_PAYROLL,
            payment_purpose=SALARY_CATEGORY,
            submitted_at=timezone.now(),
            status=Request.STATUS_DRAFT,
            billing_date=timezone.now().date(),
            expense_ref_id=locked_document.pk,
            expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
        )
        n = create_approval_rows_for_request(request_obj)
        if n and request_obj.status == Request.STATUS_DRAFT:
            _recalculate_request_status(request_obj)

    route_request_approvals(request_obj=request_obj)
    return request_obj


def _month_bounds(period_month: date) -> tuple[date, date]:
    start = period_month.replace(day=1)
    last_day = calendar.monthrange(start.year, start.month)[1]
    return start, start.replace(day=last_day)


def _next_month(d: date) -> date:
    start = d.replace(day=1)
    return date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)


def _write_draft_lines(document: PayrollDocument, *, kind: str, lines_data: list[dict]) -> None:
    start, end = _month_bounds(document.period_month)
    item = KIND_LABELS[kind]
    for idx, line_data in enumerate(lines_data, start=1):
        employee = line_data["employee"]
        PayrollLine.objects.create(
            document=document,
            line_no=idx,
            employee=employee.full_name,
            employee_fk=employee,
            item=item,
            description=line_data.get("description") or "",
            sum=line_data["sum"],
            period_start=start,
            period_end=end,
            approval=True,
        )


def _lock_draft(document: PayrollDocument) -> PayrollDocument:
    locked = PayrollDocument.objects.select_for_update().get(pk=document.pk)
    if locked.status != PayrollDocument.STATUS_DRAFT:
        raise ValidationError({"detail": "Действие доступно только для черновика."})
    return locked


def create_draft_document(*, tenant, user, period_month: date, kind: str, lines_data: list[dict]) -> PayrollDocument:
    with transaction.atomic():
        document = PayrollDocument.objects.create(
            tenant=tenant,
            doc_id=None,
            created_by=user,
            status=PayrollDocument.STATUS_DRAFT,
            source=PayrollDocument.SOURCE_PORTAL,
            period_month=period_month.replace(day=1),
            kind=kind,
        )
        _write_draft_lines(document, kind=kind, lines_data=lines_data)
    return document


def update_draft_document(*, document: PayrollDocument, period_month: date, kind: str, lines_data: list[dict]) -> PayrollDocument:
    with transaction.atomic():
        locked = _lock_draft(document)
        if PayrollPayout.objects.filter(document=locked).exists():
            raise ValidationError({"detail": "По начислению уже есть выплаты."})
        locked.period_month = period_month.replace(day=1)
        locked.kind = kind
        locked.save(update_fields=["period_month", "kind"])
        # Allowed exception to the no-delete rule (agreed): draft lines are user input,
        # never accepted, no payouts reference them.
        locked.lines.all().delete()
        _write_draft_lines(locked, kind=kind, lines_data=lines_data)
    return locked


def cancel_draft_document(*, document: PayrollDocument) -> PayrollDocument:
    with transaction.atomic():
        locked = _lock_draft(document)
        locked.status = PayrollDocument.STATUS_CANCELLED
        locked.save(update_fields=["status"])
    return locked


def copy_document(*, document: PayrollDocument, user) -> PayrollDocument:
    per_employee: dict[int, Decimal] = {}
    employees: dict[int, object] = {}
    for line in document.lines.select_related("employee_fk").order_by("line_no", "id"):
        if line.employee_fk_id is None:
            continue
        per_employee[line.employee_fk_id] = per_employee.get(line.employee_fk_id, Decimal("0")) + line.sum
        employees[line.employee_fk_id] = line.employee_fk
    if not per_employee:
        raise ValidationError({"detail": "В начислении нет строк с сотрудниками из справочника."})
    base_period = document.period_month or timezone.localdate().replace(day=1)
    period = _next_month(base_period) if document.period_month else base_period
    return create_draft_document(
        tenant=document.tenant,
        user=user,
        period_month=period,
        kind=document.kind or PayrollDocument.KIND_SALARY,
        lines_data=[{"employee": employees[eid], "sum": total} for eid, total in per_employee.items()],
    )


def current_request_for_document(document: PayrollDocument) -> Request | None:
    return (
        Request.objects.filter(
            tenant_id=document.tenant_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
            expense_ref_id=document.pk,
        )
        .exclude(status=Request.STATUS_REJECTED)
        .order_by("-id")
        .first()
    )


def add_system_comment(request_obj: Request, body: str) -> None:
    system_user = _system_user()
    if system_user is None:
        logger.warning("payroll: system user pk=1 missing, comment skipped request_id=%s", request_obj.pk)
        return
    RequestComment.objects.create(request=request_obj, created_by=system_user, body=body)


def accept_document(*, document: PayrollDocument, actor) -> Request | None:
    with transaction.atomic():
        locked = _lock_draft(document)
        if not locked.lines.exists():
            raise ValidationError({"detail": "Нужна хотя бы одна строка начисления."})
        locked.status = PayrollDocument.STATUS_ACCEPTED
        locked.payout_mode = locked.tenant.payroll_payout_mode
        locked.save(update_fields=["status", "payout_mode"])
        request_obj = maybe_create_linked_request(locked, actor_user=actor, force=True)
    return request_obj
