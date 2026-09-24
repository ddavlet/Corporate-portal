"""
Registry of predicates that take the payment step of a request out of the normal
approval flow (no Telegram dispatch, no manual confirmation). A module that tracks
payment itself (payroll portal payouts) registers a predicate and later closes the
step via approval_workflow.complete_request_payment_by_system.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)

PaymentStepSuppressor = Callable[..., "str | None"]

PAYMENT_STEP_SUPPRESSORS: tuple[PaymentStepSuppressor, ...] = ()


def register_payment_step_suppressor(fn: PaymentStepSuppressor) -> None:
    global PAYMENT_STEP_SUPPRESSORS
    if fn not in PAYMENT_STEP_SUPPRESSORS:
        PAYMENT_STEP_SUPPRESSORS = (*PAYMENT_STEP_SUPPRESSORS, fn)


def payment_step_suppression_reason(*, request_obj: Request) -> str | None:
    for fn in PAYMENT_STEP_SUPPRESSORS:
        try:
            reason = fn(request_obj=request_obj)
        except Exception:
            logger.exception(
                "payment_step_suppressor failed fn=%s request_id=%s",
                getattr(fn, "__name__", repr(fn)),
                request_obj.id,
            )
            continue
        if reason:
            return reason
    return None
