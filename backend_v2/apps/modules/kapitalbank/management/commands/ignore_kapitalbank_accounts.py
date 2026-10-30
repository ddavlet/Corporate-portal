"""Mark PENDING Kapitalbank accounts of one tenant "do not track" with one reason (dry-run by default)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.kapitalbank.ignoring import ignore_pending
from apps.modules.kapitalbank.models import BankAccountLink
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        "Mark the tenant's PENDING bank accounts with the given numbers IGNORED with one reason. "
        "Linked and already ignored accounts are not changed. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant subdomain.")
        parser.add_argument(
            "--account",
            action="append",
            required=True,
            help="Bank account number; repeat or separate with commas for several.",
        )
        parser.add_argument("--reason", required=True, help="Why these accounts are not tracked.")
        parser.add_argument("--apply", action="store_true", help="Write the decision. Without it nothing is written.")

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
        reason = options["reason"].strip()
        if not reason:
            raise CommandError("--reason must not be empty.")
        apply = options["apply"]
        results = ignore_pending(tenant=tenant, account_nos=account_nos, reason=reason, apply=apply, now=timezone.now())

        self.stdout.write(f"Kapitalbank ignore{'' if apply else ' (dry-run)'}: tenant={tenant.subdomain} reason={reason}")
        self.stdout.write("account_no | branch | name | result")
        decisions = dict(BankAccountLink.DECISION_CHOICES)
        for r in results:
            if r.link is None:
                self.stdout.write(f"{r.account_no} | | | пропущен: {r.skip_reason}")
                continue
            prefix = f"{r.link.account_no} | {r.link.branch} | {r.link.name} | "
            if not r.matched:
                self.stdout.write(f"{prefix}пропущен: {r.skip_reason} ({decisions.get(r.link.decision, r.link.decision)})")
            elif not apply:
                self.stdout.write(f"{prefix}будет отмечен «Игнорируется»")
            elif r.ignored:
                self.stdout.write(f"{prefix}отмечен «Игнорируется»")
            else:
                self.stdout.write(f"{prefix}не изменён: решение уже принято в админке")

        matched = sum(1 for r in results if r.matched)
        skipped = len(results) - matched
        if apply:
            self.stdout.write(f"ignored={sum(1 for r in results if r.ignored)} skipped={skipped}")
        else:
            self.stdout.write(f"would_ignore={matched} skipped={skipped}")
            if matched:
                self.stdout.write("Run with --apply (make ignore-kapitalbank ... APPLY=1) to write the decision.")
