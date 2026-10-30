from datetime import date

from django.db.models import QuerySet
from django.db.models.functions import Trim

from apps.modules.bank_expenses.models import BankRevenue
from apps.modules.wallets.models import BankAccount


def report_bank_revenues(*, tenant, start: date) -> QuerySet[BankRevenue]:
    """Bank revenues that count towards P&L and cashflow.

    Only UZS revenues on controlled accounts, and never transfers from the tenant's own
    accounts (matched by account number only: the counterparty MFO is stored without the
    leading zero in legacy n8n rows). `BankRevenue.wallet` is non-nullable, so there is no
    wallet-less branch. Stored `account_no` is compared trimmed, via the DB `Trim`.
    """
    own_account_nos = {
        no.strip()
        for no in BankAccount.objects.filter(tenant=tenant).exclude(account_no="").values_list("account_no", flat=True)
        if no.strip()
    }
    qs = BankRevenue.objects.filter(
        tenant_id=tenant.id,
        doc_date__gte=start,
        wallet__currency="UZS",
        wallet__bank_account__account_type=BankAccount.AccountType.CONTROLLED,
    )
    if own_account_nos:
        qs = qs.annotate(_account_no_trimmed=Trim("account_no")).exclude(_account_no_trimmed__in=own_account_nos)
    return qs.order_by("doc_date", "id")
