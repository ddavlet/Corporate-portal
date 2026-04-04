from __future__ import annotations

import logging
from html import escape

import requests
from django.conf import settings

from apps.modules.telegram_approvals.services import _bridge_headers

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
    Same URL the browser would use: https://<tenant>.<BASE_DOMAIN>/<path>/
    (e.g. https://lemonfit.kolberg.uz/n8n/ai/dispatch/).
    """
    sub = (tenant_subdomain or "").strip()
    path = (getattr(settings, "N8N_FEEDBACK_AI_WEBHOOK_PATH", "n8n/ai/dispatch") or "n8n/ai/dispatch").strip().strip(
        "/"
    )
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    if not base_domain or not sub:
        raise ValueError("BASE_DOMAIN or tenant subdomain is not configured.")
    u = f"https://{sub}.{base_domain}/{path}"
    return u if u.endswith("/") else f"{u}/"


def post_feedback_ai_refine(*, tenant, body: dict) -> str:
    """
    POST JSON to n8n (e.g. action=feedback_former, kind, text) with X-N8N-Integration-Token like telegram/dispatch.
    """
    url = feedback_ai_webhook_url(tenant_subdomain=tenant.subdomain)
    logger.info("Feedback AI POST %s", url)

    headers = dict(_bridge_headers(tenant=tenant))
    headers["Accept"] = "application/json"

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
