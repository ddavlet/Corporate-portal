"""One-time: create a "Платежная карта" Request for each Lemonfit Aqua
(tenant_id=3) CardExpense from August 2026 onward that has no request
pointing at it yet (via `expense_ref_id`/`expense_ref_target='card'`).

These are real corporate-card charges (FITLINE Fitness Center Group,
UZCARD DUO) that cleared the card but were never filed as a request —
neither directly nor as part of another request's amount. Unlike every
other one-off command in this module, this one *creates* new `Request`
rows rather than only repointing/correcting existing ones; it never reads
or writes `CardExpense` beyond looking up the id/amount/date/title used to
build each new request.

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py create_lemonaqua_missing_card_expense_requests
    python manage.py create_lemonaqua_missing_card_expense_requests --apply
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.models import Request

LEMONAQUA_TENANT_ID = 3
IMPORT_USERNAME = "app"
CARD_VENDOR_SUFFIX = " UZCARD DUO"
CATEGORY = "Содержание клуба"
PAYMENT_PURPOSE = "Прочие расходы"


@dataclass(frozen=True)
class ExpenseSpec:
    expense_id: int
    amount: Decimal
    expense_date: date


EXPENSES: list[ExpenseSpec] = [
    ExpenseSpec(125, Decimal("14000.00"), date(2026, 8, 11)),
    ExpenseSpec(124, Decimal("80000.00"), date(2026, 8, 11)),
    ExpenseSpec(150, Decimal("90000.00"), date(2026, 9, 3)),
    ExpenseSpec(148, Decimal("129900.00"), date(2026, 9, 3)),
    ExpenseSpec(149, Decimal("118000.00"), date(2026, 9, 3)),
    ExpenseSpec(147, Decimal("111000.00"), date(2026, 9, 3)),
    ExpenseSpec(156, Decimal("128000.00"), date(2026, 9, 6)),
]


def _vendor_from_title(title: str) -> str:
    title = title.strip()
    if title.endswith(CARD_VENDOR_SUFFIX):
        return title[: -len(CARD_VENDOR_SUFFIX)].strip()
    return title


class Command(BaseCommand):
    help = (
        "One-time: create a Request for each of 7 Lemonfit Aqua (tenant 3) CardExpense "
        "rows from 2026-08 onward that have no request linked to them yet."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]

        importer = get_user_model().objects.filter(username=IMPORT_USERNAME).first()
        if importer is None:
            self.stdout.write(self.style.WARNING(f"User '{IMPORT_USERNAME}' not found — aborting"))
            return

        created = 0
        already_correct = 0
        skipped: list[str] = []

        for spec in EXPENSES:
            expense = CardExpense.objects.filter(pk=spec.expense_id, tenant_id=LEMONAQUA_TENANT_ID).first()
            if expense is None:
                skipped.append(f"CardExpense {spec.expense_id}: not found for tenant {LEMONAQUA_TENANT_ID}")
                continue
            if expense.amount != spec.amount:
                skipped.append(
                    f"CardExpense {spec.expense_id}: amount={expense.amount} != expected {spec.amount} — skipped"
                )
                continue

            existing = Request.all_objects.filter(
                tenant_id=LEMONAQUA_TENANT_ID,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
                expense_ref_id=spec.expense_id,
            ).first()
            if existing is not None:
                already_correct += 1
                self.stdout.write(f"  = CardExpense {spec.expense_id}: already has request {existing.id}")
                continue

            vendor = _vendor_from_title(expense.title)
            self.stdout.write(
                f"  + CardExpense {spec.expense_id} ({spec.amount}, {spec.expense_date}, {vendor}): "
                f"would create new PAYED request"
            )
            if apply_changes:
                new_req = Request.objects.create(
                    tenant_id=LEMONAQUA_TENANT_ID,
                    created_by=importer,
                    requester=importer,
                    description=(
                        f"[auto-created: заявка под расход по корпоративной карте, ранее не имевший "
                        f"заявки; CardExpense {spec.expense_id}, {spec.expense_date}, {spec.amount} UZS]"
                    ),
                    amount=spec.amount,
                    currency="UZS",
                    payment_type=Request.PAYMENT_TYPE_CARD,
                    urgency=Request.URGENCY_NORMAL,
                    vendor=vendor,
                    category=CATEGORY,
                    payment_purpose=PAYMENT_PURPOSE,
                    status=Request.STATUS_PAYED,
                    payed_at=int(spec.expense_date.strftime("%Y%m%d")),
                    expense_ref_id=spec.expense_id,
                    expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
                    billing_date=spec.expense_date.replace(day=1),
                )
                created += 1
                self.stdout.write(f"    -> created request {new_req.id}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Created' if apply_changes else 'Would create'}: {created}"))
        self.stdout.write(f"Already correct: {already_correct}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
