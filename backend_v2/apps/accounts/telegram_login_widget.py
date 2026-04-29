from __future__ import annotations

import hashlib
import hmac
import time


class TelegramLoginWidgetDataError(ValueError):
    pass


def validate_login_widget_auth_data(
    auth_data: dict[str, str],
    bot_token: str,
    *,
    max_age_seconds: int = 86400,
) -> dict[str, str]:
    if not isinstance(auth_data, dict):
        raise TelegramLoginWidgetDataError("auth_data must be an object")

    token = (bot_token or "").strip()
    if not token:
        raise TelegramLoginWidgetDataError("bot token is not configured")

    received_hash = str(auth_data.get("hash", "")).strip()
    if not received_hash:
        raise TelegramLoginWidgetDataError("missing hash")

    fields: dict[str, str] = {}
    for key, value in auth_data.items():
        if key == "hash":
            continue
        value_s = str(value or "").strip()
        if value_s:
            fields[key] = value_s

    if "id" not in fields:
        raise TelegramLoginWidgetDataError("missing id")
    if "auth_date" not in fields:
        raise TelegramLoginWidgetDataError("missing auth_date")

    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret_key = hashlib.sha256(token.encode("utf-8")).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise TelegramLoginWidgetDataError("invalid auth_data signature")

    try:
        auth_ts = int(fields["auth_date"])
    except ValueError as exc:
        raise TelegramLoginWidgetDataError("invalid auth_date") from exc
    if auth_ts <= 0 or (time.time() - auth_ts) > max_age_seconds:
        raise TelegramLoginWidgetDataError("auth_date expired or invalid")

    return fields


def telegram_user_id_from_login_widget(fields: dict[str, str]) -> int:
    try:
        return int(fields["id"])
    except (KeyError, ValueError) as exc:
        raise TelegramLoginWidgetDataError("invalid id") from exc
