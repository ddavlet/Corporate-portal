"""
Unit tests for the Telegram Dispatch Gateway.
No real credentials or database needed.

Run:
    pytest test_gateway.py -v
"""
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "")  # disables DB — all log_event calls are no-ops

from main import app  # noqa: E402

client = TestClient(app)

BOT    = "123:TEST"
CHAT   = 12345
TENANT = "test-tenant"

BASE_PAYLOAD = {
    "bot_token": BOT,
    "tenant_id": TENANT,
    "chat_id": CHAT,
}


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
    mock_resp.json.return_value = {"ok": True, "result": True}
    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__  = AsyncMock(return_value=False)
    m.post = AsyncMock(return_value=mock_resp)
    return m


def _tg_err(description: str = "chat not found"):
    mock_resp = MagicMock()
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
    assert resp.json()["ok"] is True


# ── send_message ──────────────────────────────────────────────────────────────

def test_send_message_returns_tenant_chat_message():
    with patch("httpx.AsyncClient", return_value=_tg_ok(101)):
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "send_message", "text_message": "Hello",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["tenant"] == TENANT
    assert data["chat_id"] == CHAT
    assert data["message_id"] == 101


def test_send_message_no_reply_markup():
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "send_message", "text_message": "plain",
        })
    assert "reply_markup" not in _posted_body(m)


# ── send_message_button (fully dynamic) ──────────────────────────────────────

def test_send_message_button_passes_any_keyboard():
    buttons = [
        [{"text": "✅ Approve", "callback_data": "v2_1:a"},
         {"text": "❌ Reject",  "callback_data": "v2_1:r"}],
    ]
    with patch("httpx.AsyncClient", return_value=_tg_ok(202)) as m:
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "send_message_button",
            "text_message": "Approve?", "inline_keyboard": buttons,
        })
    assert resp.status_code == 200
    body = _posted_body(m)
    assert body["reply_markup"]["inline_keyboard"] == buttons


def test_send_message_button_custom_labels():
    buttons = [[{"text": "💰 Pay", "callback_data": "pay"},
                {"text": "🚫 Cancel", "callback_data": "cancel"}]]
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "send_message_button",
            "text_message": "Pay?", "inline_keyboard": buttons,
        })
    body = _posted_body(m)
    assert body["reply_markup"]["inline_keyboard"][0][0]["text"] == "💰 Pay"


def test_send_message_button_empty_keyboard_omits_markup():
    with patch("httpx.AsyncClient", return_value=_tg_ok()) as m:
        client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "send_message_button",
            "text_message": "no buttons", "inline_keyboard": [],
        })
    assert "reply_markup" not in _posted_body(m)


# ── edit_message ──────────────────────────────────────────────────────────────

def test_edit_message_calls_editMessageText():
    with patch("httpx.AsyncClient", return_value=_tg_ok(555)) as m:
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "edit_message",
            "message_id": 555, "text_message": "Edited",
        })
    assert resp.status_code == 200
    assert "editMessageText" in _posted_url(m)


def test_edit_message_empty_keyboard_removes_buttons():
    """edit_message with empty inline_keyboard removes buttons (no reply_markup sent)."""
    with patch("httpx.AsyncClient", return_value=_tg_ok(555)) as m:
        client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "edit_message",
            "message_id": 555, "text_message": "No buttons now", "inline_keyboard": [],
        })
    assert "reply_markup" not in _posted_body(m)


def test_edit_message_no_message_id_returns_400():
    with patch("httpx.AsyncClient", return_value=_tg_ok()):
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "edit_message", "text_message": "no id",
        })
    assert resp.status_code == 400


def test_edit_not_modified_returns_200():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "description": "Bad Request: message is not modified"}
    m = AsyncMock()
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__  = AsyncMock(return_value=False)
    m.post = AsyncMock(return_value=mock_resp)
    with patch("httpx.AsyncClient", return_value=m):
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "edit_message",
            "message_id": 999, "text_message": "same",
        })
    assert resp.status_code == 200


# ── edit_message_button (fully dynamic) ──────────────────────────────────────

def test_edit_message_button_replaces_keyboard():
    new_buttons = [[{"text": "New", "callback_data": "new"}]]
    with patch("httpx.AsyncClient", return_value=_tg_ok(777)) as m:
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "edit_message_button",
            "message_id": 777, "text_message": "updated",
            "inline_keyboard": new_buttons,
        })
    assert resp.status_code == 200
    body = _posted_body(m)
    assert body["reply_markup"]["inline_keyboard"] == new_buttons


def test_edit_message_button_no_message_id_returns_400():
    with patch("httpx.AsyncClient", return_value=_tg_ok()):
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "edit_message_button", "text_message": "no id",
        })
    assert resp.status_code == 400


# ── delete_message ────────────────────────────────────────────────────────────

def test_delete_message_calls_deleteMessage():
    with patch("httpx.AsyncClient", return_value=_tg_delete_ok()) as m:
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "delete_message", "message_id": 888,
        })
    assert resp.status_code == 200
    assert "deleteMessage" in _posted_url(m)


def test_delete_message_no_message_id_returns_400():
    with patch("httpx.AsyncClient", return_value=_tg_delete_ok()):
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "delete_message",
        })
    assert resp.status_code == 400


def test_delete_message_button_action_is_unknown():
    """delete_message_button is removed — must return 422."""
    resp = client.post("/v1/telegram/send", json={
        **BASE_PAYLOAD, "action": "delete_message_button", "message_id": 999,
    })
    assert resp.status_code == 422


# ── Telegram API errors ───────────────────────────────────────────────────────

def test_telegram_error_returns_502():
    with patch("httpx.AsyncClient", return_value=_tg_err("chat not found")):
        resp = client.post("/v1/telegram/send", json={
            **BASE_PAYLOAD, "action": "send_message", "text_message": "hi",
        })
    assert resp.status_code == 502
    assert "chat not found" in resp.json()["detail"]


# ── Validation ────────────────────────────────────────────────────────────────

def test_unknown_action_returns_422():
    resp = client.post("/v1/telegram/send", json={
        **BASE_PAYLOAD, "action": "fly_to_moon", "text_message": "hi",
    })
    assert resp.status_code == 422


def test_missing_chat_id_returns_422():
    resp = client.post("/v1/telegram/send", json={
        "action": "send_message", "bot_token": BOT, "text_message": "hi",
    })
    assert resp.status_code == 422


# ── Webhook ───────────────────────────────────────────────────────────────────

def test_webhook_non_callback_returns_ok():
    resp = client.post("/v1/telegram/webhook/testtoken", json={
        "update_id": 1, "message": {"text": "hi"},
    })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_webhook_callback_no_backend_returns_ok():
    with patch("main.BACKEND_URL", ""):
        resp = client.post("/v1/telegram/webhook/testtoken", json={
            "update_id": 2,
            "callback_query": {
                "id": "abc", "data": "v2_42:a",
                "from": {"id": 12345},
                "message": {"message_id": 999, "chat": {"id": 12345}},
            },
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
