from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.wallets.resolution import get_or_create_cash_wallet


User = get_user_model()


class CashierSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u", password="x")

    def test_can_create_cash_expense(self):
        dt = timezone.now()
        w = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        obj = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="exp-1",
            confirmed=True,
            title="Lunch",
            amount=10,
            currency="UZS",
            wallet=w,
            expense_at=dt,
            expense_year=dt.year,
            expense_month=dt.month,
            expense_day=dt.day,
            note="",
            payload={},
            created_by=self.user,
        )

        self.assertIsNotNone(obj.id)
        self.assertEqual(CashExpense.objects.filter(tenant=self.tenant).count(), 1)

    def test_can_create_cash_revenue(self):
        w = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        obj = CashRevenue.objects.create(
            tenant=self.tenant,
            external_id="rev-1",
            total_sum=100,
            confirmed=True,
            wallet=w,
            operation="Sale",
            payload={},
            created_by=self.user,
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)

