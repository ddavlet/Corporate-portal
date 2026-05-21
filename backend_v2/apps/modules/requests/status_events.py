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


def _configured_request_payed_event_handlers() -> tuple[RequestPayedEventHandler, ...]:
    from django.apps import apps
    from django.utils.module_loading import import_string

    handlers = []
    for app_config in apps.get_app_configs():
        for handler_ref in getattr(app_config, "request_payed_event_handlers", ()):
            try:
                handler = import_string(handler_ref) if isinstance(handler_ref, str) else handler_ref
            except Exception:
                logger.exception(
                    "Failed to import request_payed_event handler app=%s handler=%r",
                    app_config.label,
                    handler_ref,
                )
                continue
            handlers.append(handler)
    return tuple(handlers)


def _request_payed_event_handlers() -> tuple[RequestPayedEventHandler, ...]:
    handlers = REQUEST_PAYED_EVENT_HANDLERS
    for handler in _configured_request_payed_event_handlers():
        if handler not in handlers:
            handlers = (*handlers, handler)
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
