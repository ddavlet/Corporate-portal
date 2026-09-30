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
            lambda: messaging.send_to_alert_recipients(config=config, text=text, request_id=request_obj.pk),
            robust=True,
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
            CashWithdrawalReceipt.objects.select_for_update(of=("self",))
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
        receipt = (
            CashWithdrawalReceipt.objects.select_for_update(of=("self",))
            .select_related("request")
            .get(pk=receipt_id)
        )
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


def _user_label(user) -> str:
    return (getattr(user, "full_name", "") or "").strip() or user.username


def config_payload(tenant) -> dict:
    from apps.modules.cash_withdrawals.formatter import wallet_label
    from apps.modules.requests.models import RequestFormConfig
    from apps.modules.telegram_approvals.models import TenantTelegramChat
    from apps.modules.wallets.models import Wallet

    config = CashWithdrawalConfig.objects.filter(tenant=tenant).first()
    rules = []
    if config is not None:
        rules = [
            {"payment_type": r.payment_type, "payment_purpose": r.payment_purpose, "wallet_id": r.wallet_id}
            for r in config.rules.order_by("id")
        ]
    member_ids = TenantMembership.objects.filter(tenant=tenant, is_active=True).values_list("user_id", flat=True)
    users = User.objects.filter(id__in=member_ids, is_active=True).order_by("full_name", "username")
    purposes: dict[str, list[str]] = {}
    form = RequestFormConfig.objects.filter(tenant=tenant).first()
    if form is not None:
        for pt in form.payment_types.filter(is_enabled=True).order_by("id"):
            names = list(pt.payment_purposes.filter(is_active=True).order_by("name").values_list("name", flat=True))
            purposes.setdefault(pt.payment_type, []).extend(names)
    for rule in rules:  # keep purposes already used in rules visible even if deactivated in the form
        bucket = purposes.setdefault(rule["payment_type"], [])
        if rule["payment_purpose"] not in bucket:
            bucket.append(rule["payment_purpose"])
    wallets = Wallet.objects.filter(tenant=tenant, wallet_type=Wallet.Type.CASH).select_related("cash_register").order_by("id")
    return {
        "is_active": bool(config and config.is_active),
        "card_telegram_chat_id": config.card_telegram_chat_id if config else None,
        "alert_telegram_chat_id": config.alert_telegram_chat_id if config else None,
        "alert_after_days": config.alert_after_days if config else 3,
        "alert_repeat_every_days": config.alert_repeat_every_days if config else 1,
        "alert_hour": config.alert_hour if config else 9,
        "confirmer_user_ids": sorted(config.confirmers.values_list("user_id", flat=True)) if config else [],
        "alert_recipient_user_ids": sorted(config.alert_recipients.values_list("user_id", flat=True)) if config else [],
        "rules": rules,
        "options": {
            "users": [
                {"id": u.id, "label": _user_label(u), "has_telegram": bool(u.telegram_chat_id)} for u in users
            ],
            "telegram_chats": [
                {"id": c.id, "name": c.name}
                for c in TenantTelegramChat.objects.filter(tenant=tenant, is_active=True).order_by("name")
            ],
            "wallets": [{"id": w.id, "label": wallet_label(w), "currency": w.currency} for w in wallets],
            "payment_purposes": [{"payment_type": k, "purposes": v} for k, v in purposes.items()],
        },
    }


def save_config(*, tenant, data: dict, actor) -> None:
    from apps.modules.cash_withdrawals.models import (
        CashWithdrawalAlertRecipient,
        CashWithdrawalConfirmer,
        CashWithdrawalRule,
    )

    with transaction.atomic():
        config, _ = CashWithdrawalConfig.objects.select_for_update().get_or_create(tenant=tenant)
        config.is_active = data["is_active"]
        config.card_telegram_chat_id = data.get("card_telegram_chat_id")
        config.alert_telegram_chat_id = data.get("alert_telegram_chat_id")
        config.alert_after_days = data["alert_after_days"]
        config.alert_repeat_every_days = data["alert_repeat_every_days"]
        config.alert_hour = data["alert_hour"]
        config.updated_by = actor
        config.save()
        # Settings rows (not business data): replacing the list is the edit itself.
        config.confirmers.exclude(user_id__in=data["confirmer_user_ids"]).delete()
        for user_id in data["confirmer_user_ids"]:
            CashWithdrawalConfirmer.objects.get_or_create(config=config, user_id=user_id)
        config.alert_recipients.exclude(user_id__in=data["alert_recipient_user_ids"]).delete()
        for user_id in data["alert_recipient_user_ids"]:
            CashWithdrawalAlertRecipient.objects.get_or_create(config=config, user_id=user_id)
        wanted = {(r["payment_type"], r["payment_purpose"]): r["wallet_id"] for r in data["rules"]}
        for rule in list(config.rules.all()):
            key = (rule.payment_type, rule.payment_purpose)
            if key not in wanted:
                rule.delete()
            elif rule.wallet_id != wanted[key]:
                rule.wallet_id = wanted.pop(key)
                rule.save(update_fields=["wallet"])
            else:
                wanted.pop(key)
        for (payment_type, payment_purpose), wallet_id in wanted.items():
            CashWithdrawalRule.objects.create(
                config=config, payment_type=payment_type, payment_purpose=payment_purpose, wallet_id=wallet_id
            )
