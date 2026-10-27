"""Bank account list refresh: every account visible under the bank login becomes a BankAccountLink.

Refresh never links an account: the owner decides in admin, or `link_kapitalbank_accounts` links
the unambiguous matches (autolink.py).
"""

from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.db.models import QuerySet

from apps.modules.kapitalbank.client import KapitalbankClient
from apps.modules.kapitalbank.models import BankAccountLink, KapitalbankConnection

# APILogin `val` is a numeric currency code; stored as letters so the API and admin show them.
CURRENCY_LETTERS = {"000": "UZS", "860": "UZS", "840": "USD", "978": "EUR", "643": "RUB"}


def currency_letters(code: str) -> str:
    """'000'/'860' -> 'UZS', '840' -> 'USD', '978' -> 'EUR', '643' -> 'RUB'; anything else stays raw."""
    return CURRENCY_LETTERS.get((code or "").strip(), code)


def refresh_account_list(
    connection: KapitalbankConnection, client: KapitalbankClient, *, now: datetime
) -> list[BankAccountLink]:
    """Upsert links by (tenant, account_no, branch).

    Existing links: only name, currency, last_balance, bank_state and last_seen_at are updated;
    the decision (decision, bank_account, card_account, decided_by, decided_at) is never touched.
    New links are PENDING. Accounts that vanished from the bank list are left as they are.
    """
    tenant = connection.tenant
    listed = client.list_accounts()
    links: list[BankAccountLink] = []
    with transaction.atomic():
        for acc in listed:
            fields = {
                "name": acc.name,
                "currency": currency_letters(acc.currency),
                "last_balance": acc.balance,
                "bank_state": acc.state_name,
            }
            link, created = BankAccountLink.objects.get_or_create(
                tenant=tenant,
                account_no=acc.account_no,
                branch=acc.branch,
                defaults={**fields, "decision": BankAccountLink.PENDING},
            )
            # auto_now / auto_now_add ignore passed values on save; set timestamps via update().
            timestamps = {"last_seen_at": now}
            if created:
                timestamps["first_seen_at"] = now
            else:
                timestamps.update(fields)
            BankAccountLink.objects.filter(pk=link.pk).update(**timestamps)
            link.refresh_from_db()
            links.append(link)
    return links


def pending_accounts(tenant) -> QuerySet[BankAccountLink]:
    return BankAccountLink.objects.filter(tenant=tenant, decision=BankAccountLink.PENDING).order_by(
        "first_seen_at", "id"
    )
