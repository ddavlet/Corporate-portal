from __future__ import annotations

from dataclasses import dataclass

from apps.modules.requests.models import RequestApprovalConfig
from apps.tenants.integration_settings import (
    DEFAULT_TELEGRAM_APPROVALS_HEADER_CLOSED_TEMPLATE,
    DEFAULT_TELEGRAM_APPROVALS_HEADER_FULLY_APPROVED_TEMPLATE,
    DEFAULT_TELEGRAM_APPROVALS_HEADER_NEW_TEMPLATE,
    DEFAULT_TELEGRAM_APPROVALS_HEADER_REJECTED_TEMPLATE,
    DEFAULT_TELEGRAM_APPROVALS_HEADER_STEP_APPROVED_TEMPLATE,
    DEFAULT_TELEGRAM_APPROVALS_MESSAGE_TEMPLATE,
    DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE,
    DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_REJECTED_BY_TEMPLATE,
    get_n8n_integration_settings,
    get_telegram_approvals_settings,
)


@dataclass(frozen=True)
class RequestsTelegramIntegrationSettings:
    dispatch_url: str
    bridge_token: str
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
    n8n_integration_token: str


def get_requests_telegram_integration_settings(*, tenant) -> RequestsTelegramIntegrationSettings:
    cfg = RequestApprovalConfig.objects.filter(tenant=tenant).first()
    legacy_tg = get_telegram_approvals_settings(tenant=tenant)
    legacy_n8n = get_n8n_integration_settings(tenant=tenant)
    draft_action = (cfg.telegram_approvals_draft_notification_action.strip() if cfg else "") or (
        legacy_tg.draft_notification_action.strip()
    )
    if not draft_action:
        draft_action = "send_draft_notification"
    return RequestsTelegramIntegrationSettings(
        dispatch_url=(cfg.telegram_approvals_bridge_dispatch_url.strip() if cfg else "") or legacy_tg.dispatch_url,
        bridge_token=(cfg.telegram_approvals_bridge_token.strip() if cfg else "") or legacy_tg.bridge_token,
        send_action=(cfg.telegram_approvals_send_action.strip() if cfg else "") or legacy_tg.send_action,
        edit_action=(cfg.telegram_approvals_edit_action.strip() if cfg else "") or legacy_tg.edit_action,
        draft_notification_action=draft_action,
        message_template=(cfg.telegram_approvals_message_template if cfg else "") or legacy_tg.message_template,
        header_new_template=(cfg.telegram_approvals_header_new_template if cfg else "")
        or getattr(legacy_tg, "header_new_template", DEFAULT_TELEGRAM_APPROVALS_HEADER_NEW_TEMPLATE),
        header_step_approved_template=(cfg.telegram_approvals_header_step_approved_template if cfg else "")
        or getattr(
            legacy_tg,
            "header_step_approved_template",
            DEFAULT_TELEGRAM_APPROVALS_HEADER_STEP_APPROVED_TEMPLATE,
        ),
        header_fully_approved_template=(cfg.telegram_approvals_header_fully_approved_template if cfg else "")
        or getattr(
            legacy_tg,
            "header_fully_approved_template",
            DEFAULT_TELEGRAM_APPROVALS_HEADER_FULLY_APPROVED_TEMPLATE,
        ),
        header_closed_template=(cfg.telegram_approvals_header_closed_template if cfg else "")
        or getattr(legacy_tg, "header_closed_template", DEFAULT_TELEGRAM_APPROVALS_HEADER_CLOSED_TEMPLATE),
        header_rejected_template=(cfg.telegram_approvals_header_rejected_template if cfg else "")
        or getattr(legacy_tg, "header_rejected_template", DEFAULT_TELEGRAM_APPROVALS_HEADER_REJECTED_TEMPLATE),
        subheader_payment_responsible_template=(
            cfg.telegram_approvals_subheader_payment_responsible_template if cfg else ""
        )
        or getattr(
            legacy_tg,
            "subheader_payment_responsible_template",
            DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE,
        ),
        subheader_rejected_by_template=(cfg.telegram_approvals_subheader_rejected_by_template if cfg else "")
        or getattr(
            legacy_tg,
            "subheader_rejected_by_template",
            DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_REJECTED_BY_TEMPLATE,
        ),
        n8n_integration_token=(cfg.n8n_integration_token.strip() if cfg else "") or legacy_n8n.integration_token,
    )
