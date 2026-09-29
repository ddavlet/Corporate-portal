"""Business logic for cash-withdrawal receipts."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.modules.cash_withdrawals import events, formatter, messaging
from apps.modules.cash_withdrawals.models import CashWithdrawalConfig, CashWithdrawalReceipt
from apps.modules.cashier.models import CashRevenue
from apps.tenants.models import TenantMembership

logger = logging.getLogger(__name__)
User = get_user_model()


def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def get_active_config(tenant) -> CashWithdrawalConfig | None:
    return (
        CashWithdrawalConfig.objects.filter(tenant=tenant, is_active=True)
        .select_related("tenant", "card_telegram_chat", "alert_telegram_chat")
        .first()
    )


def find_rule(config, request_obj):
    payment_type = _norm(request_obj.payment_type)
    purpose = _norm(request_obj.payment_purpose)
    if not purpose:
        return None
    for rule in config.rules.select_related("wallet", "wallet__cash_register").all():
        if _norm(rule.payment_type) == payment_type and _norm(rule.payment_purpose) == purpose:
            return rule
    return None


def _send_cards_safely(receipt_id: int) -> None:
    receipt = (
        CashWithdrawalReceipt.objects.select_related("tenant", "request", "wallet", "wallet__cash_register")
        .filter(pk=receipt_id)
        .first()
    )
    if receipt is None:
        return
    try:
        messaging.send_receipt_cards(receipt)
    except Exception:
        logger.exception("cash_withdrawals: send_receipt_cards crashed receipt_id=%s", receipt_id)


def create_receipt_for_request(*, request_obj, send: bool = True) -> CashWithdrawalReceipt | None:
    config = get_active_config(request_obj.tenant)
    if config is None:
        return None
    rule = find_rule(config, request_obj)
    if rule is None:
        return None
    wallet = rule.wallet
    if _norm(request_obj.currency) != _norm(wallet.currency):
        logger.error(
            "cash_withdrawals: currency mismatch request_id=%s request_currency=%s wallet_id=%s wallet_currency=%s",
            request_obj.pk, request_obj.currency, wallet.pk, wallet.currency,
        )
        text = formatter.build_currency_mismatch_text(request_obj=request_obj, wallet=wallet)
        transaction.on_commit(
            lambda: messaging.send_to_alert_recipients(config=config, text=text, request_id=request_obj.pk)
        )
        return None
    receipt, created = CashWithdrawalReceipt.objects.get_or_create(
        request=request_obj,
        defaults={
            "tenant": request_obj.tenant,
            "wallet": wallet,
            "amount": request_obj.amount,
            "currency": request_obj.currency,
        },
    )
    if created:
        logger.info("cash_withdrawals: receipt created receipt_id=%s request_id=%s", receipt.pk, request_obj.pk)
        if send:
            receipt_id = receipt.pk
            transaction.on_commit(lambda: _send_cards_safely(receipt_id))
    return receipt


def on_request_payed(*, request_obj) -> None:
    """Registered PAYED handler (see apps.CashWithdrawalsConfig.ready).

    Runs in its own savepoint: `dispatch_request_payed_event_handlers` catches exceptions
    but opens no savepoint (unlike its REJECTED counterpart), so a DB error raised here
    would otherwise leave Postgres in an aborted-transaction state and break the caller's
    PAYED status save.
    """
    with transaction.atomic():
        create_receipt_for_request(request_obj=request_obj)


def find_confirmer_user(config, telegram_user_id: int):
    """User from the confirmer list whose Telegram id matches and who is an active tenant member."""
    active_ids = TenantMembership.objects.filter(tenant_id=config.tenant_id, is_active=True).values_list(
        "user_id", flat=True
    )
    return (
        User.objects.filter(
            cash_withdrawal_confirmer_rows__config=config,
            is_active=True,
            id__in=active_ids,
        )
        .filter(Q(telegram_from_id=telegram_user_id) | Q(telegram_chat_id=telegram_user_id))
        .order_by("id")
        .first()
    )


def _after_confirm(receipt_id: int) -> None:
    receipt = (
        CashWithdrawalReceipt.objects.select_related(
            "tenant", "request", "wallet", "wallet__cash_register", "confirmed_by", "cash_revenue"
        )
        .filter(pk=receipt_id)
        .first()
    )
    if receipt is None:
        return
    try:
        messaging.refresh_receipt_cards(receipt)
    except Exception:
        logger.exception("cash_withdrawals: refresh after confirm failed receipt_id=%s", receipt_id)
    events.dispatch_receipt_confirmed(receipt=receipt)


def confirm_receipt(*, receipt_id: int, user) -> tuple[CashWithdrawalReceipt, bool]:
    with transaction.atomic():
        receipt = (
            CashWithdrawalReceipt.objects.select_for_update()
            .select_related("tenant", "request", "wallet")
            .get(pk=receipt_id)
        )
        if receipt.status != CashWithdrawalReceipt.Status.PENDING:
            return receipt, False
        request_obj = receipt.request
        now = timezone.now()
        revenue = CashRevenue.objects.create(
            tenant=receipt.tenant,
            wallet=receipt.wallet,
            total_sum=receipt.amount,
            currency=receipt.currency,
            revenue_at=now,
            confirmed=True,
            operation=f"Наличные с банка {request_obj.title or ''}".strip()[:255],
            comment=request_obj.description or "",
            external_id=f"cash-{request_obj.pk}",
            source_year=None,
            created_by=user,
            payload={"source": "cash_withdrawals", "receipt_id": receipt.pk, "request_id": request_obj.pk},
        )
        receipt.status = CashWithdrawalReceipt.Status.CONFIRMED
        receipt.confirmed_by = user
        receipt.confirmed_at = now
        receipt.cash_revenue = revenue
        receipt.save(update_fields=["status", "confirmed_by", "confirmed_at", "cash_revenue"])
        logger.info(
            "cash_withdrawals: receipt confirmed receipt_id=%s revenue_id=%s user_id=%s",
            receipt.pk, revenue.pk, user.pk,
        )
        confirmed_id = receipt.pk
        transaction.on_commit(lambda: _after_confirm(confirmed_id))
    return receipt, True


def _system_user():
    """pk=1 service account shown as «Система» (same convention as payroll/n8n_integration)."""
    return User.objects.filter(pk=1).first()


def close_receipt(*, receipt_id: int, actor, comment: str) -> bool:
    from apps.modules.requests.models import RequestComment

    comment = (comment or "").strip()
    if not comment:
        return False
    with transaction.atomic():
        receipt = CashWithdrawalReceipt.objects.select_for_update().select_related("request").get(pk=receipt_id)
        if receipt.status != CashWithdrawalReceipt.Status.PENDING:
            return False
        receipt.status = CashWithdrawalReceipt.Status.CLOSED
        receipt.closed_by = actor
        receipt.closed_at = timezone.now()
        receipt.closed_comment = comment
        receipt.save(update_fields=["status", "closed_by", "closed_at", "closed_comment"])
        RequestComment.objects.create(
            request=receipt.request,
            created_by=_system_user() or actor,
            body=f"Ожидание поступления наличных закрыто без дохода: {comment}",
        )
        logger.info("cash_withdrawals: receipt closed receipt_id=%s actor_id=%s", receipt.pk, getattr(actor, "pk", None))
        closed_id = receipt.pk
        transaction.on_commit(lambda: _refresh_cards_safely(closed_id))
    return True


def _refresh_cards_safely(receipt_id: int) -> None:
    receipt = (
        CashWithdrawalReceipt.objects.select_related("tenant", "request", "wallet", "wallet__cash_register")
        .filter(pk=receipt_id)
        .first()
    )
    if receipt is None:
        return
    try:
        messaging.refresh_receipt_cards(receipt)
    except Exception:
        logger.exception("cash_withdrawals: refresh after close failed receipt_id=%s", receipt_id)
