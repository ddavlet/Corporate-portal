"""
Tests for requests.card_revenue_reconciliation — the amount + payed_at fallback
matcher that links "Пополнение" (corporate card top-up) requests to CardRevenue
rows. Mirrors tests_bank_expense_reconciliation.py, minus the vendor dimension
(CardRevenue has no vendor to match on).
"""

from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.modules.corporate_card.models import CardRevenue
from apps.modules.requests.card_revenue_reconciliation import (
    reconcile_card_revenues_by_amount_date,
)
from apps.modules.requests.models import Request
from apps.modules.wallets.resolution import get_or_create_corporate_wallet
from apps.tenants.models import Tenant

User = get_user_model()


def _payed_at(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _at_noon(d: date):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


class CardRevenueReconciliationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-card-recon", is_active=True)
        self.admin = User.objects.create_user(username="admin-card-recon", password="x")
        self.card_wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")

    def _make_revenue(self, *, revenue_date, amount, external_id=""):
        return CardRevenue.objects.create(
            tenant=self.tenant,
            external_id=external_id,
            confirmed=True,
            total_sum=Decimal(amount),
            currency="UZS",
            revenue_at=_at_noon(revenue_date),
            wallet=self.card_wallet,
            created_by=self.admin,
        )

    def _make_request(self, *, amount, payed_date, expense_id="", expense_ref_id=None, title="R"):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title=title,
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TOPUP,
            urgency=Request.URGENCY_NORMAL,
            billing_date=payed_date.replace(day=1),
            expense_id=expense_id,
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD_REVENUE if expense_ref_id else None,
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(payed_date),
        )

    # -- basic matching ----------------------------------------------------

    def test_matches_within_window_without_vendor(self):
        revenue = self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 12))

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 1)
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, revenue.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD_REVENUE)

    def test_no_match_outside_window(self):
        self._make_revenue(revenue_date=date(2026, 3, 1), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10))

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_no_match_when_amount_differs(self):
        self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="501.00", payed_date=date(2026, 3, 10))

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_no_match_when_payed_at_missing(self):
        self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10))
        req.payed_at = None
        req.save(update_fields=["payed_at"])

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)

    def test_manual_expense_id_is_not_touched(self):
        self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10), expense_id="SOME-DOC-NO")

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_transfer_requests_are_not_candidates(self):
        """Only PAYMENT_TYPE_TOPUP is a card top-up; regular transfers must be ignored."""
        self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(amount="500.00", payed_date=date(2026, 3, 10))
        req.payment_type = Request.PAYMENT_TYPE_TRANSFER
        req.save(update_fields=["payment_type"])

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)

    # -- never touch existing links -----------------------------------------

    def test_does_not_relink_already_linked_request(self):
        other_revenue = self._make_revenue(revenue_date=date(2026, 1, 1), amount="999.00")
        matching_revenue = self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        req = self._make_request(
            amount="500.00", payed_date=date(2026, 3, 10), expense_ref_id=other_revenue.id,
        )

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, other_revenue.id)
        self.assertFalse(
            Request.objects.filter(expense_ref_id=matching_revenue.id).exists()
        )

    def test_does_not_reclaim_already_claimed_revenue(self):
        revenue = self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        self._make_request(
            amount="500.00", payed_date=date(2026, 3, 10),
            expense_ref_id=revenue.id, title="Already linked",
        )
        unlinked_req = self._make_request(
            amount="500.00", payed_date=date(2026, 3, 11), title="Should stay unlinked",
        )

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 0)
        unlinked_req.refresh_from_db()
        self.assertIsNone(unlinked_req.expense_ref_id)

    # -- multiple top-ups of the same amount --------------------------------

    def test_multiple_topups_same_amount_paired_by_closest_date(self):
        revenue_early = self._make_revenue(revenue_date=date(2026, 3, 5), amount="400.00")
        revenue_late = self._make_revenue(revenue_date=date(2026, 3, 20), amount="400.00")
        req_early = self._make_request(amount="400.00", payed_date=date(2026, 3, 6), title="Early")
        req_late = self._make_request(amount="400.00", payed_date=date(2026, 3, 19), title="Late")

        linked = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(linked, 2)
        req_early.refresh_from_db()
        req_late.refresh_from_db()
        self.assertEqual(req_early.expense_ref_id, revenue_early.id)
        self.assertEqual(req_late.expense_ref_id, revenue_late.id)

    # -- idempotency ----------------------------------------------------------

    def test_running_twice_is_a_no_op_the_second_time(self):
        self._make_revenue(revenue_date=date(2026, 3, 10), amount="500.00")
        self._make_request(amount="500.00", payed_date=date(2026, 3, 10))

        first = reconcile_card_revenues_by_amount_date(tenant=self.tenant)
        second = reconcile_card_revenues_by_amount_date(tenant=self.tenant)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)


class ReconcileCardRevenuesByAmountCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-card-recon-cmd", is_active=True)
        self.admin = User.objects.create_user(username="admin-card-recon-cmd", password="x")
        self.card_wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")

    def test_command_links_for_given_tenant(self):
        revenue = CardRevenue.objects.create(
            tenant=self.tenant,
            external_id="",
            confirmed=True,
            total_sum=Decimal("500.00"),
            currency="UZS",
            revenue_at=_at_noon(date(2026, 3, 10)),
            wallet=self.card_wallet,
            created_by=self.admin,
        )
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="R",
            description="",
            amount=Decimal("500.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TOPUP,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            expense_id="",
            status=Request.STATUS_PAYED,
            payed_at=_payed_at(date(2026, 3, 11)),
        )

        call_command("reconcile_card_revenues_by_amount", tenant=self.tenant.id)

        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, revenue.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD_REVENUE)
