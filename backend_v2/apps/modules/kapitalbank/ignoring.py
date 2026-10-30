"""Bulk "do not track" of PENDING bank accounts of one tenant, by account number, with one reason.

Only PENDING links are written. A LINKED account is never unlinked here (that stays a per-account
decision in admin), and an IGNORED one keeps its own reason.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from apps.modules.kapitalbank.models import BankAccountLink

logger = logging.getLogger(__name__)

NOT_FOUND = "нет такого счёта у тенанта (обновите список: make import-kapitalbank REFRESH_ACCOUNTS=1)"
ALREADY_DECIDED = "решение уже принято"


@dataclass
class IgnoreResult:
    account_no: str
    link: BankAccountLink | None = None
    skip_reason: str = ""
    ignored: bool = False

    @property
    def matched(self) -> bool:
        return not self.skip_reason


def ignore_pending(
    *, tenant, account_nos: list[str], reason: str, apply: bool = False, now: datetime
) -> list[IgnoreResult]:
    """Plan (and with ``apply`` write) IGNORED with ``reason`` for the tenant's PENDING links whose
    account_no is in ``account_nos``. One result per link found, one per number not found."""
    reason = reason.strip()
    if not reason:
        raise ValueError("reason is required")
    wanted = list(dict.fromkeys(a.strip() for a in account_nos if a.strip()))
    with transaction.atomic():
        links = BankAccountLink.objects.filter(tenant=tenant, account_no__in=wanted).select_related("tenant")
        if apply:
            links = links.select_for_update(of=("self",))
        by_no: dict[str, list[BankAccountLink]] = {}
        for link in links.order_by("account_no", "branch"):
            by_no.setdefault(link.account_no, []).append(link)

        results: list[IgnoreResult] = []
        for account_no in wanted:
            found = by_no.get(account_no)
            if not found:
                results.append(IgnoreResult(account_no=account_no, skip_reason=NOT_FOUND))
                continue
            for link in found:
                result = IgnoreResult(account_no=account_no, link=link)
                if link.decision != BankAccountLink.PENDING:
                    result.skip_reason = ALREADY_DECIDED
                results.append(result)

        if apply:
            for result in results:
                if not result.matched:
                    continue
                updated = BankAccountLink.objects.filter(
                    pk=result.link.pk, decision=BankAccountLink.PENDING
                ).update(decision=BankAccountLink.IGNORED, ignore_reason=reason, decided_by=None, decided_at=now)
                result.ignored = bool(updated)
                if result.ignored:
                    logger.info(
                        "kapitalbank ignore: tenant=%s account=%s/%s",
                        result.link.tenant_id,
                        result.link.account_no,
                        result.link.branch,
                    )
    return results
