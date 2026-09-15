"""One-time: soft-delete (status=DELETED) two Lemonfit Aqua (tenant_id=3)
"Платежная карта" requests that could not be reconciled against the
imported CardExpense ledger after every other candidate was exhausted:

    Request 7940 (241 000 UZS, payed 2026-09-04) — the only two nearby
    transactions that could plausibly sum to this amount (CardExpense
    147 + 148 = 240 900, off by 100 UZS) were needed for their own
    exact-amount requests instead (see
    create_lemonaqua_missing_card_expense_requests), so no candidate
    is left.

    Request 7980 (528 000 UZS, payed 2026-09-07) — no subset of nearby
    CardExpense transactions ever summed to this amount within a
    plausible date range; the underlying card charge(s) were never
    imported.

This does NOT touch CardExpense or delete any row — `status=DELETED` is
the existing soft-delete convention (see draft_retention.py): the row
stays in the database but drops out of the default `Request.objects`
manager and out of PAYED-only financial reports (P&L, cashflow). This
was a deliberate, human-confirmed decision: these two requests represent
real card spending with no matching statement data, and removing them
from active reporting was chosen over leaving them permanently stuck as
"missing expense".

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py delete_lemonaqua_unmatched_card_requests
    python manage.py delete_lemonaqua_unmatched_card_requests --apply
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.modules.requests.models import Request, RequestComment

User = get_user_model()

LEMONAQUA_TENANT_ID = 3
REQUEST_IDS_AND_AMOUNTS = {
    7940: Decimal("241000.00"),
    7980: Decimal("528000.00"),
}


def _system_user():
    """pk=1 already displays as "Система" — same account
    apps.modules.n8n_integration.views._system_user() uses."""
    return User.objects.filter(pk=1).first()


class Command(BaseCommand):
    help = (
        "One-time: soft-delete (status=DELETED) requests 7940 and 7980 "
        "(tenant 3, Lemonfit Aqua) — unreconcilable corporate card charges."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        system_user = _system_user()

        deleted = 0
        already_correct = 0
        skipped: list[str] = []

        for request_id, expected_amount in REQUEST_IDS_AND_AMOUNTS.items():
            req = Request.all_objects.filter(pk=request_id, tenant_id=LEMONAQUA_TENANT_ID).first()
            if req is None:
                skipped.append(f"Request {request_id}: not found for tenant {LEMONAQUA_TENANT_ID}")
                continue

            if req.status == Request.STATUS_DELETED:
                already_correct += 1
                self.stdout.write(f"  = Request {request_id}: already DELETED")
                continue

            if not (req.status == Request.STATUS_PAYED and req.amount == expected_amount and req.expense_ref_id is None):
                skipped.append(
                    f"Request {request_id}: expected status=PAYED amount={expected_amount} expense_ref_id=None, "
                    f"found status={req.status} amount={req.amount} expense_ref_id={req.expense_ref_id} "
                    f"— skipped (unexpected state, resolve manually)"
                )
                continue

            deleted += 1
            self.stdout.write(f"  + Request {request_id}: status PAYED -> DELETED")
            if apply_changes:
                note = (
                    "[soft-delete: расход по корпоративной карте не удалось сопоставить с транзакцией "
                    "в импортированной выписке; заявка исключена из активных заявок и финансовой "
                    "отчётности (P&L/Cashflow) по решению администратора]"
                )
                Request.objects.filter(pk=request_id).update(
                    status=Request.STATUS_DELETED,
                    description=(f"{req.description}\n{note}" if req.description else note),
                )
                if system_user is not None:
                    RequestComment.objects.create(
                        request_id=request_id,
                        created_by=system_user,
                        body=(
                            "Заявка помечена как удалённая (DELETED): расход по корпоративной карте "
                            "не удалось сопоставить ни с одной транзакцией в импортированной выписке. "
                            "Исключена из активных заявок и P&L/Cashflow отчётов."
                        ),
                    )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Deleted' if apply_changes else 'Would delete'}: {deleted}"))
        self.stdout.write(f"Already correct: {already_correct}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
