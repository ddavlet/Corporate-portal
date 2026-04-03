import calendar
import datetime as dt
import logging
import re
import threading
import time
from decimal import Decimal

from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.utils import timezone

from apps.modules.requests.approval_workflow import _recalculate_request_status
from apps.modules.requests.models import (
    Approval,
    AutoRequestTemplate,
    Request,
    RequestApprovalConfig,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.telegram_approvals.services import dispatch_pending_approvals
from apps.tenants.models import TenantMembership

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\{\{\s*([a-z_]+)(?::([^}]+))?\s*\}\}")
_RU_MONTHS_FULL = [
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "мая",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]
_EN_MONTHS_FULL = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_EN_MONTHS_SHORT = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
_poller_started = False
_poller_lock = threading.Lock()


def _month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def _first_day_add_months(month_start: dt.date, delta: int) -> dt.date:
    """month_start must be the first day of a month. Returns the first day of month_start + delta months."""
    y, m = month_start.year, month_start.month + delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return dt.date(y, m, 1)


def _billing_month_first_day(*, run_month_start: dt.date, mode: str) -> dt.date:
    """Месяц начисления заявки относительно календарного месяца дня запуска (run_month_start)."""
    if mode == AutoRequestTemplate.BILLING_MONTH_PREVIOUS:
        return _first_day_add_months(run_month_start, -1)
    if mode == AutoRequestTemplate.BILLING_MONTH_NEXT:
        return _first_day_add_months(run_month_start, 1)
    return run_month_start


def _replace_month_names_to_ru(value: str, date_value: dt.datetime) -> str:
    full_en = _EN_MONTHS_FULL[date_value.month]
    short_en = _EN_MONTHS_SHORT[date_value.month]
    full_ru = _RU_MONTHS_FULL[date_value.month]
    short_ru = full_ru[:3]
    return value.replace(full_en, full_ru).replace(short_en, short_ru)


def _format_dt_ru(date_value: dt.datetime, fmt: str) -> str:
    rendered = date_value.strftime(fmt)
    if "%B" in fmt or "%b" in fmt:
        rendered = _replace_month_names_to_ru(rendered, date_value)
    return rendered


def render_auto_request_template(raw: str, *, now_dt: dt.datetime, billing_month: dt.date) -> str:
    """
    Supported tokens:
    - {{billing_month_ru}} -> "Февраль 2026"
    - {{billing_month:%B %Y}}
    - {{now:%d.%m.%Y}}
    """
    if not raw:
        return ""
    billing_dt = dt.datetime(billing_month.year, billing_month.month, 1)

    def _sub(match: re.Match) -> str:
        key = (match.group(1) or "").strip()
        fmt = (match.group(2) or "").strip()
        if key == "billing_month_ru":
            value = _format_dt_ru(billing_dt, "%B %Y").strip()
            return f"{value[:1].upper()}{value[1:]}" if value else value
        if key == "billing_month":
            return _format_dt_ru(billing_dt, fmt or "%m.%Y")
        if key == "now":
            return _format_dt_ru(now_dt, fmt or "%Y-%m-%d %H:%M")
        return match.group(0)

    return _TOKEN_RE.sub(_sub, str(raw))


def _run_approvals_for_request(request_obj: Request) -> None:
    tenant = request_obj.tenant
    cfg = RequestApprovalConfig.objects.filter(tenant=tenant).first()
    if not cfg:
        return
    pt_cfg = cfg.payment_types.filter(payment_type=request_obj.payment_type, is_enabled=True).first()
    if not pt_cfg:
        return
    step_cfgs = list(
        pt_cfg.steps.filter(is_enabled=True).order_by("step", "id").prefetch_related("approvers__approver_user")
    )
    approver_ids: set[int] = set()
    for step_cfg in step_cfgs:
        approver_ids.update(step_cfg.approvers.values_list("approver_user_id", flat=True).distinct())
    active_approver_ids = set(
        TenantMembership.objects.filter(tenant=tenant, is_active=True, user_id__in=approver_ids).values_list(
            "user_id", flat=True
        )
    )
    approval_rows: list[Approval] = []
    for step_cfg in step_cfgs:
        for row in step_cfg.approvers.all():
            if row.approver_user_id not in active_approver_ids:
                continue
            approval_rows.append(
                Approval(
                    request=request_obj,
                    approver_user=row.approver_user,
                    approver_tg_id=row.approver_user.telegram_chat_id,
                    approver_tg_from_id=row.approver_user.telegram_from_id,
                    message_id=None,
                    message_sent=False,
                    step=step_cfg.step,
                    step_type=step_cfg.step_type,
                    decision=Approval.DECISION_PENDING,
                    comment=None,
                    decided_at=None,
                )
            )
    if approval_rows:
        Approval.objects.bulk_create(approval_rows)
        if request_obj.status == Request.STATUS_DRAFT:
            _recalculate_request_status(request_obj)
        dispatch_pending_approvals(request_obj=request_obj)


def _maybe_create_request_for_template(template: AutoRequestTemplate, *, today: dt.date, now_dt: dt.datetime) -> bool:
    run_month_start = _month_start(today)
    if template.last_run_month == run_month_start:
        return False
    max_day = calendar.monthrange(today.year, today.month)[1]
    run_day = min(max(1, int(template.day_of_month)), max_day)
    if today.day < run_day:
        return False

    billing_month = _billing_month_first_day(
        run_month_start=run_month_start,
        mode=template.billing_month_mode,
    )

    title = render_auto_request_template(template.title_template, now_dt=now_dt, billing_month=billing_month).strip()
    description = render_auto_request_template(
        template.description_template, now_dt=now_dt, billing_month=billing_month
    )
    amount: Decimal = template.amount if template.amount is not None else Decimal("0")

    company_payer = ""
    category = ""
    cfg = RequestFormConfig.objects.filter(tenant=template.tenant).first()
    if cfg:
        pt_cfg = RequestFormPaymentTypeConfig.objects.filter(
            config=cfg, payment_type=template.payment_type
        ).first()
        if pt_cfg:
            company_payer = (pt_cfg.default_company_payer or "").strip()
            purpose_value = (template.payment_purpose or "").strip()
            if purpose_value:
                matched = RequestPaymentPurposeConfig.objects.filter(
                    payment_type_config=pt_cfg,
                    name=purpose_value,
                    is_active=True,
                ).first()
                if matched:
                    category = (matched.category or "").strip()
    if not company_payer:
        company_payer = (template.company_payer or "").strip()

    request_obj = Request.objects.create(
        tenant=template.tenant,
        created_by=template.updated_by or template.requester,
        company_payer=company_payer,
        category=category,
        vendor=template.vendor_ref.name if template.vendor_ref else "",
        vendor_ref=template.vendor_ref,
        title=title or "Автозаявка",
        description=description,
        amount=amount,
        currency=template.currency,
        payment_type=template.payment_type,
        urgency=template.urgency,
        requester=template.requester,
        payment_purpose=template.payment_purpose or "",
        submitted_at=timezone.now(),
        status=Request.STATUS_DRAFT,
        billing_date=billing_month,
    )
    _run_approvals_for_request(request_obj)
    template.last_run_month = run_month_start
    template.save(update_fields=["last_run_month", "updated_at"])
    return True


def process_due_auto_requests(*, now_dt: dt.datetime | None = None) -> int:
    now_dt = now_dt or timezone.now()
    today = now_dt.date()
    created = 0
    # Avoid duplicate creation across multiple workers.
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [94837201])
                has_lock = bool(cursor.fetchone()[0])
            if not has_lock:
                return 0
            rows = AutoRequestTemplate.objects.select_for_update().filter(is_enabled=True).order_by("tenant_id", "id")
            for template in rows:
                try:
                    if _maybe_create_request_for_template(template, today=today, now_dt=now_dt):
                        created += 1
                except Exception:
                    logger.exception("Failed to process auto request template id=%s", template.id)
    except ProgrammingError:
        # Migration window: table may not exist yet while container boots.
        return 0
    return created


def _poller_loop() -> None:
    while True:
        try:
            process_due_auto_requests()
        except Exception:
            logger.exception("Auto requests poller error")
        time.sleep(60)


def start_auto_requests_poller() -> None:
    global _poller_started
    with _poller_lock:
        if _poller_started:
            return
        _poller_started = True
    threading.Thread(target=_poller_loop, name="auto-requests-poller", daemon=True).start()
