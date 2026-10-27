"""Link PENDING Kapitalbank accounts to the one portal account with the same number (dry-run by default)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.modules.kapitalbank.autolink import auto_link_pending
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        "Link PENDING bank accounts to a portal account of the same tenant with the same account_no and "
        "MFO (card: external_ref = account number). Only unambiguous matches are linked; the rest stays "
        "PENDING. Dry-run unless --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Tenant subdomain. Defaults to all tenants.")
        parser.add_argument("--apply", action="store_true", help="Write the links. Without it nothing is written.")

    def handle(self, *args, **options):
        tenant = None
        if options.get("tenant"):
            tenant = Tenant.objects.filter(subdomain=options["tenant"]).first()
            if tenant is None:
                raise CommandError(f"Unknown tenant subdomain: {options['tenant']}")
        apply = options["apply"]
        results = auto_link_pending(tenant=tenant, apply=apply, now=timezone.now())

        self.stdout.write(f"Kapitalbank auto-link{'' if apply else ' (dry-run)'}: pending={len(results)}")
        self.stdout.write("tenant | account_no | branch | name | result")
        for r in results:
            prefix = f"{r.link.tenant.subdomain} | {r.link.account_no} | {r.link.branch} | {r.link.name} | "
            if not r.matched:
                self.stdout.write(f"{prefix}остаётся «ожидает решения»: {r.skip_reason}")
                continue
            if r.bank_account is not None:
                target = f"банковский счёт портала #{r.bank_account.pk} «{r.bank_account.label}»"
            else:
                target = f"карточный счёт портала #{r.card_account.pk} «{r.card_account.label}»"
            if not apply:
                verb = "будет привязан к"
            elif r.linked:
                verb = "привязан к"
            else:
                verb = "не привязан (решение уже принято в админке), кандидат —"
            self.stdout.write(f"{prefix}{verb} {target}")

        matched = sum(1 for r in results if r.matched)
        if apply:
            self.stdout.write(f"linked={sum(1 for r in results if r.linked)} left_pending={len(results) - matched}")
        else:
            self.stdout.write(f"would_link={matched} left_pending={len(results) - matched}")
            if matched:
                self.stdout.write("Run with --apply (make link-kapitalbank APPLY=1) to write the links.")
