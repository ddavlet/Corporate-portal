"""
Fake Telegram Gateway — for local testing
-------------------------------------------
Mirrors the real tg-gateway API contract but never calls the Telegram Bot API.
Instead it:
  • Returns incrementing fake message_ids for send operations
  • Stores every outbound request in memory for inspection
  • Exposes /__log__ to inspect sent messages
  • Exposes /__callback__ to manually trigger approval callbacks

Endpoints:
  POST /v1/messaging/send               — mocked send / edit / delete
  POST /v1/messaging/webhook/set        — no-op, always succeeds
  POST /v1/messaging/webhook/delete     — no-op, always succeeds
  GET  /v1/messaging/webhook/info/{t}   — no-op, returns empty
  GET  /__log__                         — inspect all dispatched messages
  POST /__callback__                    — manually trigger a callback to Django
  GET  /health                          — liveness
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("BACKEND_WEBHOOK_URL", "")
BACKEND_WEBHOOK_HTTP_HOST = (os.environ.get("BACKEND_WEBHOOK_HTTP_HOST", "") or "").strip()


# ── In-memory store ───────────────────────────────────────────────────────────

class MessageLog:
    def __init__(self):
        self._lock = Lock()
        self._counter = 1000  # starting fake message_id
        self._entries: list[dict] = []
        # Map message_id → stored entry for edit/delete lookups
        self._by_id: dict[int, dict] = {}

    def next_id(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def add(self, entry: dict) -> None:
        with self._lock:
            self._entries.append(entry)
            mid = entry.get("message_id")
            if mid is not None:
                self._by_id[mid] = entry

    def get(self, message_id: int) -> dict | None:
        with self._lock:
            return self._by_id.get(message_id)

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._entries)

    def edit(self, message_id: int, text: str | None, buttons: list | None) -> bool:
        with self._lock:
            if message_id not in self._by_id:
                return False
            entry = self._by_id[message_id]
            if text is not None:
                entry["text"] = text
            if buttons is not None:
                entry["buttons"] = buttons
            entry["edited"] = True
            return True

    def delete(self, message_id: int) -> bool:
        with self._lock:
            if message_id not in self._by_id:
                return False
            self._by_id[message_id]["deleted"] = True
            return True


_log = MessageLog()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("fake-tg-gateway started (NO real Telegram calls)")
    yield


app = FastAPI(title="Fake Telegram Gateway", version="1.0", lifespan=lifespan)


# ── POST /v1/messaging/send ───────────────────────────────────────────────────

@app.post("/v1/messaging/send")
async def dispatch(request: Request) -> JSONResponse:
    body = await request.json()

    action = body.get("action", "")
    tenant = body.get("tenant_id")
    recipient = body.get("recipient_id", "")
    text = body.get("text", "")
    buttons = body.get("buttons", [])
    message_id = body.get("message_id")
    approval_id = body.get("approval_id")
    request_id = body.get("request_id")

    logger.info("FAKE dispatch action=%s tenant=%s recipient=%s approval=%s",
                action, tenant, recipient, approval_id)

    # Validate action
    ALL_ACTIONS = {"send", "send_interactive", "send_portal_feedback",
                   "edit", "edit_interactive", "delete"}
    if action not in ALL_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Unknown action '{action}'")

    # send / send_interactive / send_portal_feedback
    if action in {"send", "send_interactive", "send_portal_feedback"}:
        fake_id = _log.next_id()
        _log.add({
            "action": action,
            "tenant": tenant,
            "recipient_id": recipient,
            "text": text,
            "buttons": buttons,
            "message_id": fake_id,
            "approval_id": approval_id,
            "request_id": request_id,
            "edited": False,
            "deleted": False,
            "timestamp": time.time(),
        })
        return JSONResponse({"ok": True, "tenant": tenant, "recipient_id": recipient, "message_id": fake_id})

    # edit / edit_interactive
    if action in {"edit", "edit_interactive"}:
        if not message_id:
            raise HTTPException(status_code=400, detail="message_id required for edit actions")
        ok = _log.edit(message_id, text, buttons)
        if not ok:
            raise HTTPException(status_code=502, detail=f"Fake: message {message_id} not found")
        return JSONResponse({"ok": True, "tenant": tenant, "recipient_id": recipient, "message_id": message_id})

    # delete
    if action == "delete":
        if not message_id:
            raise HTTPException(status_code=400, detail="message_id required for delete")
        ok = _log.delete(message_id)
        if not ok:
            raise HTTPException(status_code=502, detail=f"Fake: message {message_id} not found")
        return JSONResponse({"ok": True, "tenant": tenant, "recipient_id": recipient, "message_id": message_id})

    # Should not reach here
    raise HTTPException(status_code=422, detail=f"Unhandled action '{action}'")


# ── Webhook management (no-op stubs) ──────────────────────────────────────────

@app.post("/v1/messaging/webhook/set")
async def webhook_set(request: Request) -> JSONResponse:
    body = await request.json()
    logger.info("FAKE webhook set: %s", body)
    return JSONResponse({
        "ok": True,
        "webhook_url": body.get("webhook_url", "http://fake/webhook"),
        "telegram_status": 200,
        "telegram": {"ok": True, "result": True},
    })


@app.get("/v1/messaging/webhook/info/{bot_token}")
async def webhook_info(bot_token: str = Path(...)) -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "connected": False,
        "url": "",
        "pending_update_count": 0,
        "telegram_status": 200,
        "telegram": {"ok": True, "result": {}},
    })


@app.post("/v1/messaging/webhook/delete")
async def webhook_delete(request: Request) -> JSONResponse:
    body = await request.json()
    logger.info("FAKE webhook delete: %s", body)
    return JSONResponse({
        "ok": True,
        "telegram_status": 200,
        "telegram": {"ok": True, "result": True},
    })


# ── GET /__log__ — inspect what Django sent ───────────────────────────────────

@app.get("/__log__")
async def get_log() -> JSONResponse:
    """Return all dispatched messages for test inspection."""
    return JSONResponse({"entries": _log.all(), "count": len(_log.all())})


@app.get("/__log__/{message_id}")
async def get_log_entry(message_id: int) -> JSONResponse:
    """Return a single dispatched message by its fake message_id."""
    entry = _log.get(message_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"message_id {message_id} not found")
    return JSONResponse(entry)


# ── POST /__callback__ — manually trigger an approval callback ────────────────

@app.post("/__callback__")
async def trigger_callback(request: Request) -> JSONResponse:
    """
    Manually simulate a user clicking an approval button.

    Body:
    {
        "payload":      "v2_42:a",       // callback_data value
        "user_id":      "789012345",     // Telegram user id
        "recipient_id": "123456789",     // chat_id
        "message_id":   1001             // fake message_id from dispatch
    }

    Forwards the standard platform-neutral interaction payload to Django's
    BACKEND_WEBHOOK_URL so the approval workflow processes it.
    """
    body = await request.json()

    forward = {
        "event":        "interaction",
        "payload":      body.get("payload", ""),
        "user_id":      str(body.get("user_id", "")),
        "recipient_id": str(body.get("recipient_id", "")),
        "message_id":   body.get("message_id"),
        "platform":     "telegram",
    }

    if not BACKEND_URL:
        raise HTTPException(status_code=500, detail="BACKEND_WEBHOOK_URL not configured")

    try:
        headers = {"Host": BACKEND_WEBHOOK_HTTP_HOST} if BACKEND_WEBHOOK_HTTP_HOST else None
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(BACKEND_URL, json=forward, headers=headers)

        return JSONResponse({
            "ok": resp.status_code < 400,
            "backend_status": resp.status_code,
            "backend_body": resp.text[:1000],
        })
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Backend forward failed: {exc}")


# ── GET /health ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"ok": True, "mode": "fake"}
