from __future__ import annotations

import logging
from collections.abc import Callable

from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)

RequestPayedEventHandler = Callable[[Request], None]

REQUEST_PAYED_EVENT_HANDLERS: tuple[RequestPayedEventHandler, ...] = ()


def register_request_payed_event_handler(handler: RequestPayedEventHandler) -> None:
    global REQUEST_PAYED_EVENT_HANDLERS
    if handler not in REQUEST_PAYED_EVENT_HANDLERS:
        REQUEST_PAYED_EVENT_HANDLERS = (*REQUEST_PAYED_EVENT_HANDLERS, handler)


def _request_payed_event_handlers() -> tuple[RequestPayedEventHandler, ...]:
    handlers = REQUEST_PAYED_EVENT_HANDLERS
    try:
        from django.apps import apps

        if apps.is_installed("apps.modules.n8n_integration"):
            from apps.modules.n8n_integration.event_handlers import notify_request_payed

            if notify_request_payed not in handlers:
                handlers = (*handlers, notify_request_payed)
    except Exception:
        logger.exception("Failed to resolve request_payed_event handlers")
    return handlers


def dispatch_request_payed_event_handlers(*, request_obj: Request) -> None:
    """
    Run PAYED status handlers without breaking the approval flow on handler errors.
    """
    for handler in _request_payed_event_handlers():
        try:
            handler(request_obj=request_obj)
        except Exception:
            logger.exception(
                "request_payed_event handler failed handler=%s request_id=%s tenant_id=%s",
                getattr(handler, "__name__", repr(handler)),
                request_obj.id,
                request_obj.tenant_id,
            )
