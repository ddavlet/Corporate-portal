from __future__ import annotations

import logging
from html import escape

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _normalize_n8n_json_payload(data):
    if isinstance(data, list):
        if not data:
            return {}
        first = data[0]
        return first if isinstance(first, dict) else {}
    return data if isinstance(data, dict) else {}


def extract_feedback_text_from_response(data) -> str | None:
    obj = _normalize_n8n_json_payload(data)
    raw = obj.get("feedback")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def feedback_ai_webhook_url(*, tenant_subdomain: str) -> str:
    """
    Public: https://<tenant>.<BASE_DOMAIN>/<path> (Traefik → /webhook/<tenant>/<path>).
    Internal: N8N_INTERNAL_BASE_URL/webhook/<tenant>/<path> (direct to n8n in Docker).
    """
    sub = (tenant_subdomain or "").strip()
    path = (getattr(settings, "N8N_FEEDBACK_AI_WEBHOOK_PATH", "ai") or "ai").strip().strip("/")
    internal = (getattr(settings, "N8N_INTERNAL_BASE_URL", "") or "").strip().rstrip("/")
    if internal:
        return f"{internal}/webhook/{sub}/{path}"
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    if not base_domain or not sub:
        raise ValueError("BASE_DOMAIN or tenant subdomain is not configured.")
    return f"https://{sub}.{base_domain}/{path}"


def post_feedback_ai_refine(*, tenant_subdomain: str, body: dict) -> str:
    """
    POST to tenant-scoped n8n webhook. Returns refined feedback text or raises RequestException/ValueError.
    """
    url = feedback_ai_webhook_url(tenant_subdomain=tenant_subdomain)
    logger.info("Feedback AI POST %s", url)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = (getattr(settings, "N8N_TOKEN", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=60)
    except requests.RequestException as exc:
        logger.exception("Feedback AI webhook request failed")
        raise requests.RequestException(f"Upstream request failed: {exc}") from exc

    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError as exc:
        raise ValueError("Upstream response is not valid JSON.") from exc

    text = extract_feedback_text_from_response(data)
    if text is None:
        raise ValueError('Upstream JSON must contain non-empty string field "feedback".')
    return text


def build_portal_feedback_telegram_message(
    *,
    feedback_id: int,
    kind: str,
    kind_label: str,
    author_display: str,
    page_path: str,
    body: str,
) -> str:
    safe_page = page_path.strip() or "—"
    return (
        f"<b>Обратная связь портала</b>\n"
        f"Тип: {escape(kind_label)}\n"
        f"От: {escape(author_display)}\n"
        f"ID: {feedback_id}\n"
        f"Страница: {escape(safe_page)}\n\n"
        f"{escape(body)}"
    )


def build_portal_feedback_dispatch_payload(
    *,
    action: str,
    chat_id: int,
    message_html: str,
    feedback_id: int,
    kind: str,
) -> dict:
    return {
        "action": action,
        "message": message_html,
        "parse_mode": "HTML",
        "chat_id": chat_id,
        "inline_keyboard": [],
        "feedback_id": feedback_id,
        "feedback_kind": kind,
        "notification_kind": "portal_feedback",
    }
