from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from apps.tenants.models import Tenant, TenantIntegrationConfig


@dataclass(frozen=True)
class TelegramApprovalsSettings:
    dispatch_url: str
    bridge_token: str
    send_action: str
    edit_action: str
    message_template: str
    header_new_template: str
    header_step_approved_template: str
    header_fully_approved_template: str
    header_closed_template: str
    header_rejected_template: str
    subheader_payment_responsible_template: str
    subheader_rejected_by_template: str


DEFAULT_TELEGRAM_APPROVALS_MESSAGE_TEMPLATE = (
    "<b>{header}</b>\n"
    "{subheader_block}"
    "Компания: {company_payer}\n"
    "Проект: {project_title}\n\n"
    "<b>💰 Финансы</b>\n"
    "• Поставщик: {vendor}\n"
    "• Категория: {category}\n"
    "• Сумма: {amount} {currency}\n"
    "• Тип оплаты: {payment_type}\n\n"
    "<b>📌 Назначение</b>\n"
    "• Назначение платежа: {payment_purpose}\n"
    "• Описание: {description}\n"
    "• Месяц начисления: {accrual_month}\n\n"
    "<b>⏱ Статус</b>\n"
    "• Срочность: {urgency}\n"
    "• Заявитель: {requester}\n\n"
    "🕒 Подано: {submitted_at}"
)
DEFAULT_TELEGRAM_APPROVALS_HEADER_NEW_TEMPLATE = "💰 Новая заявка на расход № {request_id}"
DEFAULT_TELEGRAM_APPROVALS_HEADER_STEP_APPROVED_TEMPLATE = "✅ Заявка № {request_id} одобрена"
DEFAULT_TELEGRAM_APPROVALS_HEADER_FULLY_APPROVED_TEMPLATE = "✅ Заявка № {request_id} полностью одобрена"
DEFAULT_TELEGRAM_APPROVALS_HEADER_CLOSED_TEMPLATE = "☑️ Заявка № {request_id} закрыта"
DEFAULT_TELEGRAM_APPROVALS_HEADER_REJECTED_TEMPLATE = "❌ Заявка № {request_id} отклонена"
DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE = "Отвественный за оплату: {payment_responsible}"
DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_REJECTED_BY_TEMPLATE = "Пользователь отклонивший заявку: {rejected_by}"


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


def get_telegram_approvals_settings(*, tenant: Tenant | None) -> TelegramApprovalsSettings:
    cfg = _integration_config(tenant)
    cfg_get = (lambda attr: getattr(cfg, attr, "") if cfg else "")
    dispatch_url = (cfg.telegram_approvals_bridge_dispatch_url.strip() if cfg else "") or (
        getattr(settings, "TELEGRAM_APPROVALS_BRIDGE_DISPATCH_URL", "") or ""
    ).strip()
    bridge_token = (cfg.get_telegram_approvals_bridge_token() if cfg else "") or (
        getattr(settings, "TELEGRAM_APPROVALS_BRIDGE_TOKEN", "") or ""
    ).strip()
    send_action = (cfg_get("telegram_approvals_send_action").strip()) or "send_approval_message"
    edit_action = (cfg_get("telegram_approvals_edit_action").strip()) or "edit_approval_message"
    message_template = cfg_get("telegram_approvals_message_template") or DEFAULT_TELEGRAM_APPROVALS_MESSAGE_TEMPLATE
    header_new_template = cfg_get("telegram_approvals_header_new_template") or DEFAULT_TELEGRAM_APPROVALS_HEADER_NEW_TEMPLATE
    header_step_approved_template = (
        cfg_get("telegram_approvals_header_step_approved_template") or DEFAULT_TELEGRAM_APPROVALS_HEADER_STEP_APPROVED_TEMPLATE
    )
    header_fully_approved_template = (
        cfg_get("telegram_approvals_header_fully_approved_template") or DEFAULT_TELEGRAM_APPROVALS_HEADER_FULLY_APPROVED_TEMPLATE
    )
    header_closed_template = cfg_get("telegram_approvals_header_closed_template") or DEFAULT_TELEGRAM_APPROVALS_HEADER_CLOSED_TEMPLATE
    header_rejected_template = (
        cfg_get("telegram_approvals_header_rejected_template") or DEFAULT_TELEGRAM_APPROVALS_HEADER_REJECTED_TEMPLATE
    )
    subheader_payment_responsible_template = (
        cfg_get("telegram_approvals_subheader_payment_responsible_template")
        or DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_PAYMENT_RESPONSIBLE_TEMPLATE
    )
    subheader_rejected_by_template = (
        cfg_get("telegram_approvals_subheader_rejected_by_template")
        or DEFAULT_TELEGRAM_APPROVALS_SUBHEADER_REJECTED_BY_TEMPLATE
    )
    return TelegramApprovalsSettings(
        dispatch_url=dispatch_url,
        bridge_token=bridge_token,
        send_action=send_action,
        edit_action=edit_action,
        message_template=message_template,
        header_new_template=header_new_template,
        header_step_approved_template=header_step_approved_template,
        header_fully_approved_template=header_fully_approved_template,
        header_closed_template=header_closed_template,
        header_rejected_template=header_rejected_template,
        subheader_payment_responsible_template=subheader_payment_responsible_template,
        subheader_rejected_by_template=subheader_rejected_by_template,
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

