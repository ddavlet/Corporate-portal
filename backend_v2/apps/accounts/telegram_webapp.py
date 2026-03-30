"""
Validate Telegram Mini App initData (query string) per:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl


class TelegramWebAppDataError(ValueError):
    pass


def validate_webapp_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
) -> dict[str, str]:
    """
    Returns parsed flat fields from init_data (e.g. auth_date, query_id, user JSON string).
    Raises TelegramWebAppDataError if invalid, expired, or missing user.
    """
    if not (init_data or "").strip():
        raise TelegramWebAppDataError("init_data is empty")
    token = (bot_token or "").strip()
    if not token:
        raise TelegramWebAppDataError("bot token is not configured")

    # parse_qsl preserves order; build dict (last duplicate key wins — rare)
    pairs = parse_qsl(init_data, keep_blank_values=True)
    flat: dict[str, str] = {}
    for k, v in pairs:
        flat[k] = v

    received_hash = flat.pop("hash", None)
    if not received_hash:
        raise TelegramWebAppDataError("missing hash")

    # Новые клиенты добавляют `signature` (Ed25519). Для поля `hash` (HMAC) встречаются оба варианта:
    # — data-check-string без `signature` (классика);
    # — со всеми полями кроме `hash`, включая `signature` (как @tma.js/init-data-node).
    without_sig = {k: v for k, v in flat.items() if k != "signature"}

    def _data_check(fields: dict[str, str]) -> str:
        return "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))

    secret_key = hmac.new(
        b"WebAppData",
        token.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    def _hex_hmac(data_check: str) -> str:
        return hmac.new(secret_key, data_check.encode("utf-8"), hashlib.sha256).hexdigest()

    h_no_sig = _hex_hmac(_data_check(without_sig))
    h_with_sig = _hex_hmac(_data_check(flat))
    if not (
        hmac.compare_digest(h_no_sig, received_hash)
        or hmac.compare_digest(h_with_sig, received_hash)
    ):
        raise TelegramWebAppDataError("invalid init_data signature")

    auth_raw = without_sig.get("auth_date")
    if not auth_raw:
        raise TelegramWebAppDataError("missing auth_date")
    try:
        auth_ts = int(auth_raw)
    except ValueError as exc:
        raise TelegramWebAppDataError("invalid auth_date") from exc
    if auth_ts <= 0 or (time.time() - auth_ts) > max_age_seconds:
        raise TelegramWebAppDataError("auth_date expired or invalid")

    if "user" not in without_sig:
        raise TelegramWebAppDataError("missing user")

    return without_sig


def parse_telegram_user_json(user_field: str) -> dict[str, Any]:
    try:
        out = json.loads(user_field)
    except json.JSONDecodeError as exc:
        raise TelegramWebAppDataError("invalid user json") from exc
    if not isinstance(out, dict) or "id" not in out:
        raise TelegramWebAppDataError("user.id missing")
    return out


def telegram_user_id_from_validated(flat: dict[str, str]) -> int:
    user_obj = parse_telegram_user_json(flat["user"])
    uid = user_obj.get("id")
    if not isinstance(uid, int):
        raise TelegramWebAppDataError("user.id must be an integer")
    return uid
