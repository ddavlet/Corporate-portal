"""One-time: split three Lemonfit Aqua (tenant_id=3) "Платежная карта"
requests that were each filed as a single payment but actually cleared the
corporate card as two separate CardExpense transactions (FITLINE Fitness
Center Group splits charges across several small UZCARD DUO postings rather
than one lump sum).

`Request.expense_ref_id` can only point at one expense, so a 1:2 real-world
match can't be represented on the existing request row. For each pair below
this command:

  1. repoints the original request onto the *larger* of the two matching
     CardExpense rows and shrinks its `amount` to that transaction's amount;
  2. creates a new sibling request (same tenant/vendor/category/purpose,
     already `STATUS_PAYED`) for the *remaining* amount, pointed at the
     smaller CardExpense row.

    Request 7824 (277 000 UZS, payed 2026-09-07) -> CardExpense 136
    (216 000, 2026-08-20) + CardExpense 137 (61 000, 2026-08-20)

    Request 7854 (290 000 UZS, payed 2026-08-25) -> CardExpense 142
    (190 000, 2026-08-25) + CardExpense 143 (100 000, 2026-08-25)

    Request 8069 (93 000 UZS, payed 2026-09-12) -> CardExpense 161
    (53 000, 2026-09-10) + CardExpense 160 (40 000, 2026-09-10)

Run with --dry-run (default) first to preview, then with --apply to write.

Examples:
    python manage.py split_lemonaqua_card_expense_requests
    python manage.py split_lemonaqua_card_expense_requests --apply
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.models import Request, RequestComment

User = get_user_model()

LEMONAQUA_TENANT_ID = 3


@dataclass(frozen=True)
class SplitSpec:
    request_id: int
    total_amount: Decimal
    keep_expense_id: int
    keep_amount: Decimal
    new_expense_id: int
    new_amount: Decimal
    label: str


SPLITS: list[SplitSpec] = [
    SplitSpec(7824, Decimal("277000.00"), 136, Decimal("216000.00"), 137, Decimal("61000.00"), "FITLINE card charges 2026-08-20"),
    SplitSpec(7854, Decimal("290000.00"), 142, Decimal("190000.00"), 143, Decimal("100000.00"), "FITLINE card charges 2026-08-25"),
    SplitSpec(8069, Decimal("93000.00"), 161, Decimal("53000.00"), 160, Decimal("40000.00"), "FITLINE card charges 2026-09-10"),
]


def _original_comment_body(spec: SplitSpec) -> str:
    return (
        f"Сумма заявки скорректирована с {spec.total_amount} до {spec.keep_amount} и привязана к "
        f"CardExpense {spec.keep_expense_id}: расход по факту разбился на 2 транзакции по корпоративной "
        f"карте ({spec.label}). Остаток {spec.new_amount} вынесен в отдельную заявку, привязанную к "
        f"CardExpense {spec.new_expense_id}."
    )


def _copy_comment_body(spec: SplitSpec) -> str:
    return (
        f"Заявка создана автоматически — часть суммы, выделенная из заявки #{spec.request_id} "
        f"(расход разбился на 2 транзакции по корпоративной карте, {spec.label}). "
        f"Привязана к CardExpense {spec.new_expense_id}."
    )


def _system_user():
    """pk=1 already displays as "Система" — same account
    apps.modules.n8n_integration.views._system_user() uses."""
    return User.objects.filter(pk=1).first()


def _ensure_system_comment(*, request: Request, system_user, body: str) -> bool:
    if system_user is None:
        return False
    if RequestComment.objects.filter(request=request, created_by=system_user, body=body).exists():
        return False
    RequestComment.objects.create(request=request, created_by=system_user, body=body)
    return True


def _claimant(*, tenant_id: int, expense_id: int, exclude_request_id: int):
    return (
        Request.all_objects.filter(
            tenant_id=tenant_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
            expense_ref_id=expense_id,
        )
        .exclude(pk=exclude_request_id)
        .first()
    )


def _clone_for_split(original: Request, *, amount: Decimal, expense_id: int, note: str) -> Request:
    return Request.objects.create(
        tenant=original.tenant,
        created_by=original.created_by,
        company_payer=original.company_payer,
        category=original.category,
        vendor=original.vendor,
        vendor_ref=original.vendor_ref,
        contract_ref=original.contract_ref,
        description=(f"{original.description}\n{note}" if original.description else note),
        amount=amount,
        currency=original.currency,
        payment_type=original.payment_type,
        urgency=original.urgency,
        requester=original.requester,
        payment_purpose=original.payment_purpose,
        status=Request.STATUS_PAYED,
        payed_at=original.payed_at,
        expense_ref_id=expense_id,
        expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        billing_date=original.billing_date,
        amortization_months=original.amortization_months,
        amortization_start_date=original.amortization_start_date,
    )


class Command(BaseCommand):
    help = (
        "One-time fix: split requests 7824, 7854 and 8069 (tenant 3, Lemonfit Aqua) "
        "into one request per matching CardExpense transaction."
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

        fixed = 0
        already_correct = 0
        comments_backfilled = 0
        skipped: list[str] = []

        for spec in SPLITS:
            req = Request.objects.filter(pk=spec.request_id, tenant_id=LEMONAQUA_TENANT_ID).first()
            if req is None:
                skipped.append(f"Request {spec.request_id}: not found for tenant {LEMONAQUA_TENANT_ID}")
                continue

            keep_expense = CardExpense.objects.filter(pk=spec.keep_expense_id, tenant_id=LEMONAQUA_TENANT_ID).first()
            new_expense = CardExpense.objects.filter(pk=spec.new_expense_id, tenant_id=LEMONAQUA_TENANT_ID).first()
            bad_expense = None
            for expense, expense_id, expected_amount in (
                (keep_expense, spec.keep_expense_id, spec.keep_amount),
                (new_expense, spec.new_expense_id, spec.new_amount),
            ):
                if expense is None:
                    bad_expense = f"CardExpense {expense_id} not found for tenant"
                    break
                if expense.amount != expected_amount:
                    bad_expense = f"CardExpense {expense_id} amount={expense.amount} != expected {expected_amount}"
                    break
            if bad_expense:
                skipped.append(f"Request {spec.request_id}: {bad_expense} — skipped")
                continue

            original_applied = (
                req.expense_ref_target == Request.EXPENSE_REF_TARGET_CARD
                and req.expense_ref_id == spec.keep_expense_id
                and req.amount == spec.keep_amount
            )
            existing_copy = Request.all_objects.filter(
                tenant_id=LEMONAQUA_TENANT_ID,
                expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
                expense_ref_id=spec.new_expense_id,
                amount=spec.new_amount,
            ).exclude(pk=req.pk).first()

            if original_applied and existing_copy is not None:
                already_correct += 1
                self.stdout.write(f"  = Request {spec.request_id}: already split ({spec.label})")
                if apply_changes:
                    added_original = _ensure_system_comment(
                        request=req, system_user=system_user, body=_original_comment_body(spec),
                    )
                    added_copy = _ensure_system_comment(
                        request=existing_copy, system_user=system_user, body=_copy_comment_body(spec),
                    )
                    if added_original or added_copy:
                        comments_backfilled += 1
                continue

            if not (req.amount == spec.total_amount and req.expense_ref_id is None):
                skipped.append(
                    f"Request {spec.request_id}: expected amount={spec.total_amount} and no expense_ref_id, "
                    f"found amount={req.amount} expense_ref_id={req.expense_ref_id} "
                    f"— skipped (unexpected state on original request, resolve manually)"
                )
                continue

            keep_claimant = _claimant(
                tenant_id=LEMONAQUA_TENANT_ID, expense_id=spec.keep_expense_id, exclude_request_id=req.pk,
            )
            new_claimant = _claimant(
                tenant_id=LEMONAQUA_TENANT_ID, expense_id=spec.new_expense_id, exclude_request_id=req.pk,
            )
            claimant = keep_claimant or new_claimant
            if claimant is not None:
                claimed_expense_id = spec.keep_expense_id if keep_claimant else spec.new_expense_id
                skipped.append(
                    f"Request {spec.request_id}: CardExpense {claimed_expense_id} already claimed by "
                    f"request {claimant.id} — skipped"
                )
                continue

            fixed += 1
            self.stdout.write(
                f"  + Request {spec.request_id}: amount {req.amount} -> {spec.keep_amount} "
                f"(expense {spec.keep_expense_id}); new request for {spec.new_amount} "
                f"(expense {spec.new_expense_id}) — {spec.label}"
            )
            if apply_changes:
                with transaction.atomic():
                    note = (
                        f"[auto-split {spec.label}: часть суммы, перенесена в новую заявку "
                        f"по CardExpense {spec.new_expense_id}]"
                    )
                    Request.objects.filter(pk=spec.request_id).update(
                        amount=spec.keep_amount,
                        expense_ref_id=spec.keep_expense_id,
                        expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
                        description=(f"{req.description}\n{note}" if req.description else note),
                    )
                    new_req = _clone_for_split(
                        req,
                        amount=spec.new_amount,
                        expense_id=spec.new_expense_id,
                        note=f"[auto-split {spec.label}: выделено из заявки #{spec.request_id}]",
                    )
                    if system_user is not None:
                        RequestComment.objects.create(
                            request_id=spec.request_id, created_by=system_user, body=_original_comment_body(spec),
                        )
                        RequestComment.objects.create(
                            request=new_req, created_by=system_user, body=_copy_comment_body(spec),
                        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Fixed' if apply_changes else 'Would fix'}: {fixed}"))
        self.stdout.write(f"Already correct: {already_correct}")
        if apply_changes:
            self.stdout.write(f"Comments backfilled on already-correct requests: {comments_backfilled}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
