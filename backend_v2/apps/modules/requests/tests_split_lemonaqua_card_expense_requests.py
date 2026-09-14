"""Tests for the split_lemonaqua_card_expense_requests one-off command."""

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
    call_command("split_lemonaqua_card_expense_requests", stdout=out, **options)
    return out.getvalue()


class SplitLemonaquaCardExpenseRequestsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=3, name="Lemonfit Aqua", subdomain="lemonaqua-cardsplittest", is_active=True)
        self.admin = User.objects.create_user(username="admin-cardsplit", password="x")
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")

        self.expense_136 = self._make_expense(id=136, amount="216000.00", expense_date=date(2026, 8, 20))
        self.expense_137 = self._make_expense(id=137, amount="61000.00", expense_date=date(2026, 8, 20))
        self.expense_142 = self._make_expense(id=142, amount="190000.00", expense_date=date(2026, 8, 25))
        self.expense_143 = self._make_expense(id=143, amount="100000.00", expense_date=date(2026, 8, 25))
        self.expense_160 = self._make_expense(id=160, amount="40000.00", expense_date=date(2026, 9, 10))
        self.expense_161 = self._make_expense(id=161, amount="53000.00", expense_date=date(2026, 9, 10))

        self.req_7824 = self._make_request(
            id=7824, amount="277000.00", billing_date=date(2026, 9, 1), payed_at=20260907,
            vendor="FITLINE", category="Содержание клуба", payment_purpose="Расходники Тех Отдел",
        )
        self.req_7854 = self._make_request(
            id=7854, amount="290000.00", billing_date=date(2026, 8, 1), payed_at=20260825,
            vendor="FITLINE", category="Содержание клуба", payment_purpose="Расходники АХО",
        )
        self.req_8069 = self._make_request(
            id=8069, amount="93000.00", billing_date=date(2026, 9, 1), payed_at=20260912,
            vendor="FITLINE", category="Содержание клуба", payment_purpose="Расходники Тех Отдел",
        )

    def _make_expense(self, *, id, amount, expense_date):
        return CardExpense.objects.create(
            id=id, tenant=self.tenant, external_id="", title="FITLINE UZCARD DUO",
            amount=Decimal(amount), currency="UZS", expense_at=_at_noon(expense_date),
            wallet=self.wallet, created_by=self.admin,
        )

    def _make_request(self, *, id, amount, billing_date, payed_at, vendor, category, payment_purpose):
        return Request.objects.create(
            id=id, tenant=self.tenant, created_by=self.admin, requester=self.admin,
            title="Lemonfit Aqua", description="", amount=Decimal(amount), currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD, urgency=Request.URGENCY_NORMAL,
            billing_date=billing_date, vendor=vendor, category=category, payment_purpose=payment_purpose,
            expense_id=None, status=Request.STATUS_PAYED, payed_at=payed_at,
        )

    # -- dry run --------------------------------------------------------------

    def test_dry_run_makes_no_changes(self):
        output = _run()

        for req, expected_amount in ((self.req_7824, "277000.00"), (self.req_7854, "290000.00"), (self.req_8069, "93000.00")):
            req.refresh_from_db()
            self.assertEqual(req.amount, Decimal(expected_amount))
            self.assertIsNone(req.expense_ref_id)

        self.assertEqual(Request.objects.count(), 3)
        self.assertIn("Would fix: 3", output)
        self.assertIn("Dry run complete", output)

    # -- apply ------------------------------------------------------------------

    def test_apply_splits_all_three_requests(self):
        output = _run(apply=True)
        self.assertIn("Fixed: 3", output)

        self.req_7824.refresh_from_db()
        self.assertEqual(self.req_7824.amount, Decimal("216000.00"))
        self.assertEqual(self.req_7824.expense_ref_id, 136)
        self.assertEqual(self.req_7824.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD)

        self.req_7854.refresh_from_db()
        self.assertEqual(self.req_7854.amount, Decimal("190000.00"))
        self.assertEqual(self.req_7854.expense_ref_id, 142)

        self.req_8069.refresh_from_db()
        self.assertEqual(self.req_8069.amount, Decimal("53000.00"))
        self.assertEqual(self.req_8069.expense_ref_id, 161)

        # one new sibling request per original, linked to the remaining expense
        self.assertEqual(Request.objects.count(), 6)

        copy_7824 = Request.objects.get(expense_ref_id=137, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD)
        self.assertEqual(copy_7824.amount, Decimal("61000.00"))
        self.assertEqual(copy_7824.status, Request.STATUS_PAYED)
        self.assertEqual(copy_7824.payment_type, Request.PAYMENT_TYPE_CARD)
        self.assertEqual(copy_7824.vendor, "FITLINE")
        self.assertEqual(copy_7824.tenant_id, 3)

        copy_7854 = Request.objects.get(expense_ref_id=143, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD)
        self.assertEqual(copy_7854.amount, Decimal("100000.00"))

        copy_8069 = Request.objects.get(expense_ref_id=160, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD)
        self.assertEqual(copy_8069.amount, Decimal("40000.00"))

        comment = RequestComment.objects.get(request_id=7824)
        self.assertEqual(comment.created_by.username, "system")
        self.assertEqual(comment.created_by.full_name, "Система")
        self.assertIn("136", comment.body)
        copy_comment = RequestComment.objects.get(request=copy_7824)
        self.assertIn("7824", copy_comment.body)
        self.assertEqual(RequestComment.objects.count(), 6)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Fixed: 0", output)
        self.assertIn("Already correct: 3", output)
        self.assertIn("Comments backfilled on already-correct requests: 0", output)
        self.assertEqual(Request.objects.count(), 6)
        self.assertEqual(RequestComment.objects.count(), 6)

    def test_apply_backfills_comment_on_request_split_before_this_feature_existed(self):
        # Simulate 7824 having already been split by an older version of this
        # command that didn't leave comments (i.e. production state right now).
        Request.objects.filter(pk=7824).update(
            amount=Decimal("216000.00"), expense_ref_id=136, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )
        self._make_request(
            id=8200, amount="61000.00", billing_date=date(2026, 9, 1), payed_at=20260907,
            vendor="FITLINE", category="Содержание клуба", payment_purpose="Расходники Тех Отдел",
        )
        Request.objects.filter(pk=8200).update(
            expense_ref_id=137, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )
        self.assertEqual(RequestComment.objects.count(), 0)

        output = _run(apply=True)

        self.assertIn("Fixed: 2", output)
        self.assertIn("Already correct: 1", output)
        self.assertIn("Comments backfilled on already-correct requests: 1", output)
        self.assertTrue(RequestComment.objects.filter(request_id=7824).exists())
        self.assertTrue(RequestComment.objects.filter(request_id=8200).exists())

        # re-running again must not duplicate the backfilled comments
        _run(apply=True)
        self.assertEqual(RequestComment.objects.filter(request_id=7824).count(), 1)
        self.assertEqual(RequestComment.objects.filter(request_id=8200).count(), 1)

    # -- defensive checks -------------------------------------------------------

    def test_unexpected_current_state_is_skipped_not_overwritten(self):
        # Someone already manually linked this request to an unrelated expense.
        other_expense = self._make_expense(id=999, amount="1.00", expense_date=date(2026, 8, 20))
        Request.objects.filter(pk=7824).update(
            expense_ref_id=other_expense.id, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )

        output = _run(apply=True)

        self.req_7824.refresh_from_db()
        self.assertEqual(self.req_7824.expense_ref_id, other_expense.id)
        self.assertIn("Fixed: 2", output)
        self.assertIn("Skipped (1)", output)
        self.assertIn("unexpected state", output)
        self.assertEqual(Request.objects.count(), 5)

    def test_expense_amount_mismatch_is_skipped(self):
        CardExpense.objects.filter(pk=136).update(amount=Decimal("1.00"))

        output = _run(apply=True)

        self.req_7824.refresh_from_db()
        self.assertIsNone(self.req_7824.expense_ref_id)
        self.assertIn("Fixed: 2", output)
        self.assertIn("Skipped (1)", output)
        self.assertIn("!= expected", output)

    def test_already_claimed_expense_is_skipped(self):
        # expense_ref_id 137 already claimed by some unrelated request.
        other_req = self._make_request(
            id=9999, amount="61000.00", billing_date=date(2026, 8, 1), payed_at=20260820,
            vendor="Other", category="Прочее", payment_purpose="",
        )
        Request.objects.filter(pk=9999).update(
            expense_ref_id=137, expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )

        output = _run(apply=True)

        self.req_7824.refresh_from_db()
        self.assertIsNone(self.req_7824.expense_ref_id)
        self.assertIn("already claimed by request 9999", output)
