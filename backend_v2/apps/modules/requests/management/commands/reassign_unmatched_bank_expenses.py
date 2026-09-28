"""Move unmatched bank expenses from one tenant to another where their PAYED
request lives, and link them — same logic as the n8n endpoint
`bank/expenses/reassign-unmatched/` (see bank_expense_reassignment.py), but
runnable directly without the n8n token.

Typical case: a payment for a Lemonfit Havo request went out of Lemonfit
ONE's bank account, so the statement import recorded it under ONE.

Run without --apply first to preview, then with --apply to write. Each linked
request gets a comment from the "Система" user (pk=1).

Examples:
    python manage.py reassign_unmatched_bank_expenses --from lemonfit --to lemonhavo
    python manage.py reassign_unmatched_bank_expenses --from lemonfit --to lemonhavo --apply
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.modules.requests.bank_expense_reassignment import reassign_unmatched_bank_expenses
from apps.modules.requests.models import RequestComment
from apps.tenants.models import Tenant

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Move unmatched BankExpense rows from --from tenant to --to tenant when exactly one "
        "PAYED request there matches (doc_no + year + amount), and link them."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="from_subdomain", required=True, help="Source tenant subdomain.")
        parser.add_argument("--to", dest="to_subdomain", required=True, help="Target tenant subdomain.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        tenant = self._tenant(options["from_subdomain"])
        other_tenant = self._tenant(options["to_subdomain"])
        if tenant.id == other_tenant.id:
            raise CommandError("--from and --to must be different tenants.")

        system_user = User.objects.filter(pk=1).first()
        if system_user is None:
            raise CommandError("System user (pk=1) is missing.")

        reassigned = reassign_unmatched_bank_expenses(
            tenant=tenant, other_tenant=other_tenant, created_by=system_user, dry_run=not apply_changes
        )

        for item in reassigned:
            expense, req = item.expense, item.request
            self.stdout.write(
                f"  + BankExpense {expense.pk} (п/п №{expense.doc_no} от {expense.doc_date:%d.%m.%Y}, "
                f"{expense.debit_turnover}): {tenant.subdomain} -> {other_tenant.subdomain}, link Request {req.pk}"
            )
            if apply_changes:
                RequestComment.objects.create(
                    request=req,
                    created_by=system_user,
                    body=(
                        f"Заявка связана с банковским расходом {expense.pk} "
                        f"(п/п №{expense.doc_no} от {expense.doc_date:%d.%m.%Y}). "
                        f"Расход перенесён из {tenant.name} — платёж был проведён с её счёта."
                    ),
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Reassigned' if apply_changes else 'Would reassign'}: {len(reassigned)}"))
        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))

    def _tenant(self, subdomain: str) -> Tenant:
        tenant = Tenant.objects.filter(subdomain=subdomain, is_active=True).first()
        if tenant is None:
            raise CommandError(f"Unknown tenant: {subdomain}")
        return tenant
