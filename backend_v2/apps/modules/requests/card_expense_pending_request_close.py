"""
Close an already approved (APPROVED, not yet paid) "Платежная карта" request by a
newly imported CardExpense instead of creating an automatic request for it.

A candidate is an APPROVED card request of the same tenant with the same amount and
currency, not linked to any expense and created within
[expense date - PENDING_REQUEST_LOOKBACK_DAYS; expense date + PENDING_REQUEST_LOOKAHEAD_DAYS]
(dates in the project time zone). Requests with the configured payment purpose win,
then FIFO by (created_at, id).

Closing goes through approval_workflow.complete_request_payment_by_system, so PAYED
side effects (n8n, Telegram cards, Web Push) are the same as for a manual payment.
Lock order is always "CardExpense -> Request" (the caller locks the expense first).
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.corporate_card.auto_request_config import wallet_label
from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.approval_workflow import complete_request_payment_by_system
from apps.modules.requests.command_options import date_to_payed_at
from apps.modules.requests.expense_reconciliation_core import EXPENSE_MATCH_WINDOW_DAYS
from apps.modules.requests.models import Request, RequestComment
from apps.modules.requests.payment_step_guards import payment_step_suppression_reason
from apps.modules.requests.payment_type_policies import check_request_mutation

logger = logging.getLogger(__name__)

PENDING_REQUEST_LOOKBACK_DAYS = 30
PENDING_REQUEST_LOOKAHEAD_DAYS = EXPENSE_MATCH_WINDOW_DAYS  # 3
# Upper bound of candidates re-checked under lock for one expense.
PENDING_REQUEST_MAX_CANDIDATES = 20


def card_expense_local_date(expense: CardExpense) -> dt.date:
    return timezone.localtime(expense.expense_at).date()


def card_expense_currency(expense: CardExpense) -> str:
    return str(expense.currency or "").strip().upper()


def format_card_expense_amount(amount: Decimal) -> str:
    return f"{Decimal(amount):,.2f}".replace(",", " ")


def pending_request_close_comment(expense: CardExpense, *, config=None) -> str:
    comment = (
        f"Заявка закрыта автоматически по расходу корпоративной карты #{expense.pk} "
        f"от {card_expense_local_date(expense):%d.%m.%Y} на "
        f"{format_card_expense_amount(expense.amount)} {card_expense_currency(expense)}."
    )
    if config is not None:
        # The match is by amount/currency/date only: name the card and the setting for review.
        comment += f" Карта: «{wallet_label(expense.wallet)}», настройка автозаявок #{config.pk}."
    return comment


def pending_card_request_candidates(
    *,
    expense: CardExpense,
    preferred_purpose: str,
    exclude_ids=frozenset(),
) -> QuerySet[Request]:
    """Unlocked, ordered queryset of APPROVED card requests that may be closed by `expense`."""
    expense_date = card_expense_local_date(expense)
    qs = (
        Request.objects.filter(
            tenant_id=expense.tenant_id,
            payment_type=Request.PAYMENT_TYPE_CARD,
            status=Request.STATUS_APPROVED,
            amount=expense.amount,
            currency=card_expense_currency(expense),
            expense_ref_id__isnull=True,
            created_at__date__gte=expense_date - dt.timedelta(days=PENDING_REQUEST_LOOKBACK_DAYS),
            created_at__date__lte=expense_date + dt.timedelta(days=PENDING_REQUEST_LOOKAHEAD_DAYS),
        )
        .filter(Q(expense_id__isnull=True) | Q(expense_id=""))
        .exclude(id__in=list(exclude_ids))
    )
    purpose = str(preferred_purpose or "").strip()
    if purpose:
        qs = qs.annotate(
            _purpose_rank=Case(
                When(payment_purpose=purpose, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("_purpose_rank", "created_at", "id")
    else:
        qs = qs.order_by("created_at", "id")
    return qs


def is_request_closable_by_card_expense(*, request_obj: Request, expense: CardExpense) -> bool:
    """Re-check a candidate (under lock when closing, without lock in dry-run)."""
    if request_obj.status != Request.STATUS_APPROVED:
        return False
    if request_obj.payment_type != Request.PAYMENT_TYPE_CARD or request_obj.tenant_id != expense.tenant_id:
        return False
    if request_obj.expense_ref_id is not None or (request_obj.expense_id or ""):
        return False
    if request_obj.amount != expense.amount or request_obj.currency != card_expense_currency(expense):
        return False
    if payment_step_suppression_reason(request_obj=request_obj):
        # Another module (e.g. payroll) owns closing this payment step.
        return False
    try:
        check_request_mutation(request_obj=request_obj, attrs={"status": Request.STATUS_PAYED})
    except ValidationError:
        return False
    return True


def find_closable_pending_request(
    *,
    expense: CardExpense,
    preferred_purpose: str,
    exclude_ids=frozenset(),
) -> Request | None:
    """Read-only pick used by dry-run; mirrors close_pending_request_for_card_expense."""
    candidates = pending_card_request_candidates(
        expense=expense, preferred_purpose=preferred_purpose, exclude_ids=exclude_ids
    )[:PENDING_REQUEST_MAX_CANDIDATES]
    for request_obj in candidates:
        if is_request_closable_by_card_expense(request_obj=request_obj, expense=expense):
            return request_obj
    return None


def close_pending_request_for_card_expense(
    *,
    expense: CardExpense,
    preferred_purpose: str,
    system_user,
    config=None,
) -> Request | None:
    """
    Must run inside the caller's transaction with `expense` already locked.
    Returns the closed request or None when there is no closable candidate.
    """
    candidate_ids = list(
        pending_card_request_candidates(expense=expense, preferred_purpose=preferred_purpose).values_list(
            "id", flat=True
        )[:PENDING_REQUEST_MAX_CANDIDATES]
    )
    request_obj = None
    for candidate_id in candidate_ids:
        locked = Request.objects.select_for_update(of=("self",)).filter(pk=candidate_id).first()
        if locked is not None and is_request_closable_by_card_expense(request_obj=locked, expense=expense):
            request_obj = locked
            break
    if request_obj is None:
        return None

    expense_date = card_expense_local_date(expense)
    request_obj.expense_ref_id = expense.pk
    request_obj.expense_ref_target = Request.EXPENSE_REF_TARGET_CARD
    request_obj.expense_id = str(expense.pk)
    request_obj.payed_at = date_to_payed_at(expense_date)
    update_fields = ["expense_ref_id", "expense_ref_target", "expense_id", "payed_at"]
    if request_obj.expense_year is None:
        request_obj.expense_year = expense_date.year
        request_obj.expense_month = expense_date.month
        request_obj.expense_day = expense_date.day
        update_fields.extend(["expense_year", "expense_month", "expense_day"])
    request_obj.save(update_fields=update_fields)

    comment = pending_request_close_comment(expense, config=config)
    RequestComment.objects.create(request=request_obj, created_by=system_user, body=comment)

    # Last step: it edits Telegram cards over HTTP, nothing after it may fail.
    status = complete_request_payment_by_system(request_obj=request_obj, comment=comment)
    if status != Request.STATUS_PAYED:
        logger.info(
            "card_expense_pending_request_close: request not PAYED after closing request_id=%s "
            "expense_id=%s status=%s",
            request_obj.pk,
            expense.pk,
            status,
        )
    request_obj.refresh_from_db()
    return request_obj
