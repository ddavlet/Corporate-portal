"""Set the type of Kapitalbank accounts of one tenant: attach PENDING ones as a portal bank account of
that type, or change the type of LINKED bank ones (dry-run by default)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.kapitalbank.classification import (
    ACTION_ATTACH,
    ACTION_SET_TYPE,
    BANK_ACCOUNT_TYPES,
    classify,
)
from apps.modules.kapitalbank.models import BankAccountLink
from apps.modules.wallets.models import BankAccount
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        "For the tenant's bank accounts with the given numbers: attach PENDING ones to a portal bank "
        "account of --type (created in the bank's currency, tracked from today), or set --type on the "
        "portal account of LINKED ones. Service PENDING accounts go through ignore_kapitalbank_accounts. "
        "Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant subdomain.")
        parser.add_argument(
            "--account",
            action="append",
            required=True,
            help="Bank account number; repeat or separate with commas for several.",
        )
        parser.add_argument("--type", required=True, help=f"Account type: {', '.join(BANK_ACCOUNT_TYPES)}.")
        parser.add_argument("--apply", action="store_true", help="Write the changes. Without it nothing is written.")

    def handle(self, *args, **options):
        tenant = Tenant.objects.filter(subdomain=options["tenant"]).first()
        if tenant is None:
            raise CommandError(f"Unknown tenant subdomain: {options['tenant']}")
        account_nos = [a.strip() for raw in options["account"] for a in raw.split(",") if a.strip()]
        if not account_nos:
            raise CommandError("Give at least one --account.")
        bad = [a for a in account_nos if not a.isdigit()]
        if bad:
            raise CommandError(f"Account numbers must be digits only: {', '.join(bad)}")
        account_type = (options["type"] or "").strip()
        if account_type not in BANK_ACCOUNT_TYPES:
            raise CommandError(f"--type must be one of: {', '.join(BANK_ACCOUNT_TYPES)}")
        apply = options["apply"]
        now = timezone.now()
        today = timezone.localtime(now).date()  # the same local day as the import run's "today"
        results = classify(
            tenant=tenant, account_nos=account_nos, account_type=account_type, apply=apply, today=today, now=now
        )

        types = dict(BankAccount.AccountType.choices)
        label = types[account_type]
        self.stdout.write(
            f"Kapitalbank classify{'' if apply else ' (dry-run)'}: tenant={tenant.subdomain} type={account_type}"
        )
        self.stdout.write("account_no | branch | name | currency | result")
        decisions = dict(BankAccountLink.DECISION_CHOICES)
        for r in results:
            if r.link is None:
                self.stdout.write(f"{r.account_no} | | | | пропущен: {r.skip_reason}")
                continue
            prefix = f"{r.link.account_no} | {r.link.branch} | {r.link.name} | {r.link.currency} | "
            if not r.matched:
                self.stdout.write(f"{prefix}пропущен: {r.skip_reason} ({decisions.get(r.link.decision, r.link.decision)})")
            elif r.action == ACTION_ATTACH:
                if not apply:
                    self.stdout.write(f"{prefix}будет привязан, тип «{label}», отслеживание с {today:%d.%m.%Y}")
                elif r.done:
                    self.stdout.write(f"{prefix}привязан, тип «{label}», отслеживание с {today:%d.%m.%Y}")
                else:
                    self.stdout.write(f"{prefix}не изменён")
            elif r.action == ACTION_SET_TYPE:
                old = types.get(r.link.bank_account.account_type, r.link.bank_account.account_type)
                if not apply:
                    self.stdout.write(f"{prefix}тип будет изменён: «{old}» → «{label}»")
                elif r.done:
                    self.stdout.write(f"{prefix}тип изменён на «{label}»")
                else:
                    self.stdout.write(f"{prefix}не изменён: тип уже «{label}»")

        matched = [r for r in results if r.matched]
        skipped = len(results) - len(matched)
        attach = [r for r in matched if r.action == ACTION_ATTACH]
        set_type = [r for r in matched if r.action == ACTION_SET_TYPE]
        if apply:
            self.stdout.write(
                f"attached={sum(1 for r in attach if r.done)} "
                f"type_changed={sum(1 for r in set_type if r.done)} skipped={skipped}"
            )
        else:
            self.stdout.write(f"would_attach={len(attach)} would_set_type={len(set_type)} skipped={skipped}")
            if matched:
                self.stdout.write("Run with --apply (make classify-kapitalbank ... APPLY=1) to write the changes.")
