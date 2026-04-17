from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.modules.investments.serializers import InvestReturnSerializer
from apps.tenants.models import Tenant


User = get_user_model()


class InvestReturnSerializerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="invest-admin", password="x")

    def test_accepts_sum_uzs_and_normalizes_currency(self):
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "sum": "100.00",
                "sum_uzs": "1260000.00",
                "comment": "Dividend payout in two currencies",
                "confirmed": True,
                "currency": "usd",
                "type": "дивиденды",
                "recipient": "инвестор",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertEqual(obj.currency, "USD")
        self.assertEqual(obj.sum, Decimal("100.00"))
        self.assertEqual(obj.sum_uzs, Decimal("1260000.00"))

    def test_sum_uzs_is_optional(self):
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "sum": "100.00",
                "comment": "Legacy format with one amount",
                "confirmed": False,
                "currency": "EUR",
                "type": "проценты",
                "recipient": "партнер",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertIsNone(obj.sum_uzs)
