"""Auto-link of PENDING bank accounts whose portal account is unambiguous.

A PENDING link is linked only when exactly one portal account of the same tenant matches it,
by the same rule the admin form checks:
- bank account: account_no and mfo equal the bank's account number and branch (МФО);
- corporate card account: external_ref equals the bank's account number.
Everything else (no match, several matches, a portal account without a wallet or already linked
to another bank account) stays PENDING for the owner to decide in admin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from apps.modules.kapitalbank.models import BankAccountLink
from apps.modules.wallets.models import BankAccount, CorporateCardAccount, Wallet

logger = logging.getLogger(__name__)

NO_MATCH = "нет счёта портала с этим номером и МФО (у карты — с этим внешним номером)"
SEVERAL_MATCHES = "подходят несколько счетов портала"
NO_WALLET = "у счёта портала нет кошелька"
ALREADY_LINKED = "счёт портала уже привязан к другому счёту банка"
SHARED_MATCH = "этот же счёт портала подходит другому счёту банка"


@dataclass
class AutoLinkResult:
    link: BankAccountLink
    bank_account: BankAccount | None = None
    card_account: CorporateCardAccount | None = None
    skip_reason: str = ""
    linked: bool = False

    @property
    def matched(self) -> bool:
        return not self.skip_reason


def _candidates(link: BankAccountLink, banks: list[BankAccount], cards: list[CorporateCardAccount]):
    account_no, branch = link.account_no.strip(), link.branch.strip()
    if not account_no:
        # An empty number would match the default portal account ("", "") or a card without external_ref.
        return [], []
    matched_banks = [b for b in banks if b.account_no.strip() == account_no and b.mfo.strip() == branch]
    matched_cards = [c for c in cards if c.external_ref.strip() == account_no]
    return matched_banks, matched_cards


def auto_link_pending(*, tenant=None, apply: bool = False, now: datetime) -> list[AutoLinkResult]:
    """Plan (and with ``apply`` write) links for PENDING accounts; ``tenant=None`` means all tenants.

    Only PENDING rows are ever written; LINKED and IGNORED links are not read or changed.
    """
    with transaction.atomic():
        pending = BankAccountLink.objects.filter(decision=BankAccountLink.PENDING).select_related("tenant")
        if tenant is not None:
            pending = pending.filter(tenant=tenant)
        if apply:
            pending = pending.select_for_update(of=("self",))
        pending = list(pending.order_by("tenant_id", "account_no", "branch"))

        tenant_ids = {link.tenant_id for link in pending}
        banks: dict[int, list[BankAccount]] = {}
        for bank in BankAccount.objects.filter(tenant_id__in=tenant_ids):
            banks.setdefault(bank.tenant_id, []).append(bank)
        cards: dict[int, list[CorporateCardAccount]] = {}
        for card in CorporateCardAccount.objects.filter(tenant_id__in=tenant_ids):
            cards.setdefault(card.tenant_id, []).append(card)
        bank_ids_with_wallet = set(
            Wallet.objects.filter(bank_account__tenant_id__in=tenant_ids).values_list("bank_account_id", flat=True)
        )
        card_ids_with_wallet = set(
            Wallet.objects.filter(corporate_card_account__tenant_id__in=tenant_ids).values_list(
                "corporate_card_account_id", flat=True
            )
        )
        linked = BankAccountLink.objects.filter(decision=BankAccountLink.LINKED)
        linked_bank_ids = set(linked.exclude(bank_account=None).values_list("bank_account_id", flat=True))
        linked_card_ids = set(linked.exclude(card_account=None).values_list("card_account_id", flat=True))

        results: list[AutoLinkResult] = []
        for link in pending:
            matched_banks, matched_cards = _candidates(link, banks.get(link.tenant_id, []), cards.get(link.tenant_id, []))
            result = AutoLinkResult(link=link)
            if not matched_banks and not matched_cards:
                result.skip_reason = NO_MATCH
            elif len(matched_banks) + len(matched_cards) > 1:
                result.skip_reason = SEVERAL_MATCHES
            elif matched_banks:
                result.bank_account = matched_banks[0]
                if result.bank_account.pk not in bank_ids_with_wallet:
                    result.skip_reason = NO_WALLET
                elif result.bank_account.pk in linked_bank_ids:
                    result.skip_reason = ALREADY_LINKED
            else:
                result.card_account = matched_cards[0]
                if result.card_account.pk not in card_ids_with_wallet:
                    result.skip_reason = NO_WALLET
                elif result.card_account.pk in linked_card_ids:
                    result.skip_reason = ALREADY_LINKED
            results.append(result)

        # Two bank accounts matching one portal account (a card is matched by number only, so two
        # branches of one number would): neither is linked, the owner decides.
        uses: dict[tuple[str, int], list[AutoLinkResult]] = {}
        for result in results:
            if result.matched:
                key = ("bank", result.bank_account.pk) if result.bank_account else ("card", result.card_account.pk)
                uses.setdefault(key, []).append(result)
        for shared in uses.values():
            if len(shared) > 1:
                for result in shared:
                    result.skip_reason = SHARED_MATCH

        if apply:
            for result in results:
                if not result.matched:
                    continue
                updated = BankAccountLink.objects.filter(
                    pk=result.link.pk, decision=BankAccountLink.PENDING
                ).update(
                    decision=BankAccountLink.LINKED,
                    bank_account=result.bank_account,
                    card_account=result.card_account,
                    decided_by=None,
                    decided_at=now,
                )
                result.linked = bool(updated)
                if result.linked:
                    target = (
                        f"bank_account={result.bank_account.pk}"
                        if result.bank_account
                        else f"card_account={result.card_account.pk}"
                    )
                    logger.info(
                        "kapitalbank auto-link: tenant=%s account=%s/%s -> %s",
                        result.link.tenant_id,
                        result.link.account_no,
                        result.link.branch,
                        target,
                    )
    return results
