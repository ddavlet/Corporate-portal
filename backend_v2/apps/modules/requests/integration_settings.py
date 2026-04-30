from __future__ import annotations

from dataclasses import dataclass

from apps.modules.requests.models import RequestApprovalConfig
from apps.tenants.integration_settings import (
    DEFAULT_MESSAGING_GATEWAY_HEADER_CLOSED_TEMPLATE,
    DEFAULT_MESSAGING_GATEWAY_HEADER_FULLY_APPROVED_TEMPLATE,
    DEFAULT_MESSAGING_GATEWAY_HEADER_NEW_TEMPLATE,
    DEFAULT_MESSAGING_GATEWAY_HEADER_REJECTED_TEMPLATE,
    DEFAULT_MESSAGING_GATEWAY_HEADER_STEP_APPROVED_TEMPLATE,
    DEFAULT_MESSAGING_GATEWAY_MESSAGE_TEMPLATE,
    DEFAULT_MESSAGING_GATEWAY_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE,
    DEFAULT_MESSAGING_GATEWAY_SUBHEADER_REJECTED_BY_TEMPLATE,
    get_messaging_gateway_settings,
)


@dataclass(frozen=True)
class RequestsMessagingGatewaySettings:
    dispatch_url: str
    send_action: str
    edit_action: str
    draft_notification_action: str
    message_template: str
    header_new_template: str
    header_step_approved_template: str
    header_fully_approved_template: str
    header_closed_template: str
    header_rejected_template: str
    subheader_payment_responsible_template: str
    subheader_rejected_by_template: str


def get_requests_messaging_gateway_settings(*, tenant) -> RequestsMessagingGatewaySettings:
    cfg = RequestApprovalConfig.objects.filter(tenant=tenant).first()
    legacy = get_messaging_gateway_settings(tenant=tenant)
    draft_action = (cfg.messaging_gateway_draft_action.strip() if cfg else "") or (
        legacy.draft_notification_action.strip()
    )
    if not draft_action:
        draft_action = "send"
    return RequestsMessagingGatewaySettings(
        dispatch_url=(cfg.messaging_gateway_dispatch_url.strip() if cfg else "") or legacy.dispatch_url,
        send_action=(cfg.messaging_gateway_send_action.strip() if cfg else "") or legacy.send_action,
        edit_action=(cfg.messaging_gateway_edit_action.strip() if cfg else "") or legacy.edit_action,
        draft_notification_action=draft_action,
        message_template=(cfg.messaging_gateway_message_template if cfg else "") or legacy.message_template,
        header_new_template=(cfg.messaging_gateway_header_new_template if cfg else "")
        or getattr(legacy, "header_new_template", DEFAULT_MESSAGING_GATEWAY_HEADER_NEW_TEMPLATE),
        header_step_approved_template=(cfg.messaging_gateway_header_step_approved_template if cfg else "")
        or getattr(
            legacy,
            "header_step_approved_template",
            DEFAULT_MESSAGING_GATEWAY_HEADER_STEP_APPROVED_TEMPLATE,
        ),
        header_fully_approved_template=(cfg.messaging_gateway_header_fully_approved_template if cfg else "")
        or getattr(
            legacy,
            "header_fully_approved_template",
            DEFAULT_MESSAGING_GATEWAY_HEADER_FULLY_APPROVED_TEMPLATE,
        ),
        header_closed_template=(cfg.messaging_gateway_header_closed_template if cfg else "")
        or getattr(legacy, "header_closed_template", DEFAULT_MESSAGING_GATEWAY_HEADER_CLOSED_TEMPLATE),
        header_rejected_template=(cfg.messaging_gateway_header_rejected_template if cfg else "")
        or getattr(legacy, "header_rejected_template", DEFAULT_MESSAGING_GATEWAY_HEADER_REJECTED_TEMPLATE),
        subheader_payment_responsible_template=(
            cfg.messaging_gateway_subheader_payment_responsible_template if cfg else ""
        )
        or getattr(
            legacy,
            "subheader_payment_responsible_template",
            DEFAULT_MESSAGING_GATEWAY_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE,
        ),
        subheader_rejected_by_template=(cfg.messaging_gateway_subheader_rejected_by_template if cfg else "")
        or getattr(
            legacy,
            "subheader_rejected_by_template",
            DEFAULT_MESSAGING_GATEWAY_SUBHEADER_REJECTED_BY_TEMPLATE,
        ),
    )
