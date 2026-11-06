"""Incoming CashRevenue for a cash-register transfer (replaces the n8n "Перевод между кассами" step)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.modules.cash_desk.models import CashRegisterTransferTarget
from apps.modules.cashier.models import CashRevenue
from apps.modules.wallets.models import CashRegister, Wallet

logger = logging.getLogger(__name__)

TASHKENT_TZ = ZoneInfo("Asia/Tashkent")

_DEST_LINE_RE = re.compile(r"^В кассу:[ \t]*(.+?)[ \t]*(?:\(([A-Z]{3})\))?[ \t]*$", re.MULTILINE)
_TRAILING_SUFFIX_RE = re.compile(r"\s*\((?:касса|[A-Za-z]{3})\)\s*$", re.IGNORECASE)


class TransferDestinationError(Exception):
    """Destination register can't be determined; the (Russian) message goes to CashDeskMessage.revenue_error."""


@dataclass(frozen=True)
class TransferDestination:
    wallet: Wallet
    amount: Decimal
    currency: str


def _normalize(name: str) -> str:
    value = " ".join((name or "").split()).casefold()
    previous = None
    while previous != value:
        previous = value
        value = _TRAILING_SUFFIX_RE.sub("", value).strip()
    return value


def _register_wallet(register: CashRegister):
    try:
        return register.wallet
    except Wallet.DoesNotExist:
        return None


def _resolve_by_description(request_obj) -> TransferDestination:
    match = _DEST_LINE_RE.search(request_obj.description or "")
    if not match:
        raise TransferDestinationError("В описании нет строки «В кассу: …»")
    raw_name = match.group(1).strip()
    wanted = _normalize(raw_name)

    registers = CashRegister.objects.filter(tenant_id=request_obj.tenant_id).select_related("wallet")
    wallets = []
    for register in registers:
        if _normalize(register.name) != wanted:
            continue
        wallet = _register_wallet(register)
        if wallet is not None:
            wallets.append(wallet)

    if not wallets:
        raise TransferDestinationError(f"Не найдена касса-получатель «{raw_name}»")
    if len(wallets) > 1:
        narrowed = [w for w in wallets if w.pk != request_obj.wallet_ref_id]
        if len(narrowed) != 1:
            raise TransferDestinationError(f"Найдено несколько касс «{raw_name}»")
        wallets = narrowed

    wallet = wallets[0]
    if wallet.currency != request_obj.currency:
        raise TransferDestinationError(
            f"Валюта кассы «{raw_name}» ({wallet.currency}) не совпадает с валютой заявки ({request_obj.currency})"
        )
    return TransferDestination(wallet=wallet, amount=request_obj.amount, currency=wallet.currency)


def resolve_transfer_destination(request_obj) -> TransferDestination:
    target = (
        CashRegisterTransferTarget.objects.select_related("to_wallet").filter(request_id=request_obj.pk).first()
    )
    if target is not None:
        return TransferDestination(
            wallet=target.to_wallet, amount=target.to_amount, currency=target.to_wallet.currency
        )
    return _resolve_by_description(request_obj)


def ensure_transfer_revenue(*, request_obj, destination: TransferDestination) -> tuple[CashRevenue, bool]:
    external_id = f"cash-{request_obj.pk}"
    existing = CashRevenue.objects.filter(tenant=request_obj.tenant, external_id=external_id).first()
    if existing is not None:
        return existing, False
    now = timezone.now()
    revenue = CashRevenue.objects.create(
        tenant=request_obj.tenant,
        wallet=destination.wallet,
        total_sum=destination.amount,
        currency=destination.currency,
        revenue_at=now,
        confirmed=True,
        operation=f"Перевод между кассами {request_obj.title or ''}".strip()[:255],
        comment=request_obj.description or "",
        external_id=external_id,
        source_year=timezone.localtime(now, TASHKENT_TZ).year,
        created_by=get_user_model().objects.filter(pk=1).first(),
        payload={"source": "cash_desk_transfer", "request_id": request_obj.pk},
    )
    logger.info("cash_desk: transfer revenue created request_id=%s revenue_id=%s", request_obj.pk, revenue.pk)
    return revenue, True
