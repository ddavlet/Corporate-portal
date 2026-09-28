"""Re-send approval cards that were never delivered to Telegram.

`dispatch_pending_approvals` silently skips an approver when the gateway/Telegram
refuses the message (e.g. the approver never pressed /start in the bot) and leaves
the approval pending *without* a `telegram_message`. Nothing retries it afterwards
unless another approver on the request makes a decision, so the request can sit
forever waiting for a person who was never notified.

This module finds such requests and re-runs the regular routing for them. It reuses
`route_request_approvals` (the same entry point a decision goes through), so the
"active step" rules stay in one place and this code never re-implements them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from django.contrib.auth import get_user_model

from apps.modules.requests.approval_workflow import route_request_approvals
from apps.modules.requests.models import Approval, Request, RequestComment
from apps.modules.telegram_approvals.services import _current_pending_step

logger = logging.getLogger(__name__)

User = get_user_model()

# Statuses in which a request is waiting on approvers and a card can be dispatched.
_ACTIVE_STATUSES = (
    Request.STATUS_PROGRESS_1,
    Request.STATUS_PROGRESS_2,
    Request.STATUS_PROGRESS_3,
    Request.STATUS_PROGRESS_4,
    Request.STATUS_PROGRESS_5,
    Request.STATUS_APPROVED,
)


@dataclass
class RedispatchOutcome:
    request_id: int
    tenant_id: int
    payment_type: str
    status: str
    # Approvals that had no card before the run / that got one during it.
    unsent_before: list[Approval] = field(default_factory=list)
    sent_approval_ids: list[int] = field(default_factory=list)
    error: str = ""

    @property
    def still_unsent(self) -> list[Approval]:
        sent = set(self.sent_approval_ids)
        return [a for a in self.unsent_before if a.pk not in sent]


def unsent_active_approvals(request_obj: Request) -> list[Approval]:
    """Approvals `dispatch_pending_approvals` would try to send right now for this request.

    Mirrors its selection: current step only, pending, no card yet, has a recipient; for an
    APPROVED request only the payment step is dispatched.
    """
    step = _current_pending_step(request_obj)
    if step is None:
        return []
    qs = Approval.objects.filter(
        request_id=request_obj.pk,
        step=step,
        decision=Approval.DECISION_PENDING,
        telegram_message__isnull=True,
        approver_recipient_id__isnull=False,
    )
    if request_obj.status == Request.STATUS_APPROVED:
        qs = qs.filter(step_type=Approval.STEP_TYPE_PAYMENT)
    return list(qs.select_related("approver_user").order_by("id"))


def find_requests_with_unsent_approvals(
    *,
    tenant_ids: Iterable[int] | None = None,
    payment_types: Iterable[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[tuple[Request, list[Approval]]]:
    """Requests that are waiting on a card which was never sent, oldest first.

    `date_from` / `date_to` are inclusive and apply to the request's `submitted_at` date.
    """
    candidates = Request.objects.filter(
        status__in=_ACTIVE_STATUSES,
        approvals__decision=Approval.DECISION_PENDING,
        approvals__telegram_message__isnull=True,
        approvals__approver_recipient_id__isnull=False,
    )
    if tenant_ids:
        candidates = candidates.filter(tenant_id__in=list(tenant_ids))
    if payment_types:
        candidates = candidates.filter(payment_type__in=list(payment_types))
    if date_from is not None:
        candidates = candidates.filter(submitted_at__date__gte=date_from)
    if date_to is not None:
        candidates = candidates.filter(submitted_at__date__lte=date_to)

    found: list[tuple[Request, list[Approval]]] = []
    for request_obj in candidates.distinct().order_by("submitted_at", "id"):
        # The coarse query above also matches pending approvals on future steps; the exact
        # per-request check keeps only requests that are blocked on the *current* step.
        unsent = unsent_active_approvals(request_obj)
        if unsent:
            found.append((request_obj, unsent))
    return found


def _approver_label(approval: Approval) -> str:
    user = approval.approver_user
    return (getattr(user, "full_name", "") or user.username).strip()


def _leave_system_comment(*, request_obj: Request, sent: list[Approval]) -> None:
    system_user = User.objects.filter(pk=1).first()
    if system_user is None:
        return
    names = ", ".join(_approver_label(a) for a in sent)
    RequestComment.objects.create(
        request_id=request_obj.pk,
        created_by=system_user,
        body=(
            "Карточка согласования отправлена повторно автоматически: первая отправка не дошла "
            f"до согласующего ({names})."
        ),
    )


def redispatch_request(request_obj: Request, unsent: list[Approval]) -> RedispatchOutcome:
    """Run the regular routing for one request and report which cards actually went out."""
    outcome = RedispatchOutcome(
        request_id=request_obj.pk,
        tenant_id=request_obj.tenant_id,
        payment_type=request_obj.payment_type,
        status=request_obj.status,
        unsent_before=unsent,
    )
    try:
        route_request_approvals(request_obj=request_obj)
    except Exception as exc:
        logger.exception("redispatch_request: routing failed request_id=%s", request_obj.pk)
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome

    delivered = set(
        Approval.objects.filter(pk__in=[a.pk for a in unsent], telegram_message__isnull=False).values_list(
            "pk", flat=True
        )
    )
    outcome.sent_approval_ids = sorted(delivered)
    sent = [a for a in unsent if a.pk in delivered]
    if sent:
        _leave_system_comment(request_obj=request_obj, sent=sent)
    return outcome
