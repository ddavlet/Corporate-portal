"""Extension point: handlers run after a receipt is confirmed and the revenue is committed."""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

ReceiptConfirmedHandler = Callable[..., None]

RECEIPT_CONFIRMED_HANDLERS: tuple[ReceiptConfirmedHandler, ...] = ()


def register_receipt_confirmed_handler(handler: ReceiptConfirmedHandler) -> None:
    global RECEIPT_CONFIRMED_HANDLERS
    if handler not in RECEIPT_CONFIRMED_HANDLERS:
        RECEIPT_CONFIRMED_HANDLERS = (*RECEIPT_CONFIRMED_HANDLERS, handler)


def dispatch_receipt_confirmed(*, receipt) -> None:
    for handler in RECEIPT_CONFIRMED_HANDLERS:
        try:
            handler(receipt=receipt)
        except Exception:
            logger.exception(
                "receipt_confirmed handler failed handler=%s receipt_id=%s",
                getattr(handler, "__name__", repr(handler)),
                receipt.pk,
            )
