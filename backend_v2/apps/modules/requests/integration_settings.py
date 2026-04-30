from __future__ import annotations

from dataclasses import dataclass

from apps.tenants.integration_settings import get_messaging_gateway_settings


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
    mg = get_messaging_gateway_settings(tenant=tenant)
    return RequestsMessagingGatewaySettings(
        dispatch_url=mg.dispatch_url,
        send_action=mg.send_action,
        edit_action=mg.edit_action,
        draft_notification_action=mg.draft_notification_action,
        message_template=mg.message_template,
        header_new_template=mg.header_new_template,
        header_step_approved_template=mg.header_step_approved_template,
        header_fully_approved_template=mg.header_fully_approved_template,
        header_closed_template=mg.header_closed_template,
        header_rejected_template=mg.header_rejected_template,
        subheader_payment_responsible_template=mg.subheader_payment_responsible_template,
        subheader_rejected_by_template=mg.subheader_rejected_by_template,
    )
