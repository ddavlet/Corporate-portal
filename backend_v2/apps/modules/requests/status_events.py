from __future__ import annotations

import logging
from collections.abc import Callable

from django.db import transaction

from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)

RequestPayedEventHandler = Callable[[Request], None]

REQUEST_PAYED_EVENT_HANDLERS: tuple[RequestPayedEventHandler, ...] = ()


def register_request_payed_event_handler(handler: RequestPayedEventHandler) -> None:
    global REQUEST_PAYED_EVENT_HANDLERS
    if handler not in REQUEST_PAYED_EVENT_HANDLERS:
        REQUEST_PAYED_EVENT_HANDLERS = (*REQUEST_PAYED_EVENT_HANDLERS, handler)


def dispatch_request_payed_event_handlers(*, request_obj: Request) -> None:
    """
    Run PAYED status handlers without breaking the approval flow on handler errors.
    """
    for handler in REQUEST_PAYED_EVENT_HANDLERS:
        try:
            handler(request_obj=request_obj)
        except Exception:
            logger.exception(
                "request_payed_event handler failed handler=%s request_id=%s tenant_id=%s",
                getattr(handler, "__name__", repr(handler)),
                request_obj.id,
                request_obj.tenant_id,
            )


RequestRejectedEventHandler = Callable[[Request], None]

REQUEST_REJECTED_EVENT_HANDLERS: tuple[RequestRejectedEventHandler, ...] = ()


def register_request_rejected_event_handler(handler: RequestRejectedEventHandler) -> None:
    global REQUEST_REJECTED_EVENT_HANDLERS
    if handler not in REQUEST_REJECTED_EVENT_HANDLERS:
        REQUEST_REJECTED_EVENT_HANDLERS = (*REQUEST_REJECTED_EVENT_HANDLERS, handler)


def dispatch_request_rejected_event_handlers(*, request_obj: Request) -> None:
    """
    Run REJECTED status handlers without breaking the approval flow on handler errors.

    Each handler runs inside its own savepoint (`transaction.atomic()`), so a DB
    error raised by a handler (e.g. IntegrityError) rolls back only that handler's
    work instead of aborting the caller's outer transaction (which would otherwise
    leave Postgres in a failed-transaction state and break the REJECTED status save).
    """
    for handler in REQUEST_REJECTED_EVENT_HANDLERS:
        try:
            with transaction.atomic():
                handler(request_obj=request_obj)
        except Exception:
            logger.exception(
                "request_rejected_event handler failed handler=%s request_id=%s tenant_id=%s",
                getattr(handler, "__name__", repr(handler)),
                request_obj.id,
                request_obj.tenant_id,
            )
