from __future__ import annotations
import logging
from html import escape

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.requests.models import Approval, Request
from apps.modules.telegram_approvals.formatter import (
    build_approval_message,
    build_request_draft_public_url,
    build_auto_request_template_public_url,
    _format_billing_month,
    _format_amount_for_telegram,
    _format_contract_block,
    _display_user_name,
    _buttons,
    _telegram_card_should_be_readonly,
)

logger = logging.getLogger(__name__)


class TelegramDispatchMissingMessageId(ValidationError):
    pass


def _ensure_bridge_message_id(
    *,
    approval: Approval,
    response_data: dict | None,
    request_id: int,
    action: str,
) -> None:
    _maybe_set_message_id(approval=approval, response_data=response_data)
    if approval.gateway_message_id is not None:
        return
    response_type = type(response_data).__name__
    response_keys = list(response_data.keys()) if isinstance(response_data, dict) else []
    logger.error(
        "Telegram bridge response missing message_id approval_id=%s request_id=%s payload_action=%s response_type=%s response_keys=%s",
        approval.id,
        request_id,
        action,
        response_type,
        response_keys,
    )
    raise TelegramDispatchMissingMessageId(
        {
            "telegram": (
                "Bridge dispatch must return message_id for action. "
                f"approval_id={approval.id} request_id={request_id} action={action} "
                f"(response_type={response_type}, response_keys={response_keys})"
            )
        }
    )


def get_tenant_bot_token(tenant) -> str:
    """Telegram bot token lives only on `Tenant` (encrypted field)."""
    if tenant is None:
        return ""
    try:
        token = (tenant.get_telegram_bot_token() or "").strip()
    except Exception:
        logger.exception("Failed to read Telegram bot token for tenant=%s", getattr(tenant, "pk", None))
        token = ""
    return token


def _resolve_gateway_url_for_tenant(tenant) -> str:
    if tenant is not None:
        try:
            url = (get_requests_messaging_gateway_settings(tenant=tenant).dispatch_url or "").strip()
            if url:
                return url
        except Exception:
            logger.exception(
                "Failed to resolve gateway URL for tenant=%s", getattr(tenant, "pk", None)
            )
    return (getattr(settings, "MESSAGING_GATEWAY_SEND_URL", "") or "").strip()


def dispatch_draft_request_notification(
    *, request_obj: Request, chat_id: int | None, template_id: int | None = None
) -> bool:
    """
    Outbound n8n/Telegram: action from settings (default send_draft_notification), no Approval row.
    """
    if chat_id is None:
        logger.info("draft notification skipped: no chat_id for request_id=%s", request_obj.pk)
        return False
    settings_obj = get_requests_messaging_gateway_settings(tenant=request_obj.tenant)
    action = (settings_obj.draft_notification_action or "").strip() or "send"
    draft_url = build_request_draft_public_url(request_obj=request_obj)
    template_url = build_auto_request_template_public_url(request_obj=request_obj, template_id=template_id)
    title = escape(str(request_obj.title or ""))
    billing_month = escape(_format_billing_month(request_obj))
    url_part = ""
    if draft_url:
        url_part = f'\n<a href="{escape(draft_url)}">{escape(draft_url)}</a>'
    template_part = ""
    if template_url:
        template_part = f'\n\nШаблон автозаявки:\n<a href="{escape(template_url)}">{escape(template_url)}</a>'
    vendor_name = (request_obj.vendor_ref.name if request_obj.vendor_ref_id and request_obj.vendor_ref else request_obj.vendor) or "-"
    requester_name = _display_user_name(request_obj.requester if request_obj.requester_id else None)
    amount_text = _format_amount_for_telegram(request_obj.amount)
    currency_text = str(request_obj.currency or "-")
    payment_type_text = str(request_obj.payment_type or "-")
    payment_purpose_text = str(request_obj.payment_purpose or "-")
    description_text = str(request_obj.description or "-")
    urgency_text = str(request_obj.urgency or "-")
    contract_block = _format_contract_block(request_obj)
    message_text = (
        f"<b>📝 Черновик заявки № {request_obj.pk}</b>\n"
        f"{title}\n\n"
        f"<b>💰 Финансы</b>\n"
        f"• Поставщик: {escape(str(vendor_name))}\n"
        f"• Сумма: {escape(amount_text)} {escape(currency_text)}\n"
        f"• Тип оплаты: {escape(payment_type_text)}"
        f"{contract_block}\n\n"
        f"<b>📌 Назначение</b>\n"
        f"• Назначение платежа: {escape(payment_purpose_text)}\n"
        f"• Описание: {escape(description_text)}\n"
        f"• Месяц начисления: {billing_month}\n\n"
        f"<b>⏱ Статус</b>\n"
        f"• Срочность: {escape(urgency_text)}\n"
        f"• Заявитель: {escape(requester_name)}\n\n"
        f"Укажите сумму и отправьте заявку на согласование кнопкой в этом сообщении.{url_part}{template_part}"
    )
    payload = {
        "action": action,
        "text": message_text,
        "recipient_id": str(chat_id),
        "bot_token": get_tenant_bot_token(request_obj.tenant),
        "tenant_id": str(request_obj.tenant_id),
        "request_id": request_obj.pk,
        "buttons": [],
    }
    response_data = _post_to_gateway(request_obj=request_obj, payload=payload)
    return response_data is not None


def _dispatch_payload(
    *,
    action: str,
    request_obj: Request,
    approval: Approval,
    message_text: str,
    include_buttons: bool = True,
) -> dict:
    payload: dict = {
        "action": action,
        "text": message_text,
        "recipient_id": str(approval.approver_recipient_id),
        "bot_token": get_tenant_bot_token(request_obj.tenant),
        "tenant_id": str(request_obj.tenant_id),
        "approval_id": str(approval.id),
        "request_id": approval.request_id,
    }
    payload["buttons"] = _buttons(approval=approval) if include_buttons else []
    if approval.gateway_message_id:
        payload["message_id"] = approval.gateway_message_id
    return payload


def _parse_bridge_response(resp: requests.Response) -> dict | None:
    if not resp.content:
        return {}
    data = resp.json()
    # Some n8n flows return a one-item list with telegram response object.
    if isinstance(data, list):
        if not data:
            return {}
        first = data[0]
        return first if isinstance(first, dict) else {}
    return data if isinstance(data, dict) else {}


def post_messaging_gateway(*, tenant, payload: dict) -> dict | None:
    """POST a platform-neutral payload to the messaging gateway using tenant context."""
    url = _resolve_gateway_url_for_tenant(tenant)
    if not url:
        logger.warning("Messaging gateway: no URL configured for tenant=%s", getattr(tenant, "pk", None))
        return None
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        if resp.status_code >= 400:
            logger.warning(
                "Gateway returned HTTP %s for action=%s approval_id=%s",
                resp.status_code,
                payload.get("action"),
                payload.get("approval_id"),
            )
            return None
        return _parse_bridge_response(resp)
    except Exception:
        logger.exception(
            "Failed to call messaging gateway action=%s approval_id=%s",
            payload.get("action"),
            payload.get("approval_id"),
        )
        return None


def _post_to_gateway(*, request_obj: Request, payload: dict) -> dict | None:
    """POST a platform-neutral payload to the messaging gateway. Failures are logged only."""
    return post_messaging_gateway(tenant=getattr(request_obj, "tenant", None), payload=payload)


def extract_message_id(response_data: dict | None) -> int | None:
    """Extract Telegram message_id from a gateway response dict (handles nested result.message_id)."""
    if not isinstance(response_data, dict):
        return None
    raw = response_data.get("message_id")
    if raw in (None, ""):
        result = response_data.get("result")
        if isinstance(result, dict):
            raw = result.get("message_id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _maybe_set_message_id(*, approval: Approval, response_data: dict | None) -> None:
    message_id = extract_message_id(response_data)
    if message_id is None:
        return
    updates = []
    approval.gateway_message_id = message_id
    updates.append("gateway_message_id")
    if not approval.message_sent:
        approval.message_sent = True
        updates.append("message_sent")
    if approval.message_sent_at is None:
        approval.message_sent_at = timezone.now()
        updates.append("message_sent_at")
    if updates:
        approval.save(update_fields=updates)


def _current_pending_step(request_obj: Request) -> int | None:
    if request_obj.status in {Request.STATUS_REJECTED, Request.STATUS_PAYED}:
        return None
    if request_obj.status == Request.STATUS_APPROVED:
        pending_payment_steps = (
            Approval.objects.filter(
                request=request_obj,
                step_type=Approval.STEP_TYPE_PAYMENT,
                decision=Approval.DECISION_PENDING,
            )
            .order_by("step")
            .values_list("step", flat=True)
        )
        return next(iter(pending_payment_steps), None)
    status_to_step = {
        Request.STATUS_PROGRESS_1: 1,
        Request.STATUS_PROGRESS_2: 2,
        Request.STATUS_PROGRESS_3: 3,
        Request.STATUS_PROGRESS_4: 4,
        Request.STATUS_PROGRESS_5: 5,
    }
    return status_to_step.get(request_obj.status)


def current_pending_step_approvals_count(*, request_obj: Request) -> int:
    current_step = _current_pending_step(request_obj)
    if current_step is None:
        return 0
    return Approval.objects.filter(
        request=request_obj,
        step=current_step,
        decision=Approval.DECISION_PENDING,
        approver_recipient_id__isnull=False,
    ).count()


@transaction.atomic
def dispatch_pending_approvals(*, request_obj: Request, step: int | None = None, step_type: str | None = None) -> int:
    locked = Request.objects.select_for_update(of=("self",)).select_related("contract_ref", "vendor_ref").get(pk=request_obj.pk)
    current_step = step or _current_pending_step(locked)
    if current_step is None:
        return 0
    approvals_qs = Approval.objects.select_for_update().filter(
        request_id=locked.pk,
        step=current_step,
        decision=Approval.DECISION_PENDING,
        message_sent=False,
        approver_recipient_id__isnull=False,
    )
    if step_type is not None:
        approvals_qs = approvals_qs.filter(step_type=step_type)
    approvals = list(approvals_qs.select_related("approver_user").order_by("id"))
    if not approvals:
        return 0
    sent_count = 0
    for approval in approvals:
        message_text = build_approval_message(request_obj=locked, approval=approval)
        include_buttons = approval.step_type != Approval.STEP_TYPE_NOTIFICATION
        payload = _dispatch_payload(
            action=get_requests_messaging_gateway_settings(tenant=locked.tenant).send_action,
            request_obj=locked,
            approval=approval,
            message_text=message_text,
            include_buttons=include_buttons,
        )
        response_data = _post_to_gateway(request_obj=locked, payload=payload)
        if response_data is None:
            continue

        _ensure_bridge_message_id(
            approval=approval,
            response_data=response_data,
            request_id=locked.id,
            action=str(payload.get("action") or ""),
        )
        sent_count += 1
        if approval.step_type == Approval.STEP_TYPE_NOTIFICATION:
            Approval.objects.filter(
                pk=approval.pk,
                decision=Approval.DECISION_PENDING,
            ).update(
                decision=Approval.DECISION_APPROVED,
                decided_at=timezone.now(),
            )
    return sent_count


def edit_approval_message(*, approval: Approval, request_context: Request | None = None) -> bool:
    if not approval.gateway_message_id or approval.approver_recipient_id is None:
        return False
    req = request_context or approval.request
    payload = _dispatch_payload(
        action=get_requests_messaging_gateway_settings(tenant=req.tenant).edit_action,
        request_obj=req,
        approval=approval,
        message_text=build_approval_message(request_obj=req, approval=approval),
    )
    response_data = _post_to_gateway(request_obj=req, payload=payload)
    if response_data is None:
        return False
    _ensure_bridge_message_id(
        approval=approval,
        response_data=response_data,
        request_id=req.id,
        action=str(payload.get("action") or ""),
    )
    return response_data is not None


def deactivate_approval_message_buttons(*, approval: Approval, request_context: Request | None = None) -> bool:
    if not approval.gateway_message_id or approval.approver_recipient_id is None:
        return False
    req = request_context or approval.request
    payload = _dispatch_payload(
        action=get_requests_messaging_gateway_settings(tenant=req.tenant).edit_action,
        request_obj=req,
        approval=approval,
        message_text=build_approval_message(request_obj=req, approval=approval),
        include_buttons=False,
    )
    response_data = _post_to_gateway(request_obj=req, payload=payload)
    if response_data is None:
        return False
    _ensure_bridge_message_id(
        approval=approval,
        response_data=response_data,
        request_id=req.id,
        action=str(payload.get("action") or ""),
    )
    return response_data is not None


def refresh_request_messages(*, request_obj: Request) -> int:
    """
    Notify everyone who was sent a Telegram card (message_sent) and can be edited (message_id + chat).
    Call after status/decision changes so headers match APPROVED / REJECTED / PAYED and buttons drop
    where the step is no longer actionable.
    """
    request_obj.refresh_from_db()
    # Warm FK caches after refresh so the approval-card loop doesn't hit DB per card.
    _ = request_obj.contract_ref
    _ = request_obj.vendor_ref
    approvals = list(
        Approval.objects.filter(
            request=request_obj,
            message_sent=True,
            gateway_message_id__isnull=False,
            approver_recipient_id__isnull=False,
        )
        .select_related("request", "request__tenant", "approver_user")
        .order_by("id")
    )
    updated = 0
    for approval in approvals:
        readonly = _telegram_card_should_be_readonly(request_obj=request_obj, approval=approval)
        if readonly:
            changed = deactivate_approval_message_buttons(approval=approval, request_context=request_obj)
            if changed:
                updated += 1
        else:
            changed = edit_approval_message(approval=approval, request_context=request_obj)
            if changed:
                updated += 1
    return updated


@transaction.atomic
def resend_current_pending_step(*, request_obj: Request, idempotency_key: str | None = None) -> int:
    locked = Request.objects.select_for_update(of=("self",)).select_related("contract_ref", "vendor_ref").get(pk=request_obj.pk)
    current_step = _current_pending_step(locked)
    if current_step is None:
        raise ValidationError({"detail": "Current request status has no active approval step."})

    if idempotency_key:
        existing = Approval.objects.filter(
            request_id=locked.pk,
            step=current_step,
            decision=Approval.DECISION_PENDING,
            resend_key=idempotency_key,
        ).count()
        if existing:
            return existing

    approvals = list(
        Approval.objects.select_for_update()
        .filter(
            request_id=locked.pk,
            step=current_step,
            decision=Approval.DECISION_PENDING,
            approver_recipient_id__isnull=False,
        )
        .select_related("request", "request__tenant", "approver_user")
        .order_by("id")
    )
    if not approvals:
        raise ValidationError({"detail": "No pending approvals on current step for resend."})

    created = 0
    for approval in approvals:
        if approval.gateway_message_id:
            deactivate_approval_message_buttons(approval=approval, request_context=locked)
        approval.decision = Approval.DECISION_CANCELED
        approval.decided_at = timezone.now()
        approval.comment = "Автоматически: отменено повторной отправкой шага."
        # Prevent an extra edit in subsequent refresh cycle for the canceled row.
        approval.message_sent = False
        approval.save(update_fields=["decision", "decided_at", "comment", "message_sent"])
        Approval.objects.create(
            request=locked,
            approver_user=approval.approver_user,
            approver_recipient_id=approval.approver_recipient_id,
            approver_external_user_id=approval.approver_external_user_id,
            step=approval.step,
            step_type=approval.step_type,
            decision=Approval.DECISION_PENDING,
            message_sent=False,
            gateway_message_id=None,
            resend_key=idempotency_key,
            replaced_approval=approval,
        )
        created += 1
    return created
