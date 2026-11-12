"""Destination cash register and credited amount of a cash-register transfer request."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.modules.cash_desk.constants import TRANSFER_PURPOSE
from apps.modules.cash_desk.models import CashRegisterTransferTarget
from apps.modules.cash_desk.transfer_revenue import (
    TransferDestinationError,
    description_credit_amount,
    description_wallet,
)
from apps.modules.requests.models import Request
from apps.modules.requests.payment_type_families import canonical_payment_type
from apps.modules.wallets.models import Wallet

TWO_PLACES = Decimal("0.01")
CLOSED_STATUSES = frozenset({Request.STATUS_PAYED, Request.STATUS_REJECTED, Request.STATUS_DELETED})


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(TWO_PLACES)


def save_transfer_target(*, request_obj, to_wallet_id: int, to_amount: Decimal | None, user) -> CashRegisterTransferTarget:
    """Validate and store the destination wallet and credited amount.

    Creating a request with configured approval steps moves it out of DRAFT at once, before the
    transfer form can send the destination. So after DRAFT the first destination is still accepted
    until the request is paid, but only if it matches the description approvers saw; once set, it
    can't be changed.
    """
    with transaction.atomic():
        # Lock the row: the payed handler reads the target right after the status becomes PAYED.
        locked = Request.all_objects.select_for_update().get(pk=request_obj.pk)
        if locked.status in CLOSED_STATUSES:
            raise ValidationError({"detail": "Заявка уже оплачена или закрыта — кассу-получателя изменить нельзя."})
        if locked.status != Request.STATUS_DRAFT:
            existing = CashRegisterTransferTarget.objects.filter(request_id=locked.pk).first()
            if existing is not None:
                same = existing.to_wallet_id == to_wallet_id and (
                    to_amount is None or _q(to_amount) == _q(existing.to_amount)
                )
                if same:  # repeated PUT (e.g. lost response): idempotent
                    return existing
                raise ValidationError(
                    {"detail": "Кассу-получателя нельзя изменить после отправки заявки на согласование."}
                )
            _ensure_matches_description(request_obj=locked, to_wallet_id=to_wallet_id, to_amount=to_amount)
        return _save_target(request_obj=locked, to_wallet_id=to_wallet_id, to_amount=to_amount)


MISMATCH_ERROR = "Касса-получатель и сумма зачисления должны совпадать с описанием заявки, которое видели согласующие."


def _ensure_matches_description(*, request_obj, to_wallet_id: int, to_amount: Decimal | None) -> None:
    """After DRAFT the target may only confirm what the description already says, never redirect the money."""
    try:
        wallet = description_wallet(request_obj)
    except TransferDestinationError as exc:
        raise ValidationError({"detail": MISMATCH_ERROR}) from exc
    if wallet.pk != to_wallet_id:
        raise ValidationError({"detail": MISMATCH_ERROR})
    if wallet.currency != request_obj.currency:
        credited = description_credit_amount(request_obj, wallet.currency)
        if credited is None or to_amount is None or _q(to_amount) != _q(credited):
            raise ValidationError({"detail": MISMATCH_ERROR})


def _save_target(*, request_obj, to_wallet_id: int, to_amount: Decimal | None) -> CashRegisterTransferTarget:
    if (
        request_obj.payment_purpose != TRANSFER_PURPOSE
        or canonical_payment_type(request_obj.payment_type) != Request.PAYMENT_TYPE_CASH
    ):
        raise ValidationError({"detail": "Заявка не является наличным переводом между кассами."})

    wallet = (
        Wallet.objects.filter(pk=to_wallet_id, tenant_id=request_obj.tenant_id, wallet_type=Wallet.Type.CASH)
        .select_related("cash_register")
        .first()
    )
    if wallet is None:
        raise ValidationError({"detail": "Касса-получатель не найдена."})
    if request_obj.wallet_ref_id and wallet.id == request_obj.wallet_ref_id:
        raise ValidationError({"detail": "Касса-получатель совпадает с кассой-источником."})

    request_amount = _q(request_obj.amount)
    if wallet.currency == request_obj.currency:
        if to_amount is None:
            amount = request_amount
        else:
            amount = _q(to_amount)
            if amount != request_amount:
                raise ValidationError({"detail": "При одинаковой валюте сумма зачисления должна равняться сумме заявки."})
    else:
        if to_amount is None or _q(to_amount) <= 0:
            raise ValidationError({"detail": "Для кассы в другой валюте укажите сумму зачисления."})
        amount = _q(to_amount)

    target, _ = CashRegisterTransferTarget.objects.update_or_create(
        request=request_obj,
        defaults={
            "tenant_id": request_obj.tenant_id,
            "to_wallet": wallet,
            "to_amount": amount,
            "source_amount": request_amount,
            "source_currency": request_obj.currency,
        },
    )
    return target
