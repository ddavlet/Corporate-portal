"""
Bot tokens must never reach service logs (httpx request URLs, uvicorn access lines).

Run:
    pytest test_log_redaction.py -v
"""
import logging
import os

os.environ.setdefault("DATABASE_URL", "")

import main  # noqa: E402,F401 — importing main installs redaction
from log_redaction import BotTokenRedactingFilter, redact  # noqa: E402

TOKEN = "7123456789:AAHfakeTokenForTests_abcdefghijklmnop"  # fake, Telegram-shaped
SECRET = TOKEN.split(":", 1)[1]


def test_redact_masks_secret_keeps_bot_id():
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert redact(url) == "https://api.telegram.org/bot7123456789:***/sendMessage"


def test_httpx_info_suppressed_after_main_import():
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_gateway_own_info_logs_kept(caplog):
    with caplog.at_level(logging.INFO, logger="main"):
        logging.getLogger("main").info("dispatch action=%s ok=%s", "send", True)
    assert "dispatch action=send ok=True" in caplog.text


def test_httpx_warning_with_token_is_masked(caplog):
    with caplog.at_level(logging.WARNING, logger="httpx"):
        logging.getLogger("httpx").warning(
            'HTTP Request: %s %s "%s"', "POST", f"https://api.telegram.org/bot{TOKEN}/sendMessage", "500"
        )
    assert SECRET not in caplog.text
    assert "bot7123456789:***/sendMessage" in caplog.text


def test_uvicorn_access_webhook_path_masked_args_stay_positional():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "POST", f"/v1/messaging/webhook/{TOKEN}", "1.1", 200),
        None,
    )
    assert logging.getLogger("uvicorn.access").filter(record)
    assert isinstance(record.args, tuple) and record.args[4] == 200
    assert SECRET not in record.getMessage()
    assert "/v1/messaging/webhook/7123456789:***" in record.getMessage()


def test_exception_arg_with_token_masked():
    exc = RuntimeError(f"Client error for url https://api.telegram.org/bot{TOKEN}/getMe")
    record = logging.LogRecord("main", logging.ERROR, __file__, 0, "dispatch error: %s", (exc,), None)
    BotTokenRedactingFilter().filter(record)
    assert SECRET not in record.getMessage()
