"""Tests for the fix_lemonaqua_request_7708_card_amount one-off command."""

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
    call_command("fix_lemonaqua_request_7708_card_amount", stdout=out, **options)
    return out.getvalue()


class FixLemonaquaRequest7708CardAmountTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=3, name="Lemonfit Aqua", subdomain="lemonaqua-7708test", is_active=True)
        self.admin = User.objects.create_user(username="admin-7708fix", password="x")
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")

        self.expense = CardExpense.objects.create(
            id=126, tenant=self.tenant, external_id="6459139685", title="FITLINE UZCARD DUO",
            amount=Decimal("130500.00"), currency="UZS", expense_at=_at_noon(date(2026, 8, 12)),
            wallet=self.wallet, created_by=self.admin,
        )
        self.req = Request.objects.create(
            id=7708, tenant=self.tenant, created_by=self.admin, requester=self.admin,
            title="Lemonfit Aqua", description="", amount=Decimal("130000.00"), currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD, urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 8, 1), vendor="FITLINE", category="Содержание клуба",
            payment_purpose="Расходники АХО", expense_id=None,
            status=Request.STATUS_PAYED, payed_at=20260813,
        )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.req.refresh_from_db()
        self.assertEqual(self.req.amount, Decimal("130000.00"))
        self.assertIsNone(self.req.expense_ref_id)
        self.assertIn("Dry run complete", output)

    def test_apply_links_and_corrects_amount(self):
        output = _run(apply=True)

        self.req.refresh_from_db()
        self.assertEqual(self.req.amount, Decimal("130500.00"))
        self.assertEqual(self.req.expense_ref_id, 126)
        self.assertEqual(self.req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD)
        self.assertIn("Fixed: 1", output)

        comment = RequestComment.objects.get(request=self.req)
        self.assertEqual(comment.created_by.username, "system")
        self.assertEqual(comment.created_by.full_name, "Система")
        self.assertIn("126", comment.body)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.req.refresh_from_db()
        self.assertEqual(self.req.amount, Decimal("130500.00"))
        self.assertIn("already linked and corrected", output)

    def test_expense_amount_mismatch_is_skipped(self):
        CardExpense.objects.filter(pk=126).update(amount=Decimal("1.00"))

        output = _run(apply=True)

        self.req.refresh_from_db()
        self.assertIsNone(self.req.expense_ref_id)
        self.assertEqual(self.req.amount, Decimal("130000.00"))
        self.assertIn("expected amount=130500.00", output)

    def test_unexpected_request_state_is_skipped(self):
        other_expense = CardExpense.objects.create(
            id=999, tenant=self.tenant, external_id="", title="Other",
            amount=Decimal("1.00"), currency="UZS", expense_at=_at_noon(date(2026, 8, 12)),
            wallet=self.wallet, created_by=self.admin,
        )
        Request.objects.filter(pk=7708).update(
            expense_ref_id=other_expense.id, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )

        output = _run(apply=True)

        self.req.refresh_from_db()
        self.assertEqual(self.req.expense_ref_id, other_expense.id)
        self.assertIn("unexpected state", output)

    def test_already_claimed_expense_is_skipped(self):
        other_req = Request.objects.create(
            id=9999, tenant=self.tenant, created_by=self.admin, requester=self.admin,
            title="Lemonfit Aqua", description="", amount=Decimal("130500.00"), currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD, urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 8, 1), expense_id=None,
            status=Request.STATUS_PAYED, payed_at=20260812,
        )
        Request.objects.filter(pk=9999).update(
            expense_ref_id=126, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )

        output = _run(apply=True)

        self.req.refresh_from_db()
        self.assertIsNone(self.req.expense_ref_id)
        self.assertIn("already claimed by request 9999", output)
