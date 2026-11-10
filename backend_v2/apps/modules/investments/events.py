"""Extension point: handlers run after an investor payout (InvestReturn) becomes confirmed and is committed."""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

InvestReturnConfirmedHandler = Callable[..., None]

INVEST_RETURN_CONFIRMED_HANDLERS: tuple[InvestReturnConfirmedHandler, ...] = ()


def register_invest_return_confirmed_handler(handler: InvestReturnConfirmedHandler) -> None:
    global INVEST_RETURN_CONFIRMED_HANDLERS
    if handler not in INVEST_RETURN_CONFIRMED_HANDLERS:
        INVEST_RETURN_CONFIRMED_HANDLERS = (*INVEST_RETURN_CONFIRMED_HANDLERS, handler)


def dispatch_invest_return_confirmed(*, invest_return) -> None:
    # Handlers are informational: a failing one must not affect the confirmation or the other handlers.
    for handler in INVEST_RETURN_CONFIRMED_HANDLERS:
        try:
            handler(invest_return=invest_return)
        except Exception:
            logger.exception(
                "invest_return_confirmed handler failed handler=%s invest_return_id=%s",
                getattr(handler, "__name__", repr(handler)),
                invest_return.pk,
            )
