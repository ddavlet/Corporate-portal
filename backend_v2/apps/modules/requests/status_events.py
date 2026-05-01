from __future__ import annotations

import logging
from collections.abc import Callable

import requests
from django.conf import settings

from apps.modules.requests.models import Request
from apps.modules.requests.serializers import PortalRequestDetailSerializer
from apps.tenants.integration_settings import get_n8n_integration_settings

logger = logging.getLogger(__name__)

RequestPayedEventHandler = Callable[[Request], None]


def _request_payed_n8n_webhook_url(*, request_obj: Request) -> str:
    tenant = getattr(request_obj, "tenant", None)
    subdomain = (getattr(tenant, "subdomain", "") or "").strip()
    base_domain = (getattr(settings, "BASE_DOMAIN", "") or "").strip().lower().lstrip(".")
    if not subdomain or not base_domain:
        return ""
    return f"https://{subdomain}.{base_domain}/n8n/events/new-payed-request"


def _serialize_request_payload(*, request_obj: Request) -> dict:
    return PortalRequestDetailSerializer(request_obj, context={}).data


def _handle_request_payed_n8n_event(*, request_obj: Request) -> None:
    """
    POST full request payload to tenant-scoped n8n event webhook.
    """
    webhook_url = _request_payed_n8n_webhook_url(request_obj=request_obj)
    if not webhook_url:
        logger.warning(
            "request_payed_event skipped: missing BASE_DOMAIN/subdomain request_id=%s tenant_id=%s",
            request_obj.id,
            request_obj.tenant_id,
        )
        return

    token = get_n8n_integration_settings(tenant=getattr(request_obj, "tenant", None)).integration_token
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["X-N8N-Integration-Token"] = token

    payload = _serialize_request_payload(request_obj=request_obj)
    response = requests.post(
        webhook_url,
        json=payload,
        headers=headers,
        timeout=30,
    )
    if response.status_code >= 400:
        logger.warning(
            "request_payed_event n8n webhook HTTP %s request_id=%s tenant_id=%s",
            response.status_code,
            request_obj.id,
            request_obj.tenant_id,
        )
        return
    logger.info(
        "request_payed_event sent request_id=%s tenant_id=%s",
        request_obj.id,
        request_obj.tenant_id,
    )


REQUEST_PAYED_EVENT_HANDLERS: tuple[RequestPayedEventHandler, ...] = (
    _handle_request_payed_n8n_event,
)


def dispatch_request_payed_event_handlers(*, request_obj: Request) -> None:
    """
    Run PAYED status handlers without breaking the approval flow on handler errors.
    """
    for handler in REQUEST_PAYED_EVENT_HANDLERS:
        try:
            handler(request_obj=request_obj)
        except Exception:
            logger.exception(
                "request_payed_event handler failed handler=%s request_id=%s tenant_id=%s",
                getattr(handler, "__name__", repr(handler)),
                request_obj.id,
                request_obj.tenant_id,
            )
