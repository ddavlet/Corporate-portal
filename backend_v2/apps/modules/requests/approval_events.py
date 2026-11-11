"""Event "approvals of a request may have changed" (e.g. for Web Push of action items).

`route_request_approvals` is the single point every step change goes through (portal and
Telegram decisions via `confirm_approval_by_id`, system payment, edits, resend), so it is
decorated with `notifies_approvals_changed`. Handlers run after the outer transaction commits
and never break the approval flow.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from django.db import transaction

logger = logging.getLogger(__name__)

KIND_REQUEST = "request"

# handler(*, tenant_id: int, kind: str, object_id: int) -> None
ApprovalsChangedHandler = Callable[..., None]

REQUEST_APPROVALS_CHANGED_HANDLERS: tuple[ApprovalsChangedHandler, ...] = ()


def register_request_approvals_changed_handler(handler: ApprovalsChangedHandler) -> None:
    global REQUEST_APPROVALS_CHANGED_HANDLERS
    if handler not in REQUEST_APPROVALS_CHANGED_HANDLERS:
        REQUEST_APPROVALS_CHANGED_HANDLERS = (*REQUEST_APPROVALS_CHANGED_HANDLERS, handler)


def dispatch_request_approvals_changed(*, tenant_id: int, kind: str, object_id: int) -> None:
    for handler in REQUEST_APPROVALS_CHANGED_HANDLERS:
        try:
            handler(tenant_id=tenant_id, kind=kind, object_id=object_id)
        except Exception:
            logger.exception(
                "request_approvals_changed handler failed handler=%s kind=%s object_id=%s tenant_id=%s",
                getattr(handler, "__name__", repr(handler)),
                kind,
                object_id,
                tenant_id,
            )


def notifies_approvals_changed(get_ref: Callable[[dict], tuple[int, str, int] | None]):
    """Schedule `dispatch_request_approvals_changed` after the decorated call, however it ends.

    `get_ref(kwargs)` returns `(tenant_id, kind, object_id)` or None. Inside a transaction the
    dispatch waits for the commit (dropped on rollback); in autocommit it runs right away.
    The decorated function's body and result are untouched.
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
    if not REQUEST_APPROVALS_CHANGED_HANDLERS:
        return
    try:
        ref = get_ref(kwargs)
        if ref is None:
            return
        tenant_id, kind, object_id = ref
        transaction.on_commit(
            functools.partial(
                dispatch_request_approvals_changed, tenant_id=tenant_id, kind=kind, object_id=object_id
            ),
            robust=True,
        )
    except Exception:
        logger.exception("request_approvals_changed scheduling failed")


def request_ref(kwargs: dict) -> tuple[int, str, int] | None:
    request_obj = kwargs.get("request_obj")
    if request_obj is None or request_obj.pk is None:
        return None
    return request_obj.tenant_id, KIND_REQUEST, request_obj.pk
