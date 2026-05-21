from __future__ import annotations
import logging
import threading

from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)


def notify_request_payed(*, request_obj: Request) -> None:
    from django.conf import settings
    from apps.modules.n8n_integration.views import _build_n8n_url, _n8n_session
    from apps.tenants.integration_settings import get_n8n_integration_settings

    tenant = request_obj.tenant
    if not getattr(settings, "BASE_DOMAIN", ""):
        logger.warning("notify_request_payed: BASE_DOMAIN not configured, skipping")
        return

    token = get_n8n_integration_settings(tenant=tenant).integration_token
    if not token:
        logger.warning(
            "notify_request_payed: no integration token for tenant=%s, skipping",
            tenant.subdomain,
        )
        return

    url, host_override, transport = _build_n8n_url(tenant, "/n8n/events/new-payed-request")
    headers = {
        "Content-Type": "application/json",
        "X-N8N-Integration-Token": token,
        "X-Tenant": tenant.subdomain,
    }
    if host_override:
        headers["Host"] = host_override

    payload = {
        "id": request_obj.id,
        "title": request_obj.title,
        "amount": str(request_obj.amount),
        "currency": request_obj.currency,
        "payment_type": request_obj.payment_type,
        "payment_purpose": request_obj.payment_purpose,
        "description": request_obj.description,
        "category": request_obj.category,
        "company_payer": request_obj.company_payer,
        "vendor": request_obj.vendor,
        "vendor_ref_id": request_obj.vendor_ref_id,
        "billing_date": request_obj.billing_date.isoformat() if request_obj.billing_date else None,
        "payed_at": request_obj.payed_at,
        "status": request_obj.status,
        "tenant": tenant.subdomain,
    }

    subdomain = tenant.subdomain
    request_id = request_obj.id

    def _send():
        try:
            resp = _n8n_session.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code >= 400:
                logger.warning(
                    "notify_request_payed: tenant=%s request_id=%s transport=%s status=%s body=%s",
                    subdomain, request_id, transport, resp.status_code, resp.text[:200],
                )
            else:
                logger.info(
                    "notify_request_payed: tenant=%s request_id=%s transport=%s status=%s",
                    subdomain, request_id, transport, resp.status_code,
                )
        except Exception as exc:
            logger.warning(
                "notify_request_payed failed: tenant=%s request_id=%s error=%s",
                subdomain, request_id, exc,
            )

    threading.Thread(target=_send, daemon=True).start()
