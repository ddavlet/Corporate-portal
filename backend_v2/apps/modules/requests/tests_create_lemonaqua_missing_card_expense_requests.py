"""Tests for the create_lemonaqua_missing_card_expense_requests one-off command."""

from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.modules.corporate_card.models import CardExpense
from apps.modules.requests.models import Request, RequestComment
from apps.modules.wallets.resolution import get_or_create_corporate_wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _at_noon(d: date):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


def _run(**options):
    out = StringIO()
    call_command("create_lemonaqua_missing_card_expense_requests", stdout=out, **options)
    return out.getvalue()


EXPENSE_SPECS = [
    (125, "14000.00", date(2026, 8, 11)),
    (124, "80000.00", date(2026, 8, 11)),
    (150, "90000.00", date(2026, 9, 3)),
    (148, "129900.00", date(2026, 9, 3)),
    (149, "118000.00", date(2026, 9, 3)),
    (147, "111000.00", date(2026, 9, 3)),
    (156, "128000.00", date(2026, 9, 6)),
]


class CreateLemonaquaMissingCardExpenseRequestsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=3, name="Lemonfit Aqua", subdomain="lemonaqua-backfilltest", is_active=True)
        self.importer = User.objects.create_user(username="app", password="x")
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")

        self.expenses = {}
        for expense_id, amount, expense_date in EXPENSE_SPECS:
            self.expenses[expense_id] = CardExpense.objects.create(
                id=expense_id, tenant=self.tenant, external_id=f"ext-{expense_id}",
                title='ООО "FITLINE FITNESS CENTER GROUP" UZCARD DUO',
                amount=Decimal(amount), currency="UZS", expense_at=_at_noon(expense_date),
                wallet=self.wallet, created_by=self.importer,
            )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.assertEqual(Request.objects.count(), 0)
        self.assertIn("Would create: 7", output)
        self.assertIn("Dry run complete", output)

    def test_apply_creates_one_request_per_expense(self):
        output = _run(apply=True)
        self.assertIn("Created: 7", output)
        self.assertEqual(Request.objects.count(), 7)

        req = Request.objects.get(expense_ref_id=147, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD)
        self.assertEqual(req.amount, Decimal("111000.00"))
        self.assertEqual(req.tenant_id, 3)
        self.assertEqual(req.payment_type, Request.PAYMENT_TYPE_CARD)
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.vendor, 'ООО "FITLINE FITNESS CENTER GROUP"')
        self.assertEqual(req.category, "Содержание клуба")
        self.assertEqual(req.payed_at, 20260903)
        self.assertEqual(req.billing_date, date(2026, 9, 1))
        self.assertEqual(req.created_by_id, self.importer.id)
        self.assertEqual(req.requester_id, self.importer.id)

        comment = RequestComment.objects.get(request=req)
        self.assertEqual(comment.created_by.username, "system")
        self.assertEqual(comment.created_by.full_name, "Система")
        self.assertIn("147", comment.body)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Created: 0", output)
        self.assertIn("Already correct: 7", output)
        self.assertEqual(Request.objects.count(), 7)

    def test_does_not_duplicate_when_expense_already_linked_elsewhere(self):
        Request.objects.create(
            id=9999, tenant=self.tenant, created_by=self.importer, requester=self.importer,
            title="Lemonfit Aqua", description="", amount=Decimal("111000.00"), currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD, urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1), expense_id=None,
            expense_ref_id=147, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
            status=Request.STATUS_PAYED, payed_at=20260903,
        )

        output = _run(apply=True)

        self.assertIn("Created: 6", output)
        self.assertIn("Already correct: 1", output)
        self.assertEqual(Request.objects.filter(expense_ref_id=147).count(), 1)

    def test_expense_amount_mismatch_is_skipped(self):
        CardExpense.objects.filter(pk=147).update(amount=Decimal("1.00"))

        output = _run(apply=True)

        self.assertIn("Created: 6", output)
        self.assertIn("Skipped (1)", output)
        self.assertIn("!= expected", output)
        self.assertFalse(Request.objects.filter(expense_ref_id=147).exists())

    def test_missing_importer_user_aborts_cleanly(self):
        User.objects.filter(username="app").delete()

        output = _run(apply=True)

        self.assertIn("not found", output)
        self.assertEqual(Request.objects.count(), 0)
