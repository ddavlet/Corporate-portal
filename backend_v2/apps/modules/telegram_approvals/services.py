from __future__ import annotations
import logging
from html import escape

import requests
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.requests.models import Approval, Request
from apps.modules.telegram_approvals.models import Notification, TelegramMessage
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


def normalize_gateway_buttons(buttons: list | None) -> list[list[dict]]:
    """
    Normalize module-specific button payloads to gateway format.
    Supported button actions:
    - {"value": "..."} for callback actions
    - {"callback_data": "..."} (legacy alias) -> converted to value
    - {"url": "..."} for webapp links
    """
    if not buttons:
        return []
    normalized_rows: list[list[dict]] = []
    for row in buttons:
        if not isinstance(row, list):
            continue
        normalized_row: list[dict] = []
        for button in row:
            if not isinstance(button, dict):
                continue
            label = str(button.get("label") or "").strip()
            if not label:
                continue
            if button.get("url"):
                normalized_row.append({"label": label, "url": str(button.get("url"))})
                continue
            action_value = button.get("value")
            if action_value in (None, ""):
                action_value = button.get("callback_data")
            if action_value in (None, ""):
                continue
            normalized_row.append({"label": label, "value": str(action_value)})
        if normalized_row:
            normalized_rows.append(normalized_row)
    return normalized_rows


def build_gateway_payload(
    *,
    action: str,
    tenant_id: int | str | None,
    recipient_id: int | str | None,
    bot_token: str,
    message_text: str,
    approval_id: int | str | None = None,
    request_id: int | str | None = None,
    message_id: int | None = None,
    buttons: list | None = None,
) -> dict:
    payload: dict = {
        "action": action,
        "text": message_text,
        "recipient_id": str(recipient_id) if recipient_id is not None else "",
        "bot_token": bot_token,
        "tenant_id": str(tenant_id) if tenant_id is not None else "",
        "buttons": normalize_gateway_buttons(buttons),
    }
    if approval_id is not None:
        payload["approval_id"] = str(approval_id)
    if request_id is not None:
        payload["request_id"] = request_id
    if message_id is not None:
        payload["message_id"] = message_id
    return payload


def apply_gateway_message_lifecycle(
    *,
    obj,
    message_id: int | None,
    message_field: str = "gateway_message_id",
    sent_field: str = "message_sent",
    sent_at_field: str = "message_sent_at",
) -> bool:
    """
    Apply transport delivery lifecycle fields to approval-like models.
    Returns True when at least one field was updated.
    """
    if message_id is None:
        return False
    updates: list[str] = []
    if getattr(obj, message_field, None) != message_id:
        setattr(obj, message_field, message_id)
        updates.append(message_field)
    if not getattr(obj, sent_field, False):
        setattr(obj, sent_field, True)
        updates.append(sent_field)
    if getattr(obj, sent_at_field, None) is None:
        setattr(obj, sent_at_field, timezone.now())
        updates.append(sent_at_field)
    if updates:
        obj.save(update_fields=updates)
        return True
    return False


def ensure_callback_identity(
    *,
    callback_message_id: int | None,
    stored_message_id: int | None,
    callback_recipient_id: str | None,
    stored_recipient_id: str | None,
    callback_external_user_id: int | None,
    stored_external_user_id: int | None,
    message_id_error: str = "Callback message_id does not match stored message_id.",
    recipient_error: str = "Recipient is not allowed for this approval.",
    user_error: str = "User is not allowed for this approval.",
) -> None:
    """
    Shared callback identity guard for approval-like entities.
    Validates optional message/chat/user bindings when they are configured.
    """
    if (
        callback_message_id is not None
        and stored_message_id is not None
        and stored_message_id != callback_message_id
    ):
        raise ValidationError({"message_id": message_id_error})
    if (
        stored_recipient_id is not None
        and str(stored_recipient_id).strip() != (str(callback_recipient_id or "").strip())
    ):
        raise ValidationError({"recipient_id": recipient_error})
    if (
        stored_external_user_id is not None
        and callback_external_user_id is not None
        and int(stored_external_user_id) != int(callback_external_user_id)
    ):
        raise ValidationError({"user_id": user_error})


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
    Records a Notification linked to the sent TelegramMessage for debugging.
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
    dispatcher = TelegramDispatcher(request_obj.tenant)
    message = dispatcher.send(
        action=action,
        recipient_id=chat_id,
        text=message_text,
        buttons=[],
        link=None,
        request_id=request_obj.pk,
    )
    if message is not None:
        Notification.objects.create(
            tenant=request_obj.tenant,
            kind=Notification.KIND_DRAFT,
            telegram_message=message,
            content_type=ContentType.objects.get_for_model(Request),
            object_id=request_obj.pk,
        )
        return True
    return False


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


class TelegramDispatcher:
    """
    Single outbound hub for tg-gateway.

    Owns gateway mechanics (payload build + POST + message_id parsing) and persistence of
    the sent message as a ``TelegramMessage`` row. Callers supply content (text, buttons,
    recipient) and an optional ``link`` — a domain object with a OneToOne ``telegram_message``
    (e.g. ``Approval`` / ``Task``) — which gets wired to the created record. ``TelegramMessage``
    stays a passive model; all logic lives here (CLAUDE.md: models are not business logic).
    """

    def __init__(self, tenant):
        self.tenant = tenant
        self.bot_token = get_tenant_bot_token(tenant)

    def _post(self, payload: dict) -> dict | None:
        return post_messaging_gateway(tenant=self.tenant, payload=payload)

    @staticmethod
    def _link(link, message: TelegramMessage) -> None:
        if link is None:
            return
        link.telegram_message = message
        link.save(update_fields=["telegram_message"])

    def send(
        self,
        *,
        action: str,
        recipient_id,
        text: str,
        buttons: list | None = None,
        link=None,
        external_user_id: int | None = None,
        approval_id: int | str | None = None,
        request_id: int | str | None = None,
        require_message_id: bool = False,
    ) -> TelegramMessage | None:
        """Send a new message. Returns the persisted TelegramMessage, or None when the
        gateway is unreachable. With ``require_message_id`` a reachable gateway that returns
        no message_id raises ``TelegramDispatchMissingMessageId`` (hard error for dispatch)."""
        payload = build_gateway_payload(
            action=action,
            tenant_id=getattr(self.tenant, "id", None),
            recipient_id=recipient_id,
            bot_token=self.bot_token,
            message_text=text,
            approval_id=approval_id,
            request_id=request_id,
            buttons=buttons or [],
        )
        response_data = self._post(payload)
        if response_data is None:
            return None
        message_id = extract_message_id(response_data)
        if message_id is None:
            if require_message_id:
                response_type = type(response_data).__name__
                response_keys = list(response_data.keys()) if isinstance(response_data, dict) else []
                logger.error(
                    "Telegram bridge response missing message_id approval_id=%s request_id=%s action=%s response_type=%s response_keys=%s",
                    approval_id,
                    request_id,
                    action,
                    response_type,
                    response_keys,
                )
                raise TelegramDispatchMissingMessageId(
                    {
                        "telegram": (
                            "Bridge dispatch must return message_id for action. "
                            f"approval_id={approval_id} request_id={request_id} action={action} "
                            f"(response_type={response_type}, response_keys={response_keys})"
                        )
                    }
                )
            return None
        message = TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id=str(recipient_id or ""),
            external_user_id=external_user_id,
            message_id=message_id,
            sent_at=timezone.now(),
        )
        self._link(link, message)
        return message

    def edit(
        self,
        message: TelegramMessage,
        *,
        action: str,
        text: str,
        buttons: list | None = None,
        recipient_id=None,
        approval_id: int | str | None = None,
        request_id: int | str | None = None,
    ) -> TelegramMessage | None:
        """Edit an existing message in place. Returns the message, or None on gateway failure."""
        payload = build_gateway_payload(
            action=action,
            tenant_id=getattr(self.tenant, "id", None),
            recipient_id=recipient_id if recipient_id is not None else message.recipient_id,
            bot_token=self.bot_token,
            message_text=text,
            approval_id=approval_id,
            request_id=request_id,
            message_id=message.message_id,
            buttons=buttons or [],
        )
        response_data = self._post(payload)
        if response_data is None:
            return None
        return message

    def deactivate(
        self,
        message: TelegramMessage,
        *,
        action: str,
        text: str,
        recipient_id=None,
        approval_id: int | str | None = None,
        request_id: int | str | None = None,
    ) -> TelegramMessage | None:
        """Re-render the message without buttons (drops the inline keyboard)."""
        return self.edit(
            message,
            action=action,
            text=text,
            buttons=[],
            recipient_id=recipient_id,
            approval_id=approval_id,
            request_id=request_id,
        )

    def delete(self, message: TelegramMessage, *, action: str = "delete", recipient_id=None) -> None:
        payload = build_gateway_payload(
            action=action,
            tenant_id=getattr(self.tenant, "id", None),
            recipient_id=recipient_id if recipient_id is not None else message.recipient_id,
            bot_token=self.bot_token,
            message_text="",
            message_id=message.message_id,
        )
        self._post(payload)


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
        telegram_message__isnull=True,
        approver_recipient_id__isnull=False,
    )
    if step_type is not None:
        approvals_qs = approvals_qs.filter(step_type=step_type)
    approvals = list(approvals_qs.select_related("approver_user").order_by("id"))
    if not approvals:
        return 0
    dispatcher = TelegramDispatcher(locked.tenant)
    send_action = get_requests_messaging_gateway_settings(tenant=locked.tenant).send_action
    sent_count = 0
    for approval in approvals:
        message_text = build_approval_message(request_obj=locked, approval=approval)
        include_buttons = approval.step_type != Approval.STEP_TYPE_NOTIFICATION
        message = dispatcher.send(
            action=send_action,
            recipient_id=approval.approver_recipient_id,
            text=message_text,
            buttons=_buttons(approval=approval) if include_buttons else [],
            link=approval,
            external_user_id=approval.approver_external_user_id,
            approval_id=approval.id,
            request_id=approval.request_id,
            require_message_id=True,
        )
        if message is None:
            # Gateway unreachable — leave this approver for a later dispatch.
            continue
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
    if approval.telegram_message_id is None or approval.approver_recipient_id is None:
        return False
    req = request_context or approval.request
    dispatcher = TelegramDispatcher(req.tenant)
    message = dispatcher.edit(
        approval.telegram_message,
        action=get_requests_messaging_gateway_settings(tenant=req.tenant).edit_action,
        text=build_approval_message(request_obj=req, approval=approval),
        buttons=_buttons(approval=approval),
        recipient_id=approval.approver_recipient_id,
        approval_id=approval.id,
        request_id=approval.request_id,
    )
    return message is not None


def deactivate_approval_message_buttons(*, approval: Approval, request_context: Request | None = None) -> bool:
    if approval.telegram_message_id is None or approval.approver_recipient_id is None:
        return False
    req = request_context or approval.request
    dispatcher = TelegramDispatcher(req.tenant)
    message = dispatcher.deactivate(
        approval.telegram_message,
        action=get_requests_messaging_gateway_settings(tenant=req.tenant).edit_action,
        text=build_approval_message(request_obj=req, approval=approval),
        recipient_id=approval.approver_recipient_id,
        approval_id=approval.id,
        request_id=approval.request_id,
    )
    return message is not None


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
            telegram_message__isnull=False,
            approver_recipient_id__isnull=False,
        )
        .select_related("request", "request__tenant", "approver_user", "telegram_message")
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
        if approval.telegram_message_id is not None:
            deactivate_approval_message_buttons(approval=approval, request_context=locked)
        approval.decision = Approval.DECISION_CANCELED
        approval.decided_at = timezone.now()
        approval.comment = "Автоматически: отменено повторной отправкой шага."
        # Unlink so the next refresh cycle skips this canceled row (no longer counts as
        # "sent"); the TelegramMessage history row itself is left intact.
        approval.telegram_message = None
        approval.save(update_fields=["decision", "decided_at", "comment", "telegram_message"])
        Approval.objects.create(
            request=locked,
            approver_user=approval.approver_user,
            approver_recipient_id=approval.approver_recipient_id,
            approver_external_user_id=approval.approver_external_user_id,
            step=approval.step,
            step_type=approval.step_type,
            decision=Approval.DECISION_PENDING,
            resend_key=idempotency_key,
            replaced_approval=approval,
        )
        created += 1
    return created
