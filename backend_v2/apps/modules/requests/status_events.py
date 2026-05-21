from __future__ import annotations

import logging
from collections.abc import Callable

from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)

RequestPayedEventHandler = Callable[[Request], None]

REQUEST_PAYED_EVENT_HANDLERS: tuple[RequestPayedEventHandler, ...] = ()


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
