"""Destination cash register and credited amount of a cash-register transfer request."""

from __future__ import annotations

from decimal import Decimal

from rest_framework.exceptions import ValidationError

from apps.modules.cash_desk.constants import TRANSFER_PURPOSE
from apps.modules.cash_desk.models import CashRegisterTransferTarget
from apps.modules.requests.models import Request
from apps.modules.requests.payment_type_families import canonical_payment_type
from apps.modules.wallets.models import Wallet

TWO_PLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(TWO_PLACES)


def save_transfer_target(*, request_obj, to_wallet_id: int, to_amount: Decimal | None, user) -> CashRegisterTransferTarget:
    """Validate and store the destination wallet and credited amount (idempotent per request)."""
    if request_obj.status != Request.STATUS_DRAFT:
        raise ValidationError({"detail": "Кассу-получателя можно менять только в черновике заявки."})
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
        defaults={"tenant_id": request_obj.tenant_id, "to_wallet": wallet, "to_amount": amount},
    )
    return target
