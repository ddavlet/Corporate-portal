"""Account kind of a Kapitalbank account, attaching a PENDING account to a portal account, account type changes.

- ``kind_for_account``: which kind a bank account is, by its balance-account prefix and currency;
- ``attach_bank`` / ``attach_card``: link a PENDING account to a portal bank / corporate card account
  (created when missing), tracked from ``today``;
- ``set_account_type``: change a portal bank account's type; every change alerts the owner;
- ``auto_attach_new``: the nightly run's handling of an account the bank listed for the first time;
- ``classify``: the ``classify_kapitalbank_accounts`` command (attach PENDING or change the type of LINKED).

Nothing here unlinks an account or deletes data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import NamedTuple

from django.db import transaction

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.kapitalbank import alerts
from apps.modules.kapitalbank.models import BankAccountLink
from apps.modules.wallets.models import BankAccount, CorporateCardAccount, Wallet
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account, normalized_currency

logger = logging.getLogger(__name__)

KIND_CONTROLLED = "controlled"
KIND_INFORMATIONAL = "informational"
KIND_SERVICE = "service"
KIND_CARD = "card"

BANK_ACCOUNT_TYPES = (KIND_CONTROLLED, KIND_INFORMATIONAL, KIND_SERVICE)

# Balance-account prefixes of the unified chart of accounts of Uzbekistan's banks (the first digits
# of a 20-digit account number are its balance account). Checked in this order, first match wins:
# 22620 — corporate card accounts; 16… (bank fees), 22613, 23106, 23510 (transit / settlement
# accounts of the bank) — service; 22614 — informational.
PREFIX_KINDS: tuple[tuple[str, str], ...] = (
    ("22620", KIND_CARD),
    ("16", KIND_SERVICE),
    ("22613", KIND_SERVICE),
    ("23106", KIND_SERVICE),
    ("23510", KIND_SERVICE),
    ("22614", KIND_INFORMATIONAL),
)
# 202… are current accounts: in UZS they are controlled, in a foreign currency informational.
CURRENT_ACCOUNT_PREFIX = "202"
HOME_CURRENCY = "UZS"

NOT_FOUND = "нет такого счёта у тенанта (обновите список: make import-kapitalbank REFRESH_ACCOUNTS=1)"
NOT_PENDING = "решение уже принято"
EMPTY_NUMBER = "у счёта банка нет номера"
LINKED_ELSEWHERE = "счёт портала уже привязан к другому счёту банка"
HAS_MOVEMENTS = "У счёта портала уже есть движения — привяжите его вручную в админке"
CARD_ACCOUNT = "счёт корпоративной карты — привязывается в «Корпоративные карты», не как банковский"
OTHER_CURRENCY = "кошелёк счёта портала в другой валюте — привяжите его вручную в админке"
USE_IGNORE = "служебный счёт «ожидает решения» — используйте make ignore-kapitalbank"
CARD_LINKED = "счёт привязан к корпоративной карте, тип не меняется"
IGNORED = "счёт отмечен «Служебный»"
SAME_TYPE = "тип уже такой"
BAD_TYPE = "неизвестный тип счёта"
SERVICE_IGNORE_REASON = "Служебный счёт банка (определён автоматически)"

ACTION_ATTACH = "attach"
ACTION_SET_TYPE = "set_type"
ACTION_SKIP = "skip"


class ClassificationError(Exception):
    """The account cannot be attached / changed; the message is shown to the owner (Russian)."""


def kind_for_account(account_no: str, currency: str) -> str:
    """Kind of a bank account by its number and letter currency (``BankAccountLink.currency``; empty = UZS)."""
    account_no = (account_no or "").strip()
    for prefix, kind in PREFIX_KINDS:
        if account_no.startswith(prefix):
            return kind
    if account_no.startswith(CURRENT_ACCOUNT_PREFIX) and normalized_currency(currency).upper() != HOME_CURRENCY:
        return KIND_INFORMATIONAL
    return KIND_CONTROLLED


def _type_label(value: str) -> str:
    return dict(BankAccount.AccountType.choices).get(value, value)


def _lock_pending(link: BankAccountLink) -> BankAccountLink:
    locked = BankAccountLink.objects.select_for_update(of=("self",)).select_related("tenant").get(pk=link.pk)
    if locked.decision != BankAccountLink.PENDING:
        raise ClassificationError(NOT_PENDING)
    if not locked.account_no.strip():
        raise ClassificationError(EMPTY_NUMBER)
    return locked


def bank_attach_problem(link: BankAccountLink) -> str:
    """Why ``attach_bank`` would refuse this link ("" when it would not). Used by the dry-run too."""
    if link.decision != BankAccountLink.PENDING:
        return NOT_PENDING
    account_no, branch = link.account_no.strip(), link.branch.strip()
    if not account_no:
        return EMPTY_NUMBER
    if kind_for_account(account_no, link.currency) == KIND_CARD:
        # A corporate card account is attached only as a corporate card (attach_card), never as a bank account.
        return CARD_ACCOUNT
    existing = BankAccount.objects.filter(tenant_id=link.tenant_id, account_no=account_no, mfo=branch).first()
    if existing is None:
        return ""
    if BankAccountLink.objects.filter(bank_account=existing).exclude(pk=link.pk).exists():
        return LINKED_ELSEWHERE
    wallet = Wallet.objects.filter(bank_account=existing).first()
    if wallet is not None:
        # Rows already in this wallet predate track_from and would be counted twice in the balance.
        if BankExpense.objects.filter(wallet=wallet).exists() or BankRevenue.objects.filter(wallet=wallet).exists():
            return HAS_MOVEMENTS
        if wallet.currency != normalized_currency(link.currency):
            return OTHER_CURRENCY
    return ""


def attach_bank(link: BankAccountLink, *, account_type: str, today: date, now: datetime, user=None) -> Wallet:
    """Link a PENDING account to the portal bank account (account_no, mfo=branch), creating it and its
    wallet in the bank's currency when missing; the account gets ``account_type``. Raises
    ClassificationError when the link is not PENDING or the portal account cannot be reused."""
    if account_type not in (KIND_CONTROLLED, KIND_INFORMATIONAL, KIND_SERVICE):
        raise ClassificationError(BAD_TYPE)
    with transaction.atomic():
        locked = _lock_pending(link)
        problem = bank_attach_problem(locked)
        if problem:
            raise ClassificationError(problem)
        wallet = get_or_create_bank_wallet_for_account(
            tenant=locked.tenant,
            account_no=locked.account_no,
            mfo=locked.branch,
            currency=locked.currency,
            account_type=account_type,
        )
        bank_account = wallet.bank_account
        _write_linked(link, bank_account=bank_account, card_account=None, today=today, now=now, user=user)
        set_account_type(bank_account, account_type, changed_by=user, now=now)
    logger.info(
        "kapitalbank attach: tenant=%s account=%s/%s -> bank_account=%s type=%s",
        link.tenant_id, link.account_no, link.branch, bank_account.pk, account_type,
    )
    return wallet


def attach_card(link: BankAccountLink, *, today: date, now: datetime, user=None) -> Wallet:
    """Link a PENDING account to the corporate card account whose external_ref is the account number,
    creating it (and its CORPORATE_CARD wallet) in the bank's currency when missing."""
    with transaction.atomic():
        locked = _lock_pending(link)
        account_no = locked.account_no.strip()
        card = (
            CorporateCardAccount.objects.filter(tenant_id=locked.tenant_id, external_ref=account_no)
            .order_by("id")
            .first()
        )
        if card is None:
            card = CorporateCardAccount.objects.create(
                tenant=locked.tenant,
                currency=normalized_currency(locked.currency),
                label=locked.name or account_no,
                external_ref=account_no,
            )
        wallet, _ = Wallet.objects.get_or_create(
            corporate_card_account=card,
            defaults={
                "tenant": locked.tenant,
                "wallet_type": Wallet.Type.CORPORATE_CARD,
                "currency": card.currency,
                "opening_balance": 0,
            },
        )
        _write_linked(link, bank_account=None, card_account=card, today=today, now=now, user=user)
    logger.info(
        "kapitalbank attach: tenant=%s account=%s/%s -> card_account=%s",
        link.tenant_id, link.account_no, link.branch, card.pk,
    )
    return wallet


def _write_linked(link, *, bank_account, card_account, today, now, user) -> None:
    fields = {
        "decision": BankAccountLink.LINKED,
        "bank_account": bank_account,
        "card_account": card_account,
        "ignore_reason": "",
        "track_from": today,
        "opening_synced_at": None,
        "decided_by": user,
        "decided_at": now,
    }
    BankAccountLink.objects.filter(pk=link.pk).update(**fields)
    for name, value in fields.items():
        setattr(link, name, value)


class AutoAttachResult(NamedTuple):
    kind: str
    problem: str = ""  # why the account stays PENDING ("" when it was attached / ignored)


def auto_attach_new(link: BankAccountLink, *, today: date, now: datetime) -> AutoAttachResult:
    """A PENDING account the bank listed for the first time, by its kind: a card account is attached
    to a corporate card, a service one is marked IGNORED, any other is attached as a bank account of
    that kind (tracked from ``today``). When it cannot be attached it stays PENDING and ``problem``
    says why (the owner attaches it in admin)."""
    kind = kind_for_account(link.account_no, link.currency)
    try:
        if kind == KIND_CARD:
            attach_card(link, today=today, now=now)
        elif kind == KIND_SERVICE:
            _ignore_service(link, now=now)
        else:
            attach_bank(link, account_type=kind, today=today, now=now)
    except ClassificationError as exc:
        logger.warning(
            "kapitalbank new account: tenant=%s account=%s/%s left pending: %s",
            link.tenant_id, link.account_no, link.branch, exc,
        )
        return AutoAttachResult(kind, str(exc))
    return AutoAttachResult(kind)


def _ignore_service(link: BankAccountLink, *, now: datetime) -> None:
    fields = {
        "decision": BankAccountLink.IGNORED,
        "ignore_reason": SERVICE_IGNORE_REASON,
        "decided_by": None,
        "decided_at": now,
    }
    if not BankAccountLink.objects.filter(pk=link.pk, decision=BankAccountLink.PENDING).update(**fields):
        raise ClassificationError(NOT_PENDING)
    for name, value in fields.items():
        setattr(link, name, value)
    logger.info("kapitalbank ignore: tenant=%s account=%s/%s (service)", link.tenant_id, link.account_no, link.branch)


def set_account_type(bank_account: BankAccount, new_type: str, *, changed_by=None, now: datetime) -> bool:
    """Set the portal bank account's type; False when it already has it. Every change alerts the owner."""
    if new_type not in (KIND_CONTROLLED, KIND_INFORMATIONAL, KIND_SERVICE):
        raise ClassificationError(BAD_TYPE)
    with transaction.atomic():
        current = BankAccount.objects.select_for_update().get(pk=bank_account.pk)
        old = current.account_type
        if old == new_type:
            bank_account.account_type = old
            return False
        BankAccount.objects.filter(pk=bank_account.pk).update(account_type=new_type)
        bank_account.account_type = new_type
    logger.info("kapitalbank account type: bank_account=%s %s -> %s", bank_account.pk, old, new_type)
    alerts.notify_account_type_changed(bank_account, old=old, new=new_type, changed_by=changed_by, now=now)
    return True


@dataclass
class ClassifyResult:
    account_no: str
    link: BankAccountLink | None
    action: str
    skip_reason: str = ""
    done: bool = False

    @property
    def matched(self) -> bool:
        return not self.skip_reason


def _plan(link: BankAccountLink, account_type: str) -> ClassifyResult:
    result = ClassifyResult(account_no=link.account_no, link=link, action=ACTION_SKIP)
    if link.decision == BankAccountLink.PENDING:
        if account_type == KIND_SERVICE:
            result.skip_reason = USE_IGNORE
        else:
            result.action = ACTION_ATTACH
            result.skip_reason = bank_attach_problem(link)
    elif link.decision == BankAccountLink.LINKED and link.bank_account_id is not None:
        result.action = ACTION_SET_TYPE
        if link.bank_account.account_type == account_type:
            result.skip_reason = SAME_TYPE
    elif link.decision == BankAccountLink.LINKED:
        result.skip_reason = CARD_LINKED
    else:
        result.skip_reason = IGNORED
    return result


def classify(
    *, tenant, account_nos: list[str], account_type: str, apply: bool, today: date, now: datetime
) -> list[ClassifyResult]:
    """Plan (and with ``apply`` do) for the tenant's accounts with these numbers: attach PENDING ones as
    a bank account of ``account_type`` (controlled / informational), or set ``account_type`` on the
    portal account of LINKED bank ones. One result per link found, one per number not found.
    The dry run writes nothing and sends no alerts."""
    if account_type not in BANK_ACCOUNT_TYPES:
        raise ValueError(f"unknown account type: {account_type}")
    wanted = list(dict.fromkeys(a.strip() for a in account_nos if a.strip()))
    with transaction.atomic():
        links = BankAccountLink.objects.filter(tenant=tenant, account_no__in=wanted).select_related(
            "tenant", "bank_account"
        )
        if apply:
            links = links.select_for_update(of=("self",))
        by_no: dict[str, list[BankAccountLink]] = {}
        for link in links.order_by("account_no", "branch"):
            by_no.setdefault(link.account_no, []).append(link)

        results: list[ClassifyResult] = []
        for account_no in wanted:
            found = by_no.get(account_no)
            if not found:
                results.append(
                    ClassifyResult(account_no=account_no, link=None, action=ACTION_SKIP, skip_reason=NOT_FOUND)
                )
                continue
            results.extend(_plan(link, account_type) for link in found)

        if apply:
            for result in results:
                if not result.matched:
                    continue
                try:
                    with transaction.atomic():
                        if result.action == ACTION_ATTACH:
                            attach_bank(result.link, account_type=account_type, today=today, now=now)
                            result.done = True
                        else:
                            result.done = set_account_type(result.link.bank_account, account_type, now=now)
                except ClassificationError as exc:
                    result.skip_reason = str(exc)
    return results
