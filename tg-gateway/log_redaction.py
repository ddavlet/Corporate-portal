"""
Log redaction: keep Telegram bot tokens out of service logs.

Bot tokens leak through third-party loggers:
  - httpx:          "HTTP Request: POST https://api.telegram.org/bot<TOKEN>/sendMessage"
  - uvicorn.access: "POST /v1/messaging/webhook/<TOKEN> HTTP/1.1" 200

install_log_redaction() quiets httpx/httpcore to WARNING and attaches a filter
that masks tokens in every remaining record of those loggers and the gateway's own.
"""
from __future__ import annotations

import logging
import re

# Telegram bot token: "<numeric bot id>:<35-char secret>".
_TOKEN_RE = re.compile(r"(\d{5,}):[A-Za-z0-9_-]{30,}")
_MASK = r"\1:***"

# Loggers whose records may carry a token in the message or args.
REDACTED_LOGGERS = ("httpx", "httpcore", "uvicorn.access", "uvicorn.error", "main", "__main__", "db")
# Chatty transport loggers: their INFO lines are pure request URLs — drop them.
QUIET_LOGGERS = ("httpx", "httpcore")


def redact(text: str) -> str:
    return _TOKEN_RE.sub(_MASK, text)


def _redact_arg(arg):
    if isinstance(arg, str):
        return redact(arg)
    if isinstance(arg, (int, float, bool)) or arg is None:
        return arg
    # Exceptions, httpx.URL, etc.: stringify only if the token actually appears.
    text = str(arg)
    masked = redact(text)
    return masked if masked != text else arg


class BotTokenRedactingFilter(logging.Filter):
    """Masks bot tokens in record.msg and record.args; never drops records.

    Args are redacted element-wise (not pre-formatted) because uvicorn's
    AccessFormatter reads record.args by position.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _redact_arg(v) for k, v in record.args.items()}
        return True


_FILTER = BotTokenRedactingFilter()


def install_log_redaction() -> None:
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in REDACTED_LOGGERS:
        logger = logging.getLogger(name)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)
