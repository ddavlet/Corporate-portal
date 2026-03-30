from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.modules.corporate_card.models import CardExpense, CardRevenue


User = get_user_model()


class CorporateCardSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u", password="x")

    def test_can_create_card_expense(self):
        dt = timezone.now()
        obj = CardExpense.objects.create(
            tenant=self.tenant,
            title="Taxi",
            amount=5,
            currency="UZS",
            expense_at=dt,
            note="",
            payload={},
            created_by=self.user,
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(CardExpense.objects.filter(tenant=self.tenant).count(), 1)

    def test_can_create_card_revenue(self):
        dt = timezone.now()
        obj = CardRevenue.objects.create(
            tenant=self.tenant,
            external_id="rev-1",
            confirmed=True,
            title="Refund",
            amount=7,
            currency="UZS",
            total_sum=7,
            revenue_at=dt,
            note="",
            payload={},
            created_by=self.user,
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(CardRevenue.objects.filter(tenant=self.tenant).count(), 1)

