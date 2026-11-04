"""
Unit tests for the Messaging Gateway (Telegram adapter).
No real credentials or database needed — all external calls are mocked.

Run:
    pytest test_gateway.py -v
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "")  # disables DB — log_event is a no-op

from fastapi.testclient import TestClient
from main import app  # noqa: E402

client = TestClient(app)

BOT       = "123:TEST"           # fake — never reaches Telegram
RECIPIENT = "12345"
TENANT    = "test-tenant"

BASE = {"bot_token": BOT, "tenant_id": TENANT, "recipient_id": RECIPIENT}
SEND = "/v1/messaging/send"
HOOK = "/v1/messaging/webhook/testtoken"


# ── Mock factories ────────────────────────────────────────────────────────────

def _tg_ok(message_id: int = 101):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True, "result": {"message_id": message_id}}
    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__  = AsyncMock(return_value=False)
    m.post = AsyncMock(return_value=mock_resp)
    return m


def _tg_delete_ok():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True, "result": True}
    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__  = AsyncMock(return_value=False)
    m.post = AsyncMock(return_value=mock_resp)
    return m


def _tg_err(description: str = "chat not found"):
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"ok": False, "description": description}
    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__  = AsyncMock(return_value=False)
    m.post = AsyncMock(return_value=mock_resp)
    return m


def _posted_body(mock_cls) -> dict:
    call_args = mock_cls.return_value.__aenter__.return_value.post.call_args
    return call_args.kwargs.get("json") or {}


def _posted_url(mock_cls) -> str:
    call_args = mock_cls.return_value.__aenter__.return_value.post.call_args
    return call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")


# ── Health ────────────────────────────────────────────────────────────────────

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "db" in data


# ── reply_to_message_id and typing ───────────────────────────────────────────

def test_send_with_reply_to_sets_reply_parameters():
    with patch("main._tg_post", new=AsyncMock(return_value={"ok": True, "result": {"message_id": 5}})) as m:
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "hi", "reply_to_message_id": 77})
    assert resp.status_code == 200
    body = m.call_args.args[2]
    assert body["reply_parameters"] == {"message_id": 77, "allow_sending_without_reply": True}


def test_send_without_reply_to_has_no_reply_parameters():
    with patch("main._tg_post", new=AsyncMock(return_value={"ok": True, "result": {"message_id": 5}})) as m:
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "hi"})
    assert resp.status_code == 200
    assert "reply_parameters" not in m.call_args.args[2]


def test_typing_action_calls_send_chat_action():
    with patch("main._tg_post", new=AsyncMock(return_value={"ok": True, "result": True})) as m:
        resp = client.post(SEND, json={**BASE, "action": "typing"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["message_id"] is None
    assert m.call_args.args[1] == "sendChatAction"
    assert m.call_args.args[2] == {"chat_id": int(RECIPIENT), "action": "typing"}


# ── Contract: response shape ──────────────────────────────────────────────────

def test_response_contains_tenant_recipient_message_id():
    with patch("httpx.AsyncClient", return_value=_tg_ok(101)):
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "Hello"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["tenant"] == TENANT
    assert data["recipient_id"] == RECIPIENT
    assert data["message_id"] == 101


def test_response_does_not_contain_bot_token():
    """bot_token must never appear in response or logs."""
    with patch("httpx.AsyncClient", return_value=_tg_ok()):
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "hi"})
    body = resp.text
    assert BOT not in body


def test_response_does_not_contain_old_chat_id_field():
    """chat_id was removed from response — only recipient_id is returned."""
    with patch("httpx.AsyncClient", return_value=_tg_ok()):
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "hi"})
    assert "chat_id" not in resp.json()


# ── Security: no auth token required ─────────────────────────────────────────

def test_no_token_still_accepted():
    """Gateway has no token auth — any caller on the internal network is trusted."""
    with patch("httpx.AsyncClient", return_value=_tg_ok()):
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "hi"})
    assert resp.status_code == 200


# ── Contract: field mapping to Telegram ──────────────────────────────────────

def test_recipient_id_mapped_to_tg_chat_id():
    """Universal recipient_id (str) must be converted to int for Telegram."""
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post(SEND, json={**BASE, "action": "send", "text": "hi"})
    body = _posted_body(m)
    assert body["chat_id"] == int(RECIPIENT)


def test_format_html_maps_to_tg_parse_mode():
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post(SEND, json={**BASE, "action": "send", "text": "hi", "format": "html"})
    assert _posted_body(m)["parse_mode"] == "HTML"


def test_format_plain_omits_parse_mode():
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post(SEND, json={**BASE, "action": "send", "text": "hi", "format": "plain"})
    assert _posted_body(m).get("parse_mode") is None


# ── send ──────────────────────────────────────────────────────────────────────

def test_send_no_reply_markup():
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post(SEND, json={**BASE, "action": "send", "text": "plain"})
    assert "reply_markup" not in _posted_body(m)


# ── send_interactive — dynamic buttons ───────────────────────────────────────

def test_send_interactive_converts_buttons_to_tg_format():
    """Universal {label, value} must be converted to Telegram {text, callback_data}."""
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post(SEND, json={**BASE, "action": "send_interactive", "text": "Approve?",
            "buttons": [[
                {"label": "✅ Approve", "value": "v2_1:a"},
                {"label": "❌ Reject",  "value": "v2_1:r"},
            ]]})
    kb = _posted_body(m)["reply_markup"]["inline_keyboard"]
    assert kb[0][0] == {"text": "✅ Approve", "callback_data": "v2_1:a"}
    assert kb[0][1] == {"text": "❌ Reject",  "callback_data": "v2_1:r"}


def test_send_interactive_any_button_labels():
    for label in ["💰 Pay", "Accept", "Confirm", "🚫 Cancel"]:
        with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
            client.post(SEND, json={**BASE, "action": "send_interactive", "text": "?",
                "buttons": [[{"label": label, "value": "x"}]]})
        assert _posted_body(m)["reply_markup"]["inline_keyboard"][0][0]["text"] == label


def test_send_interactive_empty_buttons_omits_markup():
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post(SEND, json={**BASE, "action": "send_interactive", "text": "hi", "buttons": []})
    assert "reply_markup" not in _posted_body(m)


# ── edit ──────────────────────────────────────────────────────────────────────

def test_edit_calls_editMessageText():
    with patch("httpx.AsyncClient", return_value=_tg_ok(555)) as m:
        resp = client.post(SEND, json={**BASE, "action": "edit", "message_id": 555, "text": "Edited"})
    assert resp.status_code == 200
    assert "editMessageText" in _posted_url(m)


def test_edit_empty_buttons_removes_markup():
    with patch("httpx.AsyncClient", return_value=_tg_ok(555)) as m:
        client.post(SEND, json={**BASE, "action": "edit", "message_id": 555, "text": "no btns", "buttons": []})
    assert "reply_markup" not in _posted_body(m)


def test_edit_no_message_id_returns_400():
    with patch("httpx.AsyncClient", return_value=_tg_ok()):
        resp = client.post(SEND, json={**BASE, "action": "edit", "text": "no id"})
    assert resp.status_code == 400


def test_edit_not_modified_returns_200():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "description": "Bad Request: message is not modified"}
    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__  = AsyncMock(return_value=False)
    m.post = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient", return_value=m):
        resp = client.post(SEND, json={**BASE, "action": "edit", "message_id": 999, "text": "same"})
    assert resp.status_code == 200


# ── edit_interactive ──────────────────────────────────────────────────────────

def test_edit_interactive_replaces_buttons():
    with patch("httpx.AsyncClient", return_value=_tg_ok(777)) as m:
        resp = client.post(SEND, json={**BASE, "action": "edit_interactive",
            "message_id": 777, "text": "updated",
            "buttons": [[{"label": "New", "value": "new"}]]})
    assert resp.status_code == 200
    kb = _posted_body(m)["reply_markup"]["inline_keyboard"]
    assert kb[0][0] == {"text": "New", "callback_data": "new"}


def test_edit_interactive_no_message_id_returns_400():
    with patch("httpx.AsyncClient", return_value=_tg_ok()):
        resp = client.post(SEND, json={**BASE, "action": "edit_interactive", "text": "no id"})
    assert resp.status_code == 400


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_calls_deleteMessage():
    with patch("httpx.AsyncClient", return_value=_tg_delete_ok()) as m:
        resp = client.post(SEND, json={**BASE, "action": "delete", "message_id": 888})
    assert resp.status_code == 200
    assert "deleteMessage" in _posted_url(m)


def test_delete_no_message_id_returns_400():
    with patch("httpx.AsyncClient", return_value=_tg_delete_ok()):
        resp = client.post(SEND, json={**BASE, "action": "delete"})
    assert resp.status_code == 400


# ── Removed actions must return 422 ──────────────────────────────────────────

def test_old_send_message_action_rejected():
    resp = client.post(SEND, json={**BASE, "action": "send_message", "text": "hi"})
    assert resp.status_code == 422


def test_old_edit_message_action_rejected():
    resp = client.post(SEND, json={**BASE, "action": "edit_message", "message_id": 1, "text": "hi"})
    assert resp.status_code == 422


def test_old_delete_message_button_rejected():
    resp = client.post(SEND, json={**BASE, "action": "delete_message_button", "message_id": 1})
    assert resp.status_code == 422


# ── Telegram error → 502 ─────────────────────────────────────────────────────

def test_telegram_chat_not_found_returns_502():
    with patch("httpx.AsyncClient", return_value=_tg_err("chat not found")):
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "hi"})
    assert resp.status_code == 502
    assert "chat not found" in resp.json()["detail"]


def test_telegram_bot_blocked_returns_502():
    with patch("httpx.AsyncClient", return_value=_tg_err("Forbidden: bot was blocked by the user")):
        resp = client.post(SEND, json={**BASE, "action": "send", "text": "hi"})
    assert resp.status_code == 502


# ── Validation ────────────────────────────────────────────────────────────────

def test_unknown_action_returns_422():
    resp = client.post(SEND, json={**BASE, "action": "fly_to_moon", "text": "hi"})
    assert resp.status_code == 422


def test_missing_recipient_id_returns_422():
    resp = client.post(SEND, json={"action": "send", "bot_token": BOT, "text": "hi"})
    assert resp.status_code == 422


def test_missing_bot_token_returns_422():
    resp = client.post(SEND, json={"action": "send", "recipient_id": RECIPIENT, "text": "hi"})
    assert resp.status_code == 422


# ── Webhook: platform-neutral callback forward ────────────────────────────────

def test_webhook_non_interactive_returns_ok():
    resp = client.post(HOOK, json={"update_id": 1, "message": {"text": "hi"}})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_webhook_group_message_logs_chat_id(caplog):
    """Discovery: a group message should surface chat_id (negative) in logs."""
    import logging
    caplog.set_level(logging.INFO, logger="main")
    resp = client.post(HOOK, json={
        "update_id": 10,
        "message": {
            "message_id": 1,
            "chat": {"id": -1001234567890, "type": "supergroup", "title": "My Group"},
            "from": {"id": 42, "username": "alice"},
            "text": "1 2 3",
        },
    })
    assert resp.status_code == 200
    assert any(
        "discovery" in r.message and "chat_id=-1001234567890" in r.message
        for r in caplog.records
    ), "expected discovery log line with negative chat_id"


def test_webhook_my_chat_member_logs_chat_id(caplog):
    """Discovery: bot-added-to-group should surface chat_id + new member status."""
    import logging
    caplog.set_level(logging.INFO, logger="main")
    resp = client.post(HOOK, json={
        "update_id": 11,
        "my_chat_member": {
            "chat": {"id": -1009999999999, "type": "supergroup", "title": "Ops"},
            "from": {"id": 7, "username": "admin"},
            "new_chat_member": {"status": "member"},
        },
    })
    assert resp.status_code == 200
    assert any(
        "discovery" in r.message and "kind=my_chat_member" in r.message and "status=member" in r.message
        for r in caplog.records
    ), "expected my_chat_member discovery log line"


def test_webhook_callback_forwards_neutral_format():
    """Gateway must forward a platform-neutral event, not raw Telegram structure."""
    forward_payload = {}

    async def fake_post(url, json=None, **kwargs):
        nonlocal forward_payload
        forward_payload = json
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        return mock_resp

    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__  = AsyncMock(return_value=False)
    m.post = AsyncMock(side_effect=fake_post)

    with patch("main.BACKEND_URL", "http://backend/webhook"), \
         patch("httpx.AsyncClient", return_value=m):
        resp = client.post(HOOK, json={
            "update_id": 2,
            "callback_query": {
                "id": "abc", "data": "v2_42:a",
                "from": {"id": 789},
                "message": {"message_id": 456, "chat": {"id": 123456}},
            },
        })

    assert resp.status_code == 200
    # Must be flat, platform-neutral — no "update" or "callback_query" keys
    assert "update" not in forward_payload
    assert "callback_query" not in forward_payload
    assert forward_payload["event"] == "interaction"
    assert forward_payload["payload"] == "v2_42:a"
    assert forward_payload["user_id"] == "789"
    assert forward_payload["recipient_id"] == "123456"
    assert forward_payload["message_id"] == 456
    assert forward_payload["platform"] == "telegram"


def test_webhook_callback_no_backend_returns_ok():
    with patch("main.BACKEND_URL", ""):
        resp = client.post(HOOK, json={
            "update_id": 3,
            "callback_query": {
                "id": "xyz", "data": "v2_99:r",
                "from": {"id": 111},
                "message": {"message_id": 222, "chat": {"id": 333}},
            },
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_webhook_bank_ostatki_command_forwards_with_bot_id():
    """Known balance slash commands are forwarded as event=command with bot_id only."""
    forward_payload = {}

    async def fake_post(url, json=None, **kwargs):
        nonlocal forward_payload
        forward_payload = json
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""
        return mock_resp

    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__ = AsyncMock(return_value=False)
    m.post = AsyncMock(side_effect=fake_post)

    # HOOK path uses bot_token "testtoken" (no ':') → bot_id == "testtoken"
    with patch("main.BACKEND_URL", "http://backend/webhook"), \
         patch("httpx.AsyncClient", return_value=m):
        resp = client.post(
            "/v1/messaging/webhook/110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
            json={
                "update_id": 10,
                "message": {
                    "message_id": 55,
                    "text": "/bank_ostatki@MyBot",
                    "chat": {"id": -100123, "type": "supergroup", "title": "Ops"},
                    "from": {"id": 789012345, "username": "boss"},
                },
            },
        )

    assert resp.status_code == 200
    assert forward_payload["event"] == "command"
    assert forward_payload["payload"] == "bank_ostatki"
    assert forward_payload["user_id"] == "789012345"
    assert forward_payload["recipient_id"] == "-100123"
    assert forward_payload["message_id"] == 55
    assert forward_payload["bot_id"] == "110201543"
    assert ":" not in forward_payload["bot_id"]
    assert "AAHdq" not in str(forward_payload)


def test_webhook_unknown_slash_command_not_forwarded_as_command():
    """Unknown slash commands stay discovery-only and must not hit the business webhook."""
    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__ = AsyncMock(return_value=False)
    m.post = AsyncMock()

    with patch("main.BACKEND_URL", "http://backend/webhook"), \
         patch("main.BACKEND_EVENT_LOG_URL", ""), \
         patch("httpx.AsyncClient", return_value=m):
        resp = client.post(HOOK, json={
            "update_id": 11,
            "message": {
                "message_id": 56,
                "text": "/start",
                "chat": {"id": 1, "type": "private"},
                "from": {"id": 2},
            },
        })

    assert resp.status_code == 200
    assert m.post.call_count == 0


# ── Webhook: event=message (addressed messages) ──────────────────────────────

TOKEN_FULL = "110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
HOOK_FULL = f"/v1/messaging/webhook/{TOKEN_FULL}"


def _msg_update(text="hello", chat_type="private", chat_id=500, **extra):
    msg = {
        "message_id": 123,
        "chat": {"id": chat_id, "type": chat_type},
        "from": {"id": 42, "first_name": "Ann", "last_name": "Lee"},
        **extra,
    }
    if text is not None:
        msg["text"] = text
    return {"update_id": 1, "message": msg}


def _post_hook(update, username="MyBot"):
    """Post an update with backend forward and getMe mocked; return (resp, fwd_mock, log_mock)."""
    with patch("main.BACKEND_URL", "http://backend/webhook"), \
         patch("main.BACKEND_EVENT_LOG_URL", ""), \
         patch("main._bot_username", new=AsyncMock(return_value=username)), \
         patch("main._forward_backend_event", new=AsyncMock(return_value=(True, 200, None))) as fwd, \
         patch("main.db.log_event", new=AsyncMock()) as log:
        resp = client.post(HOOK_FULL, json=update)
    return resp, fwd, log


def test_private_text_forwarded_as_message_event():
    resp, fwd, _ = _post_hook(_msg_update("how much cash?"))
    assert resp.status_code == 200
    fwd.assert_awaited_once()
    assert fwd.await_args.args[0] == {
        "event": "message", "payload": "how much cash?", "user_id": "42",
        "recipient_id": "500", "message_id": 123, "platform": "telegram",
        "bot_id": "110201543", "chat_type": "private", "sender_name": "Ann Lee",
        "mentions_bot": False, "reply_to_message_id": None, "reply_to_text": "",
        "reply_to_from_id": "", "reply_to_is_bot": False,
    }


def test_private_command_still_uses_command_path():
    resp, fwd, _ = _post_hook(_msg_update("/bank_ostatki"))
    assert resp.status_code == 200
    fwd.assert_awaited_once()
    assert fwd.await_args.args[0]["event"] == "command"


def test_group_mention_forwarded_mentions_bot_true():
    upd = _msg_update(
        "@MyBot balance?", chat_type="supergroup", chat_id=-100,
        entities=[{"type": "mention", "offset": 0, "length": 6}],
    )
    resp, fwd, _ = _post_hook(upd)
    assert resp.status_code == 200
    sent = fwd.await_args.args[0]
    assert sent["event"] == "message"
    assert sent["mentions_bot"] is True
    assert sent["chat_type"] == "supergroup"


def test_group_reply_to_human_forwarded_reply_to_is_bot_false():
    upd = _msg_update(
        "and bank?", chat_type="group", chat_id=-100,
        reply_to_message={"message_id": 120, "text": "prev", "from": {"id": 7, "is_bot": False}},
    )
    resp, fwd, _ = _post_hook(upd)
    assert resp.status_code == 200
    sent = fwd.await_args.args[0]
    assert sent["mentions_bot"] is False
    assert sent["reply_to_message_id"] == 120
    assert sent["reply_to_text"] == "prev"
    assert sent["reply_to_from_id"] == "7"
    assert sent["reply_to_is_bot"] is False


def test_group_plain_message_not_forwarded_and_text_not_logged(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="main")
    resp, fwd, log = _post_hook(_msg_update("secret chatter", chat_type="supergroup", chat_id=-100))
    assert resp.status_code == 200
    fwd.assert_not_awaited()
    log.assert_awaited()
    for call in log.await_args_list:
        assert not call.kwargs.get("payload")
        assert "secret chatter" not in str(call)
    assert "secret chatter" not in caplog.text


def test_caption_used_when_no_text():
    upd = _msg_update(None, caption="photo caption")
    resp, fwd, _ = _post_hook(upd)
    assert fwd.await_args.args[0]["payload"] == "photo caption"


def test_message_without_text_ignored():
    resp, fwd, _ = _post_hook(_msg_update(None))
    assert resp.status_code == 200
    fwd.assert_not_awaited()


def test_get_me_cached_per_bot():
    import main
    main._bot_username_cache.clear()
    ok = AsyncMock(return_value={"ok": True, "result": {"username": "MyBot"}})
    with patch("main._tg_post", new=ok):
        import asyncio
        assert asyncio.run(main._bot_username("1:AAA")) == "MyBot"
        assert asyncio.run(main._bot_username("1:AAA")) == "MyBot"
        assert ok.await_count == 1
        asyncio.run(main._bot_username("2:BBB"))
        assert ok.await_count == 2
    main._bot_username_cache.clear()
    fail = AsyncMock(return_value={"ok": False, "description": "boom"})
    with patch("main._tg_post", new=fail):
        assert asyncio.run(main._bot_username("3:CCC")) == ""
        assert asyncio.run(main._bot_username("3:CCC")) == ""
        assert fail.await_count == 2  # failures are not cached


# ── Commands menu (setMyCommands) ────────────────────────────────────────────

def test_commands_set_calls_setMyCommands():
    commands = [
        {"command": "bank_ostatki", "description": "Банк — остатки"},
        {"command": "cash_ostatki", "description": "Касса — остатки"},
    ]
    m = _tg_delete_ok()
    with patch("httpx.AsyncClient", return_value=m):
        resp = client.post("/v1/messaging/commands/set", json={"bot_token": BOT, "commands": commands})

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["commands"] == commands
    body = _posted_body_from(m)
    assert body["commands"] == commands
    call_args = m.post.call_args
    assert call_args.args[0] == f"https://api.telegram.org/bot{BOT}/setMyCommands"


def test_commands_set_does_not_leak_bot_token():
    commands = [{"command": "bank_ostatki", "description": "Банк — остатки"}]
    with patch("httpx.AsyncClient", return_value=_tg_delete_ok()):
        resp = client.post("/v1/messaging/commands/set", json={"bot_token": BOT, "commands": commands})
    assert BOT not in resp.text


def test_commands_set_telegram_failure_returns_502():
    commands = [{"command": "bank_ostatki", "description": "Банк — остатки"}]
    with patch("httpx.AsyncClient", return_value=_tg_err("Unauthorized")):
        resp = client.post("/v1/messaging/commands/set", json={"bot_token": BOT, "commands": commands})
    assert resp.status_code == 502
    assert resp.json()["ok"] is False


def _posted_body_from(mock_client) -> dict:
    call_args = mock_client.post.call_args
    return call_args.kwargs.get("json") or {}
