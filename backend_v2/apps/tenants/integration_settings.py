from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.tenants.models import Tenant, TenantIntegrationConfig


@dataclass(frozen=True)
class MessagingGatewaySettings:
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


DEFAULT_MESSAGING_GATEWAY_MESSAGE_TEMPLATE = (
    "<b>{header}</b>\n"
    "{subheader_block}"
    "Компания: {company_payer}\n"
    "Проект: {project_title}\n\n"
    "<b>💰 Финансы</b>\n"
    "• Поставщик: {vendor}\n"
    "• Категория: {category}\n"
    "• Сумма: {amount} {currency}\n"
    "• Тип оплаты: {payment_type}"
    "{contract_block}\n\n"
    "<b>📌 Назначение</b>\n"
    "• Назначение платежа: {payment_purpose}\n"
    "• Описание: {description}\n"
    "• Месяц начисления: {billing_month}\n\n"
    "<b>⏱ Статус</b>\n"
    "• Срочность: {urgency}\n"
    "• Заявитель: {requester}\n\n"
    "🕒 Подано: {submitted_at}"
)
DEFAULT_MESSAGING_GATEWAY_HEADER_NEW_TEMPLATE = "💰 Новая заявка на расход № {request_id}"
DEFAULT_MESSAGING_GATEWAY_HEADER_STEP_APPROVED_TEMPLATE = "✅ Заявка № {request_id} одобрена"
DEFAULT_MESSAGING_GATEWAY_HEADER_FULLY_APPROVED_TEMPLATE = "✅ Заявка № {request_id} полностью одобрена"
DEFAULT_MESSAGING_GATEWAY_HEADER_CLOSED_TEMPLATE = "☑️ Заявка № {request_id} закрыта"
DEFAULT_MESSAGING_GATEWAY_HEADER_REJECTED_TEMPLATE = "❌ Заявка № {request_id} отклонена"
DEFAULT_MESSAGING_GATEWAY_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE = "Ответственный за оплату: {payment_responsible}"
DEFAULT_MESSAGING_GATEWAY_SUBHEADER_REJECTED_BY_TEMPLATE = "Пользователь отклонивший заявку: {rejected_by}"


@dataclass(frozen=True)
class N8nIntegrationSettings:
    integration_token: str


@dataclass(frozen=True)
class RequestsGatewaySettings:
    bearer_token: str


@dataclass(frozen=True)
class NotesIntegrationSettings:
    telegram_api_base_url: str
    target_path_request: str
    target_path_cash: str
    target_path_bank: str


def _integration_config(tenant: Tenant | None) -> TenantIntegrationConfig | None:
    if tenant is None:
        return None
    return TenantIntegrationConfig.objects.filter(tenant=tenant).first()


def get_messaging_gateway_settings(*, tenant: Tenant | None = None) -> MessagingGatewaySettings:
    """
    Messaging gateway URL and actions are deployment-wide (Django settings / env).
    Telegram card copy uses built-in defaults; tenant subdomain only scopes API access and DB rows.
    """
    _ = tenant
    dispatch_url = (getattr(settings, "MESSAGING_GATEWAY_SEND_URL", "") or "").strip()
    send_action = (getattr(settings, "MESSAGING_GATEWAY_SEND_ACTION", "") or "").strip() or "send_interactive"
    edit_action = (getattr(settings, "MESSAGING_GATEWAY_EDIT_ACTION", "") or "").strip() or "edit_interactive"
    draft_notification_action = (getattr(settings, "MESSAGING_GATEWAY_DRAFT_ACTION", "") or "").strip() or "send"
    return MessagingGatewaySettings(
        dispatch_url=dispatch_url,
        send_action=send_action,
        edit_action=edit_action,
        draft_notification_action=draft_notification_action,
        message_template=DEFAULT_MESSAGING_GATEWAY_MESSAGE_TEMPLATE,
        header_new_template=DEFAULT_MESSAGING_GATEWAY_HEADER_NEW_TEMPLATE,
        header_step_approved_template=DEFAULT_MESSAGING_GATEWAY_HEADER_STEP_APPROVED_TEMPLATE,
        header_fully_approved_template=DEFAULT_MESSAGING_GATEWAY_HEADER_FULLY_APPROVED_TEMPLATE,
        header_closed_template=DEFAULT_MESSAGING_GATEWAY_HEADER_CLOSED_TEMPLATE,
        header_rejected_template=DEFAULT_MESSAGING_GATEWAY_HEADER_REJECTED_TEMPLATE,
        subheader_payment_responsible_template=DEFAULT_MESSAGING_GATEWAY_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE,
        subheader_rejected_by_template=DEFAULT_MESSAGING_GATEWAY_SUBHEADER_REJECTED_BY_TEMPLATE,
    )


def get_n8n_integration_settings(*, tenant: Tenant | None) -> N8nIntegrationSettings:
    cfg = _integration_config(tenant)
    integration_token = (cfg.get_n8n_integration_token() if cfg else "") or (
        getattr(settings, "N8N_INTEGRATION_TOKEN", "") or ""
    ).strip()
    return N8nIntegrationSettings(integration_token=integration_token)


def get_requests_gateway_settings(*, tenant: Tenant | None) -> RequestsGatewaySettings:
    cfg = _integration_config(tenant)
    bearer_token = (cfg.get_requests_file_gateway_token() if cfg else "") or (
        getattr(settings, "N8N_TOKEN", "") or ""
    ).strip()
    return RequestsGatewaySettings(bearer_token=bearer_token)


def get_notes_integration_settings(*, tenant: Tenant | None) -> NotesIntegrationSettings:
    return NotesIntegrationSettings(
        telegram_api_base_url="https://api.telegram.org",
        target_path_request="/app/requests/{id}",
        target_path_cash="/app/cash/{id}",
        target_path_bank="/app/bank/{id}",
    )


@dataclass(frozen=True)
class PortalFeedbackSettings:
    recipient_id: int | None
    action: str


def get_request_ai_chat_webhook_url(*, tenant: Tenant | None) -> str:
    cfg = _integration_config(tenant)
    return (cfg.request_ai_chat_webhook_url if cfg else "").strip()


def get_portal_feedback_settings(*, tenant: Tenant | None) -> PortalFeedbackSettings:
    cfg = _integration_config(tenant)
    chat_id = cfg.messaging_gateway_feedback_recipient_id if cfg else None
    raw_action = (cfg.messaging_gateway_feedback_action.strip() if cfg else "") or ""
    action = raw_action or "send_portal_feedback"
    return PortalFeedbackSettings(recipient_id=chat_id, action=action)
