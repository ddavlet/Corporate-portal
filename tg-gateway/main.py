"""
Telegram Dispatch Gateway
--------------------------
Internal service — no token authentication required (Docker network only).

POST /v1/telegram/send                   — send / edit / delete messages
POST /v1/telegram/webhook/{bot_token}    — receive Telegram updates, forward callbacks to backend
GET  /health                             — liveness + DB status

Actions:
  send_message         → sendMessage (plain text)
  send_message_button  → sendMessage + fully dynamic inline_keyboard
  edit_message         → editMessageText (also removes buttons if inline_keyboard is empty)
  edit_message_button  → editMessageText + dynamic inline_keyboard update
  delete_message       → deleteMessage

Multi-tenant: every request carries tenant_id, every response and log entry echoes it back.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import JSONResponse

import db
from models import DELETE_ACTIONS, EDIT_ACTIONS, SEND_ACTIONS, DispatchRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKEND_URL   = os.environ.get("BACKEND_WEBHOOK_URL", "")
BACKEND_TOKEN = os.environ.get("BACKEND_TOKEN", "")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await db.create_pool()
    if pool:
        await db.init_tables(pool)
    yield
    pool = db.get_pool()
    if pool:
        await pool.close()


app = FastAPI(title="Telegram Dispatch Gateway", version="3.0", lifespan=lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tg_url(bot_token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}/{method}"


def _markup(inline_keyboard: list) -> dict | None:
    """None when empty — Telegram omits reply_markup entirely."""
    return {"inline_keyboard": inline_keyboard} if inline_keyboard else None


async def _tg_post(bot_token: str, method: str, body: dict) -> dict:
    """Call Telegram API with 1 retry on transient network errors."""
    last_exc: Exception | None = None
    async with httpx.AsyncClient(timeout=10) as client:
        for attempt in range(2):
            try:
                resp = await client.post(_tg_url(bot_token, method), json=body)
                return resp.json()
            except httpx.TransportError as exc:
                logger.warning("TG %s attempt %d failed: %s", method, attempt + 1, exc)
                last_exc = exc
    raise last_exc  # type: ignore[misc]


# ── POST /v1/telegram/send ────────────────────────────────────────────────────

@app.post("/v1/telegram/send")
async def dispatch(payload: DispatchRequest) -> JSONResponse:
    action = payload.action
    logger.info(
        "dispatch tenant=%s action=%s chat_id=%s approval_id=%s request_id=%s",
        payload.tenant_id, action, payload.chat_id, payload.approval_id, payload.request_id,
    )

    tg_data: dict[str, Any] = {}
    ok = False
    message_id: int | None = None
    error_text: str | None = None

    try:
        if action in SEND_ACTIONS:
            body: dict = {
                "chat_id": payload.chat_id,
                "text": payload.text_message,
                "parse_mode": payload.parse_mode,
            }
            if action == "send_message_button":
                markup = _markup(payload.inline_keyboard)
                if markup:
                    body["reply_markup"] = markup
            tg_data = await _tg_post(payload.bot_token, "sendMessage", body)

        elif action in EDIT_ACTIONS:
            if not payload.message_id:
                raise HTTPException(status_code=400, detail="message_id required for edit actions")
            body = {
                "chat_id": payload.chat_id,
                "message_id": payload.message_id,
                "text": payload.text_message,
                "parse_mode": payload.parse_mode,
            }
            # edit_message with empty inline_keyboard removes buttons
            # edit_message_button with buttons updates them
            markup = _markup(payload.inline_keyboard)
            if markup:
                body["reply_markup"] = markup
            tg_data = await _tg_post(payload.bot_token, "editMessageText", body)
            # Telegram 400 "not modified" — treat as success
            if not tg_data.get("ok") and "not modified" in str(tg_data.get("description", "")).lower():
                tg_data = {"ok": True, "result": {"message_id": payload.message_id}}

        elif action == "delete_message":
            if not payload.message_id:
                raise HTTPException(status_code=400, detail="message_id required for delete_message")
            tg_data = await _tg_post(payload.bot_token, "deleteMessage", {
                "chat_id": payload.chat_id,
                "message_id": payload.message_id,
            })

        if tg_data.get("ok"):
            ok = True
            result = tg_data.get("result", {})
            message_id = (
                result.get("message_id") if isinstance(result, dict) else payload.message_id
            )
        else:
            error_text = tg_data.get("description", "Unknown Telegram error")
            logger.error("Telegram %s failed: %s", action, error_text)

    except HTTPException:
        raise
    except Exception as exc:
        error_text = str(exc)
        logger.error("dispatch error action=%s: %s", action, exc)
    finally:
        await db.log_event(
            direction="out",
            endpoint="/v1/telegram/send",
            action=action,
            tenant_id=payload.tenant_id,
            chat_id=payload.chat_id,
            message_id=message_id or payload.message_id,
            ok=ok,
            status_code=200 if ok else 502,
            error_text=error_text,
            payload=payload.model_dump(exclude={"bot_token"}),
            tg_response=tg_data or None,
        )

    if not ok:
        raise HTTPException(status_code=502, detail=f"Telegram error: {error_text}")

    return JSONResponse({
        "ok": True,
        "tenant": payload.tenant_id,
        "chat_id": payload.chat_id,
        "message_id": message_id,
        "telegram_response": tg_data,
    })


# ── POST /v1/telegram/webhook/{bot_token} ─────────────────────────────────────

@app.post("/v1/telegram/webhook/{bot_token}")
async def telegram_webhook(
    request: Request,
    bot_token: str = Path(...),
) -> dict:
    update: dict = await request.json()
    logger.info("webhook bot=***%s update_id=%s", bot_token[-6:], update.get("update_id"))

    cb = update.get("callback_query")
    if not cb:
        await db.log_event(
            direction="in", endpoint="/v1/telegram/webhook",
            action="non_callback", ok=True, status_code=200, payload=update,
        )
        return {"ok": True}

    msg       = cb.get("message", {})
    chat_id   = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    cb_data   = cb.get("data", "")

    # 10-second cooldown per (chat_id, callback_data)
    if chat_id and not await db.is_cooldown_ok(int(chat_id), cb_data):
        logger.info("cooldown blocked chat_id=%s data=%s", chat_id, cb_data)
        await db.log_event(
            direction="in", endpoint="/v1/telegram/webhook",
            action="cooldown_blocked", chat_id=chat_id, message_id=message_id,
            ok=False, status_code=429, error_text="cooldown", payload=update,
        )
        return {"ok": True}

    forward: dict = {
        "update": {
            "callback_query": {
                "data": cb_data,
                "from": cb.get("from", {}),
                "message": msg,
            }
        }
    }

    ok = False
    error_text: str | None = None
    fwd_status: int = 0

    if BACKEND_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    BACKEND_URL,
                    json=forward,
                    headers={"X-N8N-Integration-Token": BACKEND_TOKEN},
                )
            fwd_status = resp.status_code
            ok = resp.status_code < 400
            if not ok:
                error_text = resp.text[:500]
                logger.error("backend forward %s: %s", fwd_status, error_text)
            else:
                logger.info("callback forwarded: chat_id=%s data=%s", chat_id, cb_data)
        except Exception as exc:
            error_text = str(exc)
            logger.error("backend forward failed: %s", exc)
    else:
        logger.warning("BACKEND_WEBHOOK_URL not configured — callback not forwarded")
        ok = True

    await db.log_event(
        direction="in", endpoint="/v1/telegram/webhook",
        action="callback_forward", chat_id=chat_id, message_id=message_id,
        ok=ok, status_code=fwd_status, error_text=error_text,
        payload=update, tg_response=forward,
    )

    return {"ok": True}


# ── GET /health ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"ok": True, "db": db.get_pool() is not None}
