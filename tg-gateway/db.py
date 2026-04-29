"""
PostgreSQL helpers: connection pool, table init, event logging, callback cooldown.
All functions are no-ops when DATABASE_URL is not set.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
CALLBACK_COOLDOWN_SECS: int = int(os.environ.get("CALLBACK_COOLDOWN_SECS", "10"))

_pool = None


async def create_pool():
    global _pool
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set — DB logging disabled")
        return None
    try:
        import asyncpg
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        logger.info("DB pool created")
        return _pool
    except Exception as exc:
        logger.error("DB pool creation failed: %s", exc)
        return None


def get_pool():
    return _pool


async def init_tables(pool) -> None:
    if pool is None:
        return
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS gateway_logs (
            id          BIGSERIAL PRIMARY KEY,
            ts          TIMESTAMPTZ DEFAULT NOW(),
            direction   VARCHAR(10)  NOT NULL,
            endpoint    VARCHAR(200),
            action      VARCHAR(50),
            tenant_id   VARCHAR(100),
            chat_id     BIGINT,
            message_id  INT,
            ok          BOOLEAN,
            status_code INT,
            error_text  TEXT,
            payload     JSONB,
            tg_response JSONB
        )
    """)
    # add tenant_id column if table existed before this migration
    await pool.execute("""
        ALTER TABLE gateway_logs
        ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100)
    """)
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS callback_cooldown (
            chat_id     BIGINT NOT NULL,
            cb_key      TEXT   NOT NULL,
            last_called TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (chat_id, cb_key)
        )
    """)
    logger.info("DB tables ready")


async def log_event(
    *,
    direction: str,
    endpoint: str,
    action: str | None = None,
    tenant_id: str | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    ok: bool,
    status_code: int | None = None,
    error_text: str | None = None,
    payload: dict[str, Any] | None = None,
    tg_response: dict[str, Any] | None = None,
) -> None:
    pool = get_pool()
    if pool is None:
        logger.debug("log_event skipped (no pool): action=%s ok=%s error=%s", action, ok, error_text)
        return
    try:
        await pool.execute(
            """
            INSERT INTO gateway_logs
              (direction, endpoint, action, tenant_id, chat_id, message_id,
               ok, status_code, error_text, payload, tg_response)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb)
            """,
            direction, endpoint, action, tenant_id, chat_id, message_id,
            ok, status_code, error_text,
            json.dumps(payload)     if payload     else None,
            json.dumps(tg_response) if tg_response else None,
        )
    except Exception as exc:
        logger.error("DB log_event failed: %s", exc)


async def is_cooldown_ok(chat_id: int, cb_key: str) -> bool:
    """Return True if callback is allowed, False if still in cooldown."""
    pool = get_pool()
    if pool is None:
        return True
    try:
        row = await pool.fetchrow(
            "SELECT last_called FROM callback_cooldown WHERE chat_id=$1 AND cb_key=$2",
            chat_id, cb_key,
        )
        now = datetime.now(timezone.utc)
        if row:
            elapsed = (now - row["last_called"]).total_seconds()
            if elapsed < CALLBACK_COOLDOWN_SECS:
                return False
        await pool.execute(
            """
            INSERT INTO callback_cooldown (chat_id, cb_key, last_called)
            VALUES ($1, $2, NOW())
            ON CONFLICT (chat_id, cb_key) DO UPDATE SET last_called = NOW()
            """,
            chat_id, cb_key,
        )
        return True
    except Exception as exc:
        logger.error("DB cooldown check failed: %s", exc)
        return True
