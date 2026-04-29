from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from apps.modules.investments.models import InvestCompany, InvestPayoutSchedule, InvestPayoutScheduleShareLink, InvestReturn
from apps.modules.investments.serializers import (
    InvestPayoutScheduleSerializer,
    InvestPayoutScheduleShareLinkSerializer,
    InvestReturnSerializer,
    ProjectInvestmentSerializer,
)
from apps.modules.investments.views import PublicInvestPayoutScheduleByTokenView
from apps.tenants.models import Tenant


User = get_user_model()
factory = APIRequestFactory()


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
        self.assertIsNotNone(obj.last_edit_at)

    def test_investreturn_last_edit_at_updates_on_change(self):
        ret = InvestReturn.objects.create(
            tenant=self.tenant,
            date=date(2026, 1, 1),
            sum=Decimal("1.00"),
            type="дивиденды",
            recipient="инвестор",
            created_by=self.user,
        )
        t1 = ret.last_edit_at
        self.assertIsNotNone(t1)
        ret.comment = "updated"
        ret.save()
        ret.refresh_from_db()
        self.assertIsNotNone(ret.last_edit_at)
        self.assertGreaterEqual(ret.last_edit_at, t1)


class InvestPayoutScheduleSerializerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="SchedCo", subdomain="schedco", is_active=True)
        self.user = User.objects.create_user(username="sched-user", password="x")

    def test_creates_payout_schedule(self):
        serializer = InvestPayoutScheduleSerializer(
            data={
                "payout_date": date(2026, 6, 1),
                "amount": "5000.00",
                "currency": "eur",
                "is_paid": True,
                "payment_amount": "5000.00",
                "comment": "Q2",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertEqual(obj.currency, "EUR")
        self.assertIsNotNone(obj.created_at)
        self.assertIsNotNone(obj.last_edit_at)
        self.assertIsNone(obj.company)


class ProjectInvestmentSerializerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="ProjCo", subdomain="projco", is_active=True)
        self.user = User.objects.create_user(username="proj-user", password="x")

    def test_creates_project_investment(self):
        serializer = ProjectInvestmentSerializer(
            data={
                "date": date(2026, 3, 15),
                "amount": "100000.00",
                "currency": "usd",
                "comment": "Round A",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertEqual(obj.currency, "USD")
        self.assertIsNotNone(obj.last_edit_at)
        self.assertIsNone(obj.company)


class InvestCompanyScopeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="ScopeCo", subdomain="scopeco", is_active=True)
        self.other_tenant = Tenant.objects.create(name="Other", subdomain="otherco", is_active=True)
        self.user = User.objects.create_user(username="scope-user", password="x")
        self.company = InvestCompany.objects.create(
            tenant=self.tenant,
            name="Company A",
            created_by=self.user,
        )
        self.other_company = InvestCompany.objects.create(
            tenant=self.other_tenant,
            name="Company B",
            created_by=self.user,
        )

    def test_project_investment_allows_company_from_same_tenant(self):
        request = factory.post("/api/investments/project-investments/")
        request.tenant = self.tenant
        serializer = ProjectInvestmentSerializer(
            data={
                "date": date(2026, 3, 15),
                "amount": "100000.00",
                "currency": "usd",
                "company": self.company.id,
            },
            context={"request": request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_project_investment_rejects_company_from_other_tenant(self):
        request = factory.post("/api/investments/project-investments/")
        request.tenant = self.tenant
        serializer = ProjectInvestmentSerializer(
            data={
                "date": date(2026, 3, 15),
                "amount": "100000.00",
                "currency": "usd",
                "company": self.other_company.id,
            },
            context={"request": request},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("company", serializer.errors)


class InvestPayoutScheduleShareLinkTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="ShareTenant", subdomain="sharetenant", is_active=True)
        self.user = User.objects.create_user(username="share-user", password="x")
        self.company = InvestCompany.objects.create(tenant=self.tenant, name="Syrop", created_by=self.user)
        self.other_company = InvestCompany.objects.create(tenant=self.tenant, name="Other", created_by=self.user)
        self.paid_row = InvestPayoutSchedule.objects.create(
            tenant=self.tenant,
            company=self.company,
            payout_date=date(2026, 6, 6),
            amount=Decimal("1500.00"),
            currency="USD",
            is_paid=True,
            payment_amount=Decimal("1500.00"),
            comment="Monthly 3%",
            created_by=self.user,
        )
        InvestPayoutSchedule.objects.create(
            tenant=self.tenant,
            company=self.company,
            payout_date=date(2026, 7, 6),
            amount=Decimal("1500.00"),
            currency="USD",
            is_paid=False,
            payment_amount=Decimal("0.00"),
            comment="Monthly 3%",
            created_by=self.user,
        )
        InvestPayoutSchedule.objects.create(
            tenant=self.tenant,
            company=self.other_company,
            payout_date=date(2026, 8, 6),
            amount=Decimal("1800.00"),
            currency="USD",
            is_paid=False,
            payment_amount=Decimal("0.00"),
            comment="Other company",
            created_by=self.user,
        )

    def test_serializer_creates_token(self):
        request = factory.post("/api/investments/payout-schedule-share-links/")
        request.tenant = self.tenant
        serializer = InvestPayoutScheduleShareLinkSerializer(
            data={"company": self.company.id, "paid_filter": "paid"},
            context={"request": request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertTrue(obj.token)
        self.assertGreaterEqual(len(obj.token), 16)

    def test_public_token_view_applies_saved_filters(self):
        link = InvestPayoutScheduleShareLink.objects.create(
            tenant=self.tenant,
            company=self.company,
            paid_filter=InvestPayoutScheduleShareLink.PaidFilter.PAID,
            created_by=self.user,
        )
        view = PublicInvestPayoutScheduleByTokenView.as_view()
        request = factory.get(f"/api/investments/public/payout-schedule/{link.token}/")
        response = view(request, token=link.token)
        self.assertEqual(response.status_code, 200)
        rows = response.data["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.paid_row.id)

    def test_public_token_view_rejects_inactive_link(self):
        link = InvestPayoutScheduleShareLink.objects.create(
            tenant=self.tenant,
            company=self.company,
            paid_filter=InvestPayoutScheduleShareLink.PaidFilter.ALL,
            is_active=False,
            created_by=self.user,
        )
        view = PublicInvestPayoutScheduleByTokenView.as_view()
        request = factory.get(f"/api/investments/public/payout-schedule/{link.token}/")
        response = view(request, token=link.token)
        self.assertEqual(response.status_code, 404)
