"""PAYED hook for «Пополнение» requests: personal Telegram message to the configured recipients.

Never raises into the payment flow: own savepoint for DB work, delivery after commit, every
failure is logged and recorded on the CardTopupNotification row.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.modules.cash_desk.card_topup_formatter import build_card_topup_text
from apps.modules.cash_desk.models import CardTopupNotification, CardTopupNotifyConfig
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.requests.models import Request
from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import wallet_balance_payload
from apps.tenants.models import TenantMembership

logger = logging.getLogger(__name__)
User = get_user_model()

NO_TELEGRAM_ERROR = "У пользователя не привязан Telegram"
NO_MESSAGE_ID_ERROR = "Шлюз не вернул message_id"


def is_topup_request(request_obj) -> bool:
    return (request_obj.payment_type or "").strip() == Request.PAYMENT_TYPE_TOPUP


def active_recipients(config: CardTopupNotifyConfig) -> list:
    """Configured recipients who are still active users and active members of the tenant."""
    member_ids = TenantMembership.objects.filter(tenant_id=config.tenant_id, is_active=True).values_list(
        "user_id", flat=True
    )
    return list(config.recipients.filter(is_active=True, id__in=member_ids).order_by("id"))


def card_display_name(wallet: Wallet) -> str:
    """Same rule as `display_name` in wallets.services.balances_for_tenant_channel for card wallets."""
    account = wallet.corporate_card_account
    if account is None:
        return wallet.currency or ""
    return (account.label or "").strip() or account.currency


def resolve_card_wallet(request_obj) -> Wallet | None:
    """request.wallet_ref when it is a corporate card of the tenant, else the tenant's first card (by id)."""
    base = Wallet.objects.filter(
        tenant_id=request_obj.tenant_id, wallet_type=Wallet.Type.CORPORATE_CARD
    ).select_related("corporate_card_account")
    if request_obj.wallet_ref_id:
        wallet = base.filter(pk=request_obj.wallet_ref_id).first()
        if wallet is not None:
            return wallet
    return base.order_by("id").first()


def card_payload(request_obj) -> dict | None:
    wallet = resolve_card_wallet(request_obj)
    if wallet is None:
        return None
    balance = wallet_balance_payload(wallet=wallet)
    return {
        "name": card_display_name(wallet),
        "current_balance": balance.get("current_balance"),
        "currency": balance.get("currency") or wallet.currency,
    }


def _mark(notification: CardTopupNotification, *, status: str, error: str = "", telegram_message=None) -> None:
    notification.status = status
    notification.error = error
    fields = ["status", "error", "updated_at"]
    if telegram_message is not None:
        notification.telegram_message = telegram_message
        fields.append("telegram_message")
    notification.save(update_fields=fields)


def _deliver(notification: CardTopupNotification, *, text: str) -> None:
    request_obj = notification.request
    tenant = request_obj.tenant
    recipient = notification.recipient
    if not recipient.telegram_chat_id:
        _mark(notification, status=CardTopupNotification.Status.SKIPPED, error=NO_TELEGRAM_ERROR)
        return
    telegram_message = TelegramDispatcher(tenant).send(
        action=get_requests_messaging_gateway_settings(tenant=tenant).send_action,
        recipient_id=str(recipient.telegram_chat_id),
        text=text,
        external_user_id=recipient.telegram_from_id,
        request_id=request_obj.pk,
    )
    if telegram_message is None:
        _mark(notification, status=CardTopupNotification.Status.FAILED, error=NO_MESSAGE_ID_ERROR)
        logger.error(
            "cash_desk.card_topup: message not delivered notification_id=%s request_id=%s",
            notification.pk, request_obj.pk,
        )
        return
    _mark(notification, status=CardTopupNotification.Status.SENT, telegram_message=telegram_message)


def send_card_topup_notifications(notification_ids: list[int]) -> None:
    """After-commit delivery. Each recipient is isolated: one failure does not stop the others."""
    try:
        notifications = list(
            CardTopupNotification.objects.select_related("request__tenant", "recipient")
            .filter(pk__in=notification_ids, status=CardTopupNotification.Status.PENDING)
            .order_by("id")
        )
        if not notifications:
            return
        text = None
        for notification in notifications:
            try:
                if text is None:
                    request_obj = notification.request
                    text = build_card_topup_text(request_obj=request_obj, card=card_payload(request_obj))
                _deliver(notification, text=text)
            except Exception as exc:
                logger.exception(
                    "cash_desk.card_topup: send failed notification_id=%s request_id=%s",
                    notification.pk, notification.request_id,
                )
                try:
                    _mark(
                        notification,
                        status=CardTopupNotification.Status.FAILED,
                        error=str(exc) or exc.__class__.__name__,
                    )
                except Exception:
                    logger.exception("cash_desk.card_topup: cannot mark failed notification_id=%s", notification.pk)
    except Exception:
        logger.exception("cash_desk.card_topup: send_card_topup_notifications crashed ids=%s", notification_ids)


def _handle_payed(request_obj) -> None:
    if not is_topup_request(request_obj):
        return
    config = CardTopupNotifyConfig.objects.filter(tenant_id=request_obj.tenant_id, is_active=True).first()
    if config is None:
        return
    recipients = active_recipients(config)
    if not recipients:
        logger.info("cash_desk.card_topup: no active recipients tenant_id=%s", request_obj.tenant_id)
        return

    pending_ids: list[int] = []
    for user in recipients:
        notification, created = CardTopupNotification.objects.get_or_create(
            request=request_obj,
            recipient=user,
            defaults={"status": CardTopupNotification.Status.PENDING},
        )
        if not created:
            logger.info(
                "cash_desk.card_topup: repeated PAYED ignored request_id=%s recipient_id=%s", request_obj.pk, user.pk
            )
            continue
        if not user.telegram_chat_id:
            _mark(notification, status=CardTopupNotification.Status.SKIPPED, error=NO_TELEGRAM_ERROR)
            logger.warning(
                "cash_desk.card_topup: recipient without Telegram skipped request_id=%s user_id=%s",
                request_obj.pk, user.pk,
            )
            continue
        pending_ids.append(notification.pk)

    if pending_ids:
        transaction.on_commit(lambda: send_card_topup_notifications(pending_ids), robust=True)


def on_request_payed(*, request_obj) -> None:
    """Registered PAYED handler (see apps.CashDeskConfig.ready). Never breaks the payment flow.

    Own savepoint: `dispatch_request_payed_event_handlers` opens none, so a DB error here would
    otherwise abort the caller's transaction.
    """
    try:
        with transaction.atomic():
            _handle_payed(request_obj)
    except Exception:
        logger.exception(
            "cash_desk.card_topup: payed handler failed request_id=%s tenant_id=%s",
            getattr(request_obj, "pk", None), getattr(request_obj, "tenant_id", None),
        )
