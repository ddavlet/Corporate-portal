"""One-time backfill: create CardExpense for PAYED corporate-card requests that have none.

Run with --dry-run first to preview, then without to apply.

Examples:
    python manage.py backfill_card_expenses --dry-run
    python manage.py backfill_card_expenses --dry-run --tenant=1
    python manage.py backfill_card_expenses
    python manage.py backfill_card_expenses --tenant=1
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from rest_framework.exceptions import ValidationError

from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.models import Request
from apps.modules.requests.services import create_expense_for_request_payment


class Command(BaseCommand):
    help = "Backfill missing CardExpenses for PAYED corporate-card requests (one-time)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without making any changes.",
        )
        parser.add_argument(
            "--tenant",
            type=int,
            help="Limit to a specific tenant ID.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        tenant_id: int | None = options.get("tenant")

        qs = Request.objects.filter(
            payment_type=Request.PAYMENT_TYPE_CARD,
            status=Request.STATUS_PAYED,
        ).select_related("tenant", "created_by", "vendor_ref")

        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)

        # Pre-filter: only requests where expense_ref_id is null, or the referenced
        # CardExpense no longer exists for that tenant.
        candidates = []
        for req in qs:
            if req.expense_ref_id is None:
                candidates.append(req)
            elif not CardExpense.objects.filter(
                tenant=req.tenant, id=req.expense_ref_id
            ).exists():
                candidates.append(req)

        self.stdout.write(f"Found {len(candidates)} request(s) missing a CardExpense.")

        if dry_run:
            for req in candidates:
                self.stdout.write(
                    f"  [dry-run] Would create CardExpense for request id={req.id} "
                    f"tenant={req.tenant_id} amount={req.amount} billing_date={req.billing_date}"
                )
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made."))
            return

        created = 0
        skipped = 0
        for req in candidates:
            try:
                create_expense_for_request_payment(
                    request_obj=req,
                    actor_user=req.created_by,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Created CardExpense for request id={req.id} "
                        f"tenant={req.tenant_id} -> expense_ref_id={req.expense_ref_id}"
                    )
                )
                created += 1
            except ValidationError as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"  Skipped request id={req.id} tenant={req.tenant_id}: {exc.detail}"
                    )
                )
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created: {created}, Skipped (errors): {skipped}."
            )
        )
