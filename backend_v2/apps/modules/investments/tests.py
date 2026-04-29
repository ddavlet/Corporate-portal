from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from rest_framework.test import APIRequestFactory
from rest_framework.test import APITestCase

from apps.modules.investments.models import InvestCompany, InvestPayoutSchedule, InvestPayoutScheduleShareLink, InvestReturn
from apps.tenants.models import TenantMembership, TenantModuleConfig, TenantUserRole
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


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentApprovalFlowTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="InvestFlow", subdomain="investflow", is_active=True)
        self.host = "investflow.example.com"
        self.admin = User.objects.create_user(username="inv_admin", password="x")
        self.approver1 = User.objects.create_user(
            username="inv_appr_1",
            password="x",
            telegram_chat_id=555001,
            telegram_from_id=777001,
        )
        self.approver2 = User.objects.create_user(
            username="inv_appr_2",
            password="x",
            telegram_chat_id=555002,
            telegram_from_id=777002,
        )
        self.intruder = User.objects.create_user(
            username="intruder",
            password="x",
            telegram_chat_id=999001,
            telegram_from_id=999002,
        )
        for user in (self.admin, self.approver1, self.approver2, self.intruder):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver1, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver2, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.intruder, role=TenantUserRole.ROLE_DIRECTOR)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)

        self.client.force_authenticate(self.admin)
        cfg_payload = {
            "is_enabled": True,
            "steps": [
                {"step": 1, "is_enabled": True, "approver_user_ids": [self.approver1.id]},
                {"step": 2, "is_enabled": True, "approver_user_ids": [self.approver2.id]},
            ],
        }
        response = self.client.put("/api/investments/approval-config/", cfg_payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)

    @patch("apps.modules.investments.approval_services.post_telegram_bridge")
    def test_create_return_creates_approvals_and_dispatches_first_step(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 101}
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "sum": "1200.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
                "comment": "Auto approval",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        created = InvestReturn.objects.get(id=response.data["id"])
        self.assertFalse(created.confirmed)
        self.assertEqual(created.approvals.count(), 2)
        self.assertEqual(bridge_mock.call_count, 1)
        self.assertIn("Новая выплата по InvestFlow", bridge_mock.call_args.kwargs["payload"]["message"])

    @patch("apps.modules.investments.approval_services.post_telegram_bridge")
    def test_callback_enforces_authorization_and_final_confirmation(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 202}
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "sum": "900.00",
                "currency": "EUR",
                "type": "проценты",
                "recipient": "партнер",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        inv_return = InvestReturn.objects.get(id=response.data["id"])
        first_step = inv_return.approvals.get(step=1)
        second_step = inv_return.approvals.get(step=2)

        bad_res = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "callback_query": {
                    "data": f"inv_{first_step.id}:a",
                    "from": {"id": self.intruder.telegram_from_id},
                    "message": {"message_id": first_step.message_id or 202, "chat": {"id": self.intruder.telegram_chat_id}},
                }
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(bad_res.status_code, 400)

        ok_first = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "callback_query": {
                    "data": f"inv_{first_step.id}:a",
                    "from": {"id": self.approver1.telegram_from_id},
                    "message": {"message_id": first_step.message_id or 202, "chat": {"id": self.approver1.telegram_chat_id}},
                }
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(ok_first.status_code, 200)
        first_step.refresh_from_db()
        self.assertEqual(first_step.decision, "approved")

        not_active = self.client.post(
            f"/api/investments/approvals/{first_step.id}/decision/",
            {"decision": "approved"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertIn(not_active.status_code, (400, 409))

        ok_second = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "callback_query": {
                    "data": f"inv_{second_step.id}:a",
                    "from": {"id": self.approver2.telegram_from_id},
                    "message": {"message_id": 303, "chat": {"id": self.approver2.telegram_chat_id}},
                }
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(ok_second.status_code, 200)
        inv_return.refresh_from_db()
        self.assertTrue(inv_return.confirmed)

    @patch("apps.modules.investments.approval_services.post_telegram_bridge")
    def test_reject_keeps_return_unconfirmed(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 404}
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "sum": "500.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        inv_return = InvestReturn.objects.get(id=response.data["id"])
        first_step = inv_return.approvals.get(step=1)
        reject_res = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "callback_query": {
                    "data": f"inv_{first_step.id}:r",
                    "from": {"id": self.approver1.telegram_from_id},
                    "message": {"message_id": first_step.message_id or 404, "chat": {"id": self.approver1.telegram_chat_id}},
                }
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(reject_res.status_code, 200)
        inv_return.refresh_from_db()
        self.assertFalse(inv_return.confirmed)
