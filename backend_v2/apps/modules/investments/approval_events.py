"""Event "approvals of an investment object may have changed" (e.g. for Web Push of action items).

`route_invest_return_approvals` and `route_project_investment_approvals` are the points every
step change goes through (the `confirm_*_approval_by_id` decisions call them too), so they are
decorated with `notifies_approvals_changed`. Handlers run after the outer transaction commits
(right away in autocommit) and never break the approval flow.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from django.db import transaction

logger = logging.getLogger(__name__)

KIND_INVEST_RETURN = "invest_return"
KIND_PROJECT_INVESTMENT = "project_investment"

# handler(*, tenant_id: int, kind: str, object_id: int) -> None
ApprovalsChangedHandler = Callable[..., None]

INVESTMENT_APPROVALS_CHANGED_HANDLERS: tuple[ApprovalsChangedHandler, ...] = ()


def register_investment_approvals_changed_handler(handler: ApprovalsChangedHandler) -> None:
    global INVESTMENT_APPROVALS_CHANGED_HANDLERS
    if handler not in INVESTMENT_APPROVALS_CHANGED_HANDLERS:
        INVESTMENT_APPROVALS_CHANGED_HANDLERS = (*INVESTMENT_APPROVALS_CHANGED_HANDLERS, handler)


def dispatch_investment_approvals_changed(*, tenant_id: int, kind: str, object_id: int) -> None:
    for handler in INVESTMENT_APPROVALS_CHANGED_HANDLERS:
        try:
            handler(tenant_id=tenant_id, kind=kind, object_id=object_id)
        except Exception:
            logger.exception(
                "investment_approvals_changed handler failed handler=%s kind=%s object_id=%s tenant_id=%s",
                getattr(handler, "__name__", repr(handler)),
                kind,
                object_id,
                tenant_id,
            )


def notifies_approvals_changed(get_ref: Callable[[dict], tuple[int, str, int] | None]):
    """Schedule `dispatch_investment_approvals_changed` after the decorated call, however it ends.

    `get_ref(kwargs)` returns `(tenant_id, kind, object_id)` or None.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            finally:
                _schedule_dispatch(get_ref, kwargs)

        return wrapper

    return decorator


def _schedule_dispatch(get_ref, kwargs) -> None:
    if not INVESTMENT_APPROVALS_CHANGED_HANDLERS:
        return
    try:
        ref = get_ref(kwargs)
        if ref is None:
            return
        tenant_id, kind, object_id = ref
        transaction.on_commit(
            functools.partial(
                dispatch_investment_approvals_changed, tenant_id=tenant_id, kind=kind, object_id=object_id
            ),
            robust=True,
        )
    except Exception:
        logger.exception("investment_approvals_changed scheduling failed")


def invest_return_ref(kwargs: dict) -> tuple[int, str, int] | None:
    invest_return = kwargs.get("invest_return")
    if invest_return is None or invest_return.pk is None:
        return None
    return invest_return.tenant_id, KIND_INVEST_RETURN, invest_return.pk


def project_investment_ref(kwargs: dict) -> tuple[int, str, int] | None:
    project_investment = kwargs.get("project_investment")
    if project_investment is None or project_investment.pk is None:
        return None
    return project_investment.tenant_id, KIND_PROJECT_INVESTMENT, project_investment.pk
