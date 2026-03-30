from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.modules.cashier.models import CashExpense, CashRevenue


User = get_user_model()


class CashierSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u", password="x")

    def test_can_create_cash_expense(self):
        dt = timezone.now()
        obj = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="exp-1",
            confirmed=True,
            title="Lunch",
            amount=10,
            currency="UZS",
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
        obj = CashRevenue.objects.create(
            tenant=self.tenant,
            title="Sale",
            amount=100,
            currency="UZS",
            note="",
            payload={},
            created_by=self.user,
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(CashRevenue.objects.filter(tenant=self.tenant).count(), 1)

