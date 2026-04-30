"""
Messaging Gateway — Telegram Adapter
--------------------------------------
Platform-neutral API. The backend sends/receives universal messages; this service
translates them to/from the Telegram Bot API. Replacing Telegram with Slack or
another platform requires only deploying a different gateway — no backend changes.

Endpoints:
  POST /v1/messaging/send               — send / edit / delete via Telegram
  POST /v1/messaging/webhook/{bot_token}— receive Telegram updates, forward platform-neutral callback
  GET  /health                          — liveness + DB status

Authentication: none — Docker internal network only (no public exposure).

Actions:
  send             → sendMessage  (plain text)
  send_interactive → sendMessage  (with dynamic buttons)
  edit             → editMessageText (also clears buttons when buttons=[])
  edit_interactive → editMessageText (with dynamic button update)
  delete           → deleteMessage
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
from models import (
    DELETE_ACTIONS,
    EDIT_ACTIONS,
    SEND_ACTIONS,
    DispatchRequest,
    WebhookDeleteRequest,
    WebhookSetRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("BACKEND_WEBHOOK_URL", "")
# Optional Host header so Django tenant middleware sees a real subdomain (e.g. test.localhost:8001).
BACKEND_WEBHOOK_HTTP_HOST = (os.environ.get("BACKEND_WEBHOOK_HTTP_HOST", "") or "").strip()
PUBLIC_WEBHOOK_BASE_URL = (os.environ.get("PUBLIC_WEBHOOK_BASE_URL", "") or "").rstrip("/")


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


app = FastAPI(title="Messaging Gateway", version="2.0", lifespan=lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tg_url(bot_token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{bot_token}/{method}"


def _mask_bot_token(bot_token: str) -> str:
    token = (bot_token or "").strip()
    if len(token) <= 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _markup(tg_keyboard: list[list[dict]]) -> dict | None:
    """Wrap Telegram keyboard rows in reply_markup. None → omit field entirely."""
    return {"inline_keyboard": tg_keyboard} if tg_keyboard else None


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


async def _telegram_api(bot_token: str, method: str, body: dict) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(_tg_url(bot_token, method), json=body)
    try:
        payload = resp.json()
    except Exception:
        payload = {"ok": False, "description": resp.text[:500]}
    return resp.status_code, payload


# ── POST /v1/messaging/send ───────────────────────────────────────────────────

@app.post("/v1/messaging/send")
async def dispatch(payload: DispatchRequest) -> JSONResponse:
    action = payload.action
    logger.info(
        "dispatch tenant=%s action=%s recipient=%s approval_id=%s request_id=%s",
        payload.tenant_id, action, payload.recipient_id,
        payload.approval_id, payload.request_id,
    )

    tg_data: dict[str, Any] = {}
    ok = False
    message_id: int | None = None
    error_text: str | None = None

    try:
        if action in SEND_ACTIONS:
            body: dict = {
                "chat_id":    payload.tg_recipient(),
                "text":       payload.text,
                "parse_mode": payload.tg_parse_mode(),
            }
            if action == "send_interactive":
                markup = _markup(payload.tg_keyboard())
                if markup:
                    body["reply_markup"] = markup
            tg_data = await _tg_post(payload.bot_token, "sendMessage", body)

        elif action in EDIT_ACTIONS:
            if not payload.message_id:
                raise HTTPException(status_code=400, detail="message_id required for edit actions")
            body = {
                "chat_id":    payload.tg_recipient(),
                "message_id": payload.message_id,
                "text":       payload.text,
                "parse_mode": payload.tg_parse_mode(),
            }
            markup = _markup(payload.tg_keyboard())
            if markup:
                body["reply_markup"] = markup
            tg_data = await _tg_post(payload.bot_token, "editMessageText", body)
            # "message is not modified" is not an error
            if not tg_data.get("ok") and "not modified" in str(tg_data.get("description", "")).lower():
                tg_data = {"ok": True, "result": {"message_id": payload.message_id}}

        elif action == "delete":
            if not payload.message_id:
                raise HTTPException(status_code=400, detail="message_id required for delete")
            tg_data = await _tg_post(payload.bot_token, "deleteMessage", {
                "chat_id":    payload.tg_recipient(),
                "message_id": payload.message_id,
            })

        if tg_data.get("ok"):
            ok = True
            result = tg_data.get("result", {})
            message_id = result.get("message_id") if isinstance(result, dict) else payload.message_id
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
            endpoint="/v1/messaging/send",
            action=action,
            tenant_id=payload.tenant_id,
            recipient_id=payload.recipient_id,
            message_id=message_id or payload.message_id,
            ok=ok,
            status_code=200 if ok else 502,
            error_text=error_text,
            payload=payload.model_dump(exclude={"bot_token"}),  # never log credentials
            tg_response=tg_data or None,
        )

    if not ok:
        raise HTTPException(status_code=502, detail=f"Telegram error: {error_text}")

    return JSONResponse({
        "ok":           True,
        "tenant":       payload.tenant_id,
        "recipient_id": payload.recipient_id,
        "message_id":   message_id,
    })


# ── POST /v1/messaging/webhook/{bot_token} ────────────────────────────────────

@app.post("/v1/messaging/webhook/{bot_token}")
async def messaging_webhook(
    request: Request,
    bot_token: str = Path(...),
) -> dict:
    update: dict = await request.json()
    # Never log the bot_token — it is a secret even though it's in the URL
    logger.info("webhook update_id=%s", update.get("update_id"))

    cb = update.get("callback_query")
    if not cb:
        await db.log_event(
            direction="in", endpoint="/v1/messaging/webhook",
            action="non_interactive", ok=True, status_code=200, payload=update,
        )
        return {"ok": True}

    msg          = cb.get("message", {})
    recipient_id = str(msg.get("chat", {}).get("id", ""))
    message_id   = msg.get("message_id")
    cb_value     = cb.get("data", "")
    user_id      = str(cb.get("from", {}).get("id", ""))

    # 10-second cooldown — deduplicate rapid identical button presses
    if recipient_id and not await db.is_cooldown_ok(recipient_id, cb_value):
        logger.info("cooldown blocked recipient=%s value=%s", recipient_id, cb_value)
        await db.log_event(
            direction="in", endpoint="/v1/messaging/webhook",
            action="cooldown_blocked", recipient_id=recipient_id, message_id=message_id,
            ok=False, status_code=429, error_text="cooldown", payload=update,
        )
        return {"ok": True}  # always 200 to Telegram

    # Platform-neutral interaction event
    forward: dict = {
        "event":        "interaction",
        "payload":      cb_value,
        "user_id":      user_id,
        "recipient_id": recipient_id,
        "message_id":   message_id,
        "platform":     "telegram",
    }

    ok = False
    error_text: str | None = None
    fwd_status: int = 0

    if BACKEND_URL:
        try:
            headers = {"Host": BACKEND_WEBHOOK_HTTP_HOST} if BACKEND_WEBHOOK_HTTP_HOST else None
            async with httpx.AsyncClient(timeout=10) as client:
                # No auth header — Docker network isolation is the access control
                resp = await client.post(BACKEND_URL, json=forward, headers=headers)
            fwd_status = resp.status_code
            ok = resp.status_code < 400
            if not ok:
                error_text = resp.text[:500]
                logger.error("backend forward %s: %s", fwd_status, error_text)
            else:
                logger.info("interaction forwarded: recipient=%s value=%s", recipient_id, cb_value)
        except Exception as exc:
            error_text = str(exc)
            logger.error("backend forward failed: %s", exc)
    else:
        logger.warning("BACKEND_WEBHOOK_URL not configured — interaction not forwarded")
        ok = True

    await db.log_event(
        direction="in", endpoint="/v1/messaging/webhook",
        action="interaction", recipient_id=recipient_id, message_id=message_id,
        ok=ok, status_code=fwd_status, error_text=error_text,
        payload=update, tg_response=forward,
    )

    return {"ok": True}


# ── Telegram webhook management ────────────────────────────────────────────────

@app.post("/v1/messaging/webhook/set")
async def set_telegram_webhook(payload: WebhookSetRequest) -> JSONResponse:
    webhook_url = (payload.webhook_url or "").strip()
    token_mask = _mask_bot_token(payload.bot_token)
    url_source = "request"
    if not webhook_url:
        if not PUBLIC_WEBHOOK_BASE_URL:
            raise HTTPException(status_code=400, detail="webhook_url is required when PUBLIC_WEBHOOK_BASE_URL is not configured")
        webhook_url = f"{PUBLIC_WEBHOOK_BASE_URL}/v1/messaging/webhook/{payload.bot_token}"
        url_source = "public_base"

    logger.info("webhook set requested token=%s source=%s url=%s", token_mask, url_source, webhook_url)

    status_code, tg_data = await _telegram_api(payload.bot_token, "setWebhook", {"url": webhook_url})
    logger.info(
        "webhook set result token=%s ok=%s status=%s description=%s",
        token_mask,
        bool(tg_data.get("ok")),
        status_code,
        tg_data.get("description"),
    )
    return JSONResponse(
        status_code=200 if tg_data.get("ok") else 502,
        content={
            "ok": bool(tg_data.get("ok")),
            "webhook_url": webhook_url,
            "telegram_status": status_code,
            "telegram": tg_data,
        },
    )


@app.get("/v1/messaging/webhook/info/{bot_token}")
async def get_telegram_webhook_info(bot_token: str) -> JSONResponse:
    token_mask = _mask_bot_token(bot_token)
    status_code, tg_data = await _telegram_api(bot_token, "getWebhookInfo", {})
    result = tg_data.get("result") if isinstance(tg_data, dict) else {}
    webhook_url = result.get("url", "") if isinstance(result, dict) else ""
    logger.info(
        "webhook info token=%s ok=%s status=%s connected=%s url=%s pending=%s last_error=%s",
        token_mask,
        bool(tg_data.get("ok")),
        status_code,
        bool(webhook_url),
        webhook_url,
        int(result.get("pending_update_count", 0)) if isinstance(result, dict) else 0,
        result.get("last_error_message") if isinstance(result, dict) else None,
    )
    return JSONResponse(
        status_code=200 if tg_data.get("ok") else 502,
        content={
            "ok": bool(tg_data.get("ok")),
            "connected": bool(webhook_url),
            "url": webhook_url,
            "pending_update_count": int(result.get("pending_update_count", 0)) if isinstance(result, dict) else 0,
            "last_error_date": result.get("last_error_date") if isinstance(result, dict) else None,
            "last_error_message": result.get("last_error_message") if isinstance(result, dict) else None,
            "telegram_status": status_code,
            "telegram": tg_data,
        },
    )


@app.post("/v1/messaging/webhook/delete")
async def delete_telegram_webhook(payload: WebhookDeleteRequest) -> JSONResponse:
    token_mask = _mask_bot_token(payload.bot_token)
    logger.info(
        "webhook delete requested token=%s drop_pending_updates=%s",
        token_mask,
        payload.drop_pending_updates,
    )
    status_code, tg_data = await _telegram_api(
        payload.bot_token,
        "deleteWebhook",
        {"drop_pending_updates": payload.drop_pending_updates},
    )
    logger.info(
        "webhook delete result token=%s ok=%s status=%s description=%s",
        token_mask,
        bool(tg_data.get("ok")),
        status_code,
        tg_data.get("description"),
    )
    return JSONResponse(
        status_code=200 if tg_data.get("ok") else 502,
        content={
            "ok": bool(tg_data.get("ok")),
            "telegram_status": status_code,
            "telegram": tg_data,
        },
    )


# ── GET /health ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"ok": True, "db": db.get_pool() is not None}
