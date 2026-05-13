from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.modules.investments.approval_services import build_investment_return_approval_telegram_message

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.test import override_settings
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from rest_framework.test import APITestCase

from apps.modules.investments.approval_services import INVESTMENT_APPROVAL_CASCADE_REJECTION_COMMENT
from apps.modules.investments.models import (
    InvestCompany,
    InvestmentApprovalConfigStep,
    InvestmentFormConfig,
    InvestmentReturnApproval,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.tenants.models import TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.pnl_builder import build_pnl_payload_from_db
from apps.modules.reports.tests import full_backend_pnl_config
from apps.modules.investments.serializers import (
    InvestPayoutScheduleSerializer,
    InvestPayoutScheduleShareLinkSerializer,
    InvestReturnSerializer,
    ProjectInvestmentSerializer,
)
from apps.modules.investments.services import (
    fetch_cbu_usd_uzs_rate,
    invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin,
)
from apps.modules.investments.views import PublicInvestPayoutScheduleByTokenView
from apps.tenants.models import Tenant


User = get_user_model()
factory = APIRequestFactory()


class InvestReturnApprovalTelegramMessageTests(SimpleTestCase):
    def test_message_omits_fx_block_without_both_uzs_and_cbu(self):
        ir = MagicMock()
        ir.id = 99
        ir.company = None
        ir.tenant = MagicMock()
        ir.tenant.name = "Solo"
        ir.sum = Decimal("50.00")
        ir.currency = "USD"
        ir.date = date(2026, 5, 1)
        ir.billing_date = date(2026, 5, 1)
        ir.type = "дивиденды"
        ir.recipient = "инвестор"
        ir.comment = ""
        ir.sum_uzs = None
        ir.cbu_usd_uzs_rate = None
        ir.get_type_display = lambda: "Дивиденды"
        ir.get_recipient_display = lambda: "Инвестор"

        approval = MagicMock()
        approval.step = 1
        approval.step_type = InvestmentApprovalConfigStep.STEP_TYPE_SERIAL
        approval.decision = InvestmentReturnApproval.DECISION_PENDING
        u = MagicMock()
        u.full_name = "Иван Петров"
        u.username = "ivan"
        approval.approver_user = u

        out = build_investment_return_approval_telegram_message(
            invest_return=ir,
            approval=approval,
            blocked_by_rejection=False,
            current_pending_step=1,
        )
        self.assertIn("💵", out)
        self.assertNotIn("Курс CBU", out)
        self.assertNotIn("🇺🇿", out)
        self.assertNotIn("Комментарий", out)
        self.assertIn("Ожидается подтверждение от", out)
        self.assertIn("Иван Петров", out)

    def test_cbu_rate_rounded_to_two_decimals_in_message(self):
        ir = MagicMock()
        ir.id = 1
        ir.company = None
        ir.tenant = MagicMock()
        ir.tenant.name = "T"
        ir.sum = Decimal("1.00")
        ir.currency = "USD"
        ir.date = date(2026, 5, 1)
        ir.billing_date = date(2026, 5, 1)
        ir.type = "дивиденды"
        ir.recipient = "инвестор"
        ir.comment = ""
        ir.sum_uzs = Decimal("12600123.45")
        ir.cbu_usd_uzs_rate = Decimal("12600.126")
        ir.get_type_display = lambda: "Дивиденды"
        ir.get_recipient_display = lambda: "Инвестор"

        approval = MagicMock()
        approval.step = 1
        approval.step_type = InvestmentApprovalConfigStep.STEP_TYPE_SERIAL
        approval.decision = InvestmentReturnApproval.DECISION_PENDING
        u = MagicMock()
        u.full_name = "Иван Петров"
        u.username = "ivan"
        approval.approver_user = u

        out = build_investment_return_approval_telegram_message(
            invest_return=ir,
            approval=approval,
            blocked_by_rejection=False,
            current_pending_step=1,
        )
        self.assertIn("📊 Курс CBU: 12 600.13 UZS/$", out)
        self.assertIn("Ожидается подтверждение от", out)

    def test_message_hides_approver_line_when_step_not_active_yet(self):
        ir = MagicMock()
        ir.id = 2
        ir.company = None
        ir.tenant = MagicMock()
        ir.tenant.name = "T"
        ir.sum = Decimal("10.00")
        ir.currency = "USD"
        ir.date = date(2026, 5, 1)
        ir.billing_date = date(2026, 5, 1)
        ir.type = "дивиденды"
        ir.recipient = "инвестор"
        ir.comment = ""
        ir.sum_uzs = None
        ir.cbu_usd_uzs_rate = None
        ir.get_type_display = lambda: "Дивиденды"
        ir.get_recipient_display = lambda: "Инвестор"

        approval = MagicMock()
        approval.step = 2
        approval.step_type = InvestmentApprovalConfigStep.STEP_TYPE_SERIAL
        approval.decision = InvestmentReturnApproval.DECISION_PENDING
        u = MagicMock()
        u.full_name = "Позже Согласует"
        u.username = "later"
        approval.approver_user = u

        out = build_investment_return_approval_telegram_message(
            invest_return=ir,
            approval=approval,
            blocked_by_rejection=False,
            current_pending_step=1,
        )
        self.assertNotIn("Ожидается подтверждение от", out)


class InvestReturnSerializerTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="invest-admin", password="x")
        self._p_allow_billing = patch(
            "apps.modules.investments.serializers.is_accrual_month_allowed",
            return_value=True,
        )
        self._p_allow_billing.start()
        self.addCleanup(self._p_allow_billing.stop)

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate", return_value=Decimal("12600"))
    def test_usd_normalizes_currency_and_computes_sum_uzs(self, _mock_fetch):
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "100.00",
                "comment": "Dividend payout",
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
        self.assertEqual(obj.cbu_usd_uzs_rate, Decimal("12600"))
        self.assertEqual(obj.billing_date, date(2026, 4, 1))

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate", return_value=Decimal("12600"))
    def test_uzs_sets_sum_equal_sum_uzs(self, _mock_fetch):
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "5000000",
                "comment": "Payout in soums",
                "confirmed": False,
                "currency": "UZS",
                "type": "проценты",
                "recipient": "партнер",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertEqual(obj.sum, Decimal("5000000.00"))
        self.assertEqual(obj.sum_uzs, Decimal("5000000.00"))
        self.assertEqual(obj.cbu_usd_uzs_rate, Decimal("12600"))
        self.assertEqual(obj.billing_date, date(2026, 4, 1))

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate", return_value=Decimal("12600"))
    @patch("apps.modules.investments.serializers.is_accrual_month_allowed", return_value=False)
    def test_rejects_billing_month_when_not_allowed(self, _allow, _fetch):
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "100.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("billing_date", serializer.errors)

    def test_rejects_eur(self):
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "100.00",
                "currency": "EUR",
                "type": "проценты",
                "recipient": "партнер",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("currency", serializer.errors)

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate", return_value=Decimal("10000"))
    def test_client_sum_uzs_is_ignored(self, _mock_fetch):
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "10.00",
                "sum_uzs": "1.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertEqual(obj.sum_uzs, Decimal("100000.00"))

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate")
    def test_create_fails_when_cbu_unavailable(self, mock_fetch):
        from apps.modules.investments.services import CbuRateFetchError

        mock_fetch.side_effect = CbuRateFetchError("offline")
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "10.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with self.assertRaises(serializers.ValidationError):
            serializer.save(tenant=self.tenant, created_by=self.user)

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate", return_value=Decimal("10000"))
    def test_update_recomputes_sum_uzs_using_stored_rate(self, mock_fetch):
        obj = InvestReturn.objects.create(
            tenant=self.tenant,
            date=date(2026, 4, 1),
            billing_date=date(2026, 4, 1),
            sum=Decimal("100.00"),
            sum_uzs=Decimal("1000000.00"),
            currency="USD",
            cbu_usd_uzs_rate=Decimal("10000"),
            type="дивиденды",
            recipient="инвестор",
            created_by=self.user,
        )
        serializer = InvestReturnSerializer(
            instance=obj,
            data={"sum": "200.00"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        updated = serializer.save()
        mock_fetch.assert_not_called()
        self.assertEqual(updated.sum, Decimal("200.00"))
        self.assertEqual(updated.sum_uzs, Decimal("2000000.00"))
        self.assertEqual(updated.cbu_usd_uzs_rate, Decimal("10000"))

    def test_investreturn_last_edit_at_updates_on_change(self):
        ret = InvestReturn.objects.create(
            tenant=self.tenant,
            date=date(2026, 1, 1),
            billing_date=date(2026, 1, 1),
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

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate", return_value=Decimal("12600"))
    def test_rejects_disallowed_return_type(self, _mock_fetch):
        InvestmentFormConfig.objects.create(
            tenant=self.tenant,
            uses_companies=True,
            allowed_return_types=["проценты"],
        )
        request = factory.post("/api/investments/returns/")
        request.tenant = self.tenant
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "100.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            context={"request": request},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("type", serializer.errors)

    @patch("apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate", return_value=Decimal("12600"))
    def test_create_clears_company_when_form_disables_companies(self, _mock_fetch):
        co = InvestCompany.objects.create(tenant=self.tenant, name="Co", created_by=self.user)
        InvestmentFormConfig.objects.create(
            tenant=self.tenant,
            uses_companies=False,
            allowed_return_types=["дивиденды", "проценты", "доля_прибыли", "тело_инвестиций"],
        )
        request = factory.post("/api/investments/returns/")
        request.tenant = self.tenant
        serializer = InvestReturnSerializer(
            data={
                "date": date(2026, 4, 17),
                "billing_date": date(2026, 4, 1),
                "sum": "100.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
                "company": co.id,
            },
            context={"request": request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertIsNone(obj.company_id)


class InvestReturnCbuServicesTests(TestCase):
    @patch("apps.modules.investments.services.requests.get")
    def test_fetch_cbu_uses_all_by_date_url(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = [{"Ccy": "USD", "Nominal": "1", "Rate": "12000.5"}]
        mock_get.return_value = mock_resp

        out = fetch_cbu_usd_uzs_rate(rate_date=date(2020, 1, 15))
        self.assertEqual(out, Decimal("12000.5"))
        url = mock_get.call_args[0][0]
        self.assertIn("/all/2020-01-15/", url)

    @patch("apps.modules.investments.services.requests.get")
    def test_fetch_cbu_accepts_single_object_json(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"Ccy": "USD", "Nominal": "1", "Rate": "11500"}
        mock_get.return_value = mock_resp

        out = fetch_cbu_usd_uzs_rate(rate_date=date(2019, 6, 1))
        self.assertEqual(out, Decimal("11500"))

    def test_invest_return_cbu_fields_from_bulletin_usd(self):
        rows = [{"Ccy": "USD", "Nominal": "1", "Rate": "10000"}]
        usd, su = invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin(
            sum_val=Decimal("2"), currency="USD", rows=rows
        )
        self.assertEqual(usd, Decimal("10000"))
        self.assertEqual(su, Decimal("20000"))

    def test_invest_return_cbu_fields_from_bulletin_uzs(self):
        rows = [{"Ccy": "USD", "Nominal": "1", "Rate": "12000"}]
        usd, su = invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin(
            sum_val=Decimal("5000"), currency="UZS", rows=rows
        )
        self.assertEqual(usd, Decimal("12000"))
        self.assertEqual(su, Decimal("5000"))

    def test_invest_return_cbu_fields_from_bulletin_eur(self):
        rows = [
            {"Ccy": "USD", "Nominal": "1", "Rate": "12000"},
            {"Ccy": "EUR", "Nominal": "1", "Rate": "13000"},
        ]
        usd, su = invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin(
            sum_val=Decimal("10"), currency="EUR", rows=rows
        )
        self.assertEqual(usd, Decimal("12000"))
        self.assertEqual(su, Decimal("130000"))


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

    def test_clears_company_when_form_disables_companies(self):
        co = InvestCompany.objects.create(tenant=self.tenant, name="SchedCo", created_by=self.user)
        InvestmentFormConfig.objects.create(
            tenant=self.tenant,
            uses_companies=False,
            allowed_return_types=["дивиденды"],
        )
        request = factory.post("/api/investments/payout-schedule/")
        request.tenant = self.tenant
        serializer = InvestPayoutScheduleSerializer(
            data={
                "payout_date": date(2026, 6, 1),
                "amount": "5000.00",
                "currency": "USD",
                "is_paid": False,
                "payment_amount": "0",
                "comment": "Q2",
                "company": co.id,
            },
            context={"request": request},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        obj = serializer.save(tenant=self.tenant, created_by=self.user)
        self.assertIsNone(obj.company_id)


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
        self.assertFalse(obj.confirmed)
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


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class InvestmentFormConfigApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="FormCfg", subdomain="formcfg", is_active=True)
        self.host = "formcfg.example.com"
        self.user = User.objects.create_user(username="form_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)
        self.client.force_authenticate(self.user)
        InvestmentFormConfig.objects.create(
            tenant=self.tenant,
            uses_companies=False,
            allowed_return_types=["дивиденды", "проценты"],
        )

    def test_get_form_config_returns_saved_values(self):
        res = self.client.get("/api/investments/form-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["uses_companies"])
        self.assertEqual(set(res.data["allowed_return_types"]), {"дивиденды", "проценты"})

    def test_put_updates_form_config(self):
        all_types = [c[0] for c in InvestReturn.ReturnType.choices]
        res = self.client.put(
            "/api/investments/form-config/",
            {"uses_companies": True, "allowed_return_types": all_types},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["uses_companies"])
        cfg = InvestmentFormConfig.objects.get(tenant=self.tenant)
        self.assertTrue(cfg.uses_companies)

    def test_create_company_rejected_when_disabled(self):
        res = self.client.post(
            "/api/investments/companies/",
            {"name": "NewCo", "comment": ""},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentApprovalFlowTests(APITestCase):
    def setUp(self):
        self._p_allow_billing = patch(
            "apps.modules.investments.serializers.is_accrual_month_allowed",
            return_value=True,
        )
        self._p_allow_billing.start()
        self.addCleanup(self._p_allow_billing.stop)
        self.tenant = Tenant.objects.create(name="InvestFlow", subdomain="investflow", is_active=True)
        self.host = "investflow.example.com"
        self.admin = User.objects.create_user(username="inv_admin", password="x")
        self.approver1 = User.objects.create_user(
            username="inv_appr_1",
            password="x",
            full_name="Первый Согласующий",
            telegram_chat_id=555001,
            telegram_from_id=777001,
        )
        self.approver2 = User.objects.create_user(
            username="inv_appr_2",
            password="x",
            full_name="Второй Подтверждающий",
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
            "return_type": None,
            "recipient": None,
            "is_enabled": True,
            "steps": [
                {
                    "step": 1,
                    "step_type": InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                    "is_enabled": True,
                    "approver_user_ids": [self.approver1.id],
                },
                {
                    "step": 2,
                    "step_type": InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    "is_enabled": True,
                    "payment_chat_id": 666000,
                    "approver_user_ids": [self.approver2.id],
                },
            ],
        }
        response = self.client.put("/api/investments/approval-config/", cfg_payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)

        cbu_patcher = patch(
            "apps.modules.investments.serializers.fetch_cbu_usd_uzs_rate",
            return_value=Decimal("10000"),
        )
        cbu_patcher.start()
        self.addCleanup(cbu_patcher.stop)

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_create_return_creates_approvals_and_dispatches_first_step(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 101}
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
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
        self.assertEqual(created.sum_uzs, Decimal("12000000.00"))
        self.assertEqual(created.cbu_usd_uzs_rate, Decimal("10000"))
        self.assertEqual(created.approvals.count(), 2)
        self.assertEqual(bridge_mock.call_count, 1)
        payload = bridge_mock.call_args.kwargs["payload"]
        self.assertIn("📅 Месяц:", payload["text"])
        self.assertIn("InvestFlow", payload["text"])
        self.assertIn("1 200.00", payload["text"])
        self.assertIn("Выплата №", payload["text"])
        self.assertIn("🔍 Проверка выплаты", payload["text"])
        self.assertIn("Курс CBU", payload["text"])
        self.assertIn("Auto approval", payload["text"])
        self.assertIn("Ожидается подтверждение от", payload["text"])
        self.assertIn("Первый Согласующий", payload["text"])
        self.assertTrue(payload["text"].strip().startswith("<b>"))
        self.assertEqual(payload["buttons"][0][0]["label"], "✅ Проверено")

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_callback_enforces_authorization_and_final_confirmation(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 202}
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "900.00",
                "currency": "USD",
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
                "event": "interaction",
                "payload": f"inv_{first_step.id}:a",
                "user_id": str(self.intruder.telegram_from_id),
                "recipient_id": str(self.intruder.telegram_chat_id),
                "message_id": first_step.gateway_message_id or 202,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(bad_res.status_code, 400)

        ok_first = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "event": "interaction",
                "payload": f"inv_{first_step.id}:a",
                "user_id": str(self.approver1.telegram_from_id),
                "recipient_id": str(self.approver1.telegram_chat_id),
                "message_id": first_step.gateway_message_id or 202,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(ok_first.status_code, 200)
        first_step.refresh_from_db()
        self.assertEqual(first_step.decision, "approved")
        stripped = [
            c.kwargs["payload"]
            for c in bridge_mock.call_args_list
            if c.kwargs.get("payload", {}).get("buttons") == []
        ]
        self.assertGreaterEqual(len(stripped), 1)

        not_active = self.client.post(
            f"/api/investments/approvals/{first_step.id}/decision/",
            {"decision": "approved"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertIn(not_active.status_code, (400, 409))

        second_step.refresh_from_db()
        self.assertIsNotNone(second_step.gateway_message_id)
        self.assertEqual(second_step.approver_recipient_id, 666000)
        ok_second = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "event": "interaction",
                "payload": f"inv_{second_step.id}:a",
                "user_id": str(self.approver2.telegram_from_id),
                "recipient_id": "666000",
                "message_id": second_step.gateway_message_id,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(ok_second.status_code, 200)
        inv_return.refresh_from_db()
        self.assertTrue(inv_return.confirmed)

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_reject_keeps_return_unconfirmed(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 404}
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "500.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        inv_return = InvestReturn.objects.get(id=response.data["id"])
        first_step = inv_return.approvals.get(step=1)
        reject_res = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "event": "interaction",
                "payload": f"inv_{first_step.id}:r",
                "user_id": str(self.approver1.telegram_from_id),
                "recipient_id": str(self.approver1.telegram_chat_id),
                "message_id": first_step.gateway_message_id or 404,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(reject_res.status_code, 200)
        inv_return.refresh_from_db()
        self.assertFalse(inv_return.confirmed)
        second_step = inv_return.approvals.get(step=2)
        second_step.refresh_from_db()
        self.assertEqual(second_step.decision, InvestmentReturnApproval.DECISION_REJECTED)
        self.assertEqual(second_step.decision_comment, INVESTMENT_APPROVAL_CASCADE_REJECTION_COMMENT)

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_payment_step_uses_payment_buttons_and_chat_id(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 505}
        create_res = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "750.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(create_res.status_code, 201)
        inv_return = InvestReturn.objects.get(id=create_res.data["id"])
        first_step = inv_return.approvals.get(step=1)
        first_ok = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "event": "interaction",
                "payload": f"inv_{first_step.id}:a",
                "user_id": str(self.approver1.telegram_from_id),
                "recipient_id": str(self.approver1.telegram_chat_id),
                "message_id": first_step.gateway_message_id or 505,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(first_ok.status_code, 200)
        payload = bridge_mock.call_args.kwargs["payload"]
        self.assertEqual(payload["recipient_id"], "666000")
        self.assertEqual(payload["buttons"][0][0]["label"], "✅ Подтвердить")
        self.assertIn("750.00", payload["text"])
        self.assertIn("💰 Подтверждение получения", payload["text"])
        self.assertIn("Ожидается подтверждение от", payload["text"])
        self.assertIn("Второй Подтверждающий", payload["text"])

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_duplicate_webhook_callback_strips_inline_buttons(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 909}
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "100.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        inv_return = InvestReturn.objects.get(id=response.data["id"])
        first_step = inv_return.approvals.get(step=1)
        body = {
            "event": "interaction",
            "payload": f"inv_{first_step.id}:a",
            "user_id": str(self.approver1.telegram_from_id),
            "recipient_id": str(self.approver1.telegram_chat_id),
            "message_id": first_step.gateway_message_id or 909,
            "platform": "telegram",
        }
        self.assertEqual(
            self.client.post("/api/investments/approvals/webhook/", body, format="json", HTTP_HOST=self.host).status_code,
            200,
        )
        dup = self.client.post("/api/investments/approvals/webhook/", body, format="json", HTTP_HOST=self.host)
        self.assertEqual(dup.status_code, 409)
        last_payload = bridge_mock.call_args.kwargs["payload"]
        self.assertEqual(last_payload.get("buttons"), [])
        self.assertIn("message_id", last_payload)

    def test_get_approval_config_rejects_invalid_return_type_query(self):
        res = self.client.get("/api/investments/approval-config/?return_type=invalid_type", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)

    def test_get_approval_config_rejects_invalid_recipient_query(self):
        res = self.client.get("/api/investments/approval-config/?recipient=invalid", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_uses_return_type_specific_config_when_present(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 303}
        self.client.put(
            "/api/investments/approval-config/",
            {
                "return_type": None,
                "recipient": None,
                "is_enabled": True,
                "steps": [
                    {
                        "step": 1,
                        "step_type": InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                        "is_enabled": True,
                        "approver_user_ids": [self.approver1.id],
                    },
                ],
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.client.put(
            "/api/investments/approval-config/",
            {
                "return_type": "проценты",
                "recipient": None,
                "is_enabled": True,
                "steps": [
                    {
                        "step": 1,
                        "step_type": InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                        "is_enabled": True,
                        "approver_user_ids": [self.approver2.id],
                    },
                ],
            },
            format="json",
            HTTP_HOST=self.host,
        )
        div_res = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "10.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(div_res.status_code, 201, div_res.data)
        div_payload = bridge_mock.call_args.kwargs["payload"]
        self.assertEqual(div_payload["recipient_id"], str(self.approver1.telegram_chat_id))
        bridge_mock.reset_mock()
        bridge_mock.return_value = {"message_id": 304}
        pct_res = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "11.00",
                "currency": "USD",
                "type": "проценты",
                "recipient": "партнер",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(pct_res.status_code, 201, pct_res.data)
        pct_payload = bridge_mock.call_args.kwargs["payload"]
        self.assertEqual(pct_payload["recipient_id"], str(self.approver2.telegram_chat_id))

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_notification_step_dispatches_without_buttons_and_auto_approves(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 801}
        put_res = self.client.put(
            "/api/investments/approval-config/",
            {
                "return_type": None,
                "recipient": None,
                "is_enabled": True,
                "steps": [
                    {
                        "step": 1,
                        "step_type": InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION,
                        "is_enabled": True,
                        "payment_chat_id": 888001,
                        "approver_user_ids": [],
                    },
                    {
                        "step": 2,
                        "step_type": InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                        "is_enabled": True,
                        "approver_user_ids": [self.approver1.id],
                    },
                ],
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(put_res.status_code, 200, put_res.data)
        response = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "42.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        inv_return = InvestReturn.objects.get(id=response.data["id"])
        notif = inv_return.approvals.get(step=1)
        serial = inv_return.approvals.get(step=2)
        self.assertEqual(notif.decision, InvestmentReturnApproval.DECISION_APPROVED)
        self.assertEqual(serial.decision, InvestmentReturnApproval.DECISION_PENDING)
        calls = [c.kwargs["payload"] for c in bridge_mock.call_args_list]
        notify_sends = [p for p in calls if p.get("recipient_id") == "888001" and p.get("buttons") == []]
        serial_sends = [
            p
            for p in calls
            if p.get("recipient_id") == str(self.approver1.telegram_chat_id) and p.get("buttons")
        ]
        self.assertTrue(notify_sends, "ожидался send в chat notification без кнопок")
        self.assertIn("Уведомление", notify_sends[0]["text"])
        self.assertTrue(serial_sends, "ожидался send serial с кнопками")
        self.assertLess(calls.index(notify_sends[0]), calls.index(serial_sends[0]))

    @patch("apps.modules.investments.approval_services.post_messaging_gateway")
    def test_zz_recipient_specific_confirmation_chat_overrides_type_default(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 701}

        def steps_for_confirmation(chat_id: int):
            return [
                {
                    "step": 1,
                    "step_type": InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                    "is_enabled": True,
                    "approver_user_ids": [self.approver1.id],
                },
                {
                    "step": 2,
                    "step_type": InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    "is_enabled": True,
                    "payment_chat_id": chat_id,
                    "approver_user_ids": [self.approver2.id],
                },
            ]

        r_default = self.client.put(
            "/api/investments/approval-config/",
            {
                "return_type": "дивиденды",
                "recipient": None,
                "is_enabled": True,
                "steps": steps_for_confirmation(111111),
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(r_default.status_code, 200, r_default.data)
        r_partner = self.client.put(
            "/api/investments/approval-config/",
            {
                "return_type": "дивиденды",
                "recipient": "партнер",
                "is_enabled": True,
                "steps": steps_for_confirmation(222222),
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(r_partner.status_code, 200, r_partner.data)

        create_p = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "50.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "партнер",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(create_p.status_code, 201, create_p.data)
        ir_p = InvestReturn.objects.get(id=create_p.data["id"])
        first_p = ir_p.approvals.get(step=1)
        self.assertEqual(
            self.client.post(
                "/api/investments/approvals/webhook/",
                {
                    "event": "interaction",
                    "payload": f"inv_{first_p.id}:a",
                    "user_id": str(self.approver1.telegram_from_id),
                    "recipient_id": str(self.approver1.telegram_chat_id),
                    "message_id": first_p.gateway_message_id or 701,
                    "platform": "telegram",
                },
                format="json",
                HTTP_HOST=self.host,
            ).status_code,
            200,
        )
        payload_partner = bridge_mock.call_args.kwargs["payload"]
        self.assertEqual(payload_partner["recipient_id"], "222222")

        bridge_mock.reset_mock()
        bridge_mock.return_value = {"message_id": 702}
        create_i = self.client.post(
            "/api/investments/returns/",
            {
                "date": "2026-04-29",
                "billing_date": "2026-04-01",
                "sum": "51.00",
                "currency": "USD",
                "type": "дивиденды",
                "recipient": "инвестор",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(create_i.status_code, 201, create_i.data)
        ir_i = InvestReturn.objects.get(id=create_i.data["id"])
        first_i = ir_i.approvals.get(step=1)
        self.assertEqual(
            self.client.post(
                "/api/investments/approvals/webhook/",
                {
                    "event": "interaction",
                    "payload": f"inv_{first_i.id}:a",
                    "user_id": str(self.approver1.telegram_from_id),
                    "recipient_id": str(self.approver1.telegram_chat_id),
                    "message_id": first_i.gateway_message_id or 702,
                    "platform": "telegram",
                },
                format="json",
                HTTP_HOST=self.host,
            ).status_code,
            200,
        )
        payload_investor = bridge_mock.call_args.kwargs["payload"]
        self.assertEqual(payload_investor["recipient_id"], "111111")


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class InvestmentProjectApprovalFlowTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="ProjInvFlow", subdomain="projinvflow", is_active=True)
        self.host = "projinvflow.example.com"
        self.admin = User.objects.create_user(username="pi_admin", password="x")
        self.approver1 = User.objects.create_user(
            username="pi_appr_1",
            password="x",
            telegram_chat_id=155001,
            telegram_from_id=177001,
        )
        self.approver2 = User.objects.create_user(
            username="pi_appr_2",
            password="x",
            telegram_chat_id=155002,
            telegram_from_id=177002,
        )
        for user in (self.admin, self.approver1, self.approver2):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver1, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver2, role=TenantUserRole.ROLE_DIRECTOR)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)

        self.client.force_authenticate(self.admin)
        cfg_payload = {
            "is_enabled": True,
            "steps": [
                {
                    "step": 1,
                    "step_type": InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
                    "is_enabled": True,
                    "approver_user_ids": [self.approver1.id],
                },
                {
                    "step": 2,
                    "step_type": InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
                    "is_enabled": True,
                    "payment_chat_id": 166000,
                    "approver_user_ids": [self.approver2.id],
                },
            ],
        }
        response = self.client.put(
            "/api/investments/project-approval-config/", cfg_payload, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(response.status_code, 200)

    @patch("apps.modules.investments.project_investment_approval_services.post_messaging_gateway")
    def test_create_placement_creates_approvals_and_telegram_card(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 501}
        response = self.client.post(
            "/api/investments/project-investments/",
            {
                "date": "2026-04-15",
                "amount": "250000.00",
                "currency": "USD",
                "comment": "Seed round",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        created = ProjectInvestment.objects.get(id=response.data["id"])
        self.assertFalse(created.confirmed)
        self.assertEqual(created.approvals.count(), 2)
        self.assertEqual(bridge_mock.call_count, 1)
        payload = bridge_mock.call_args.kwargs["payload"]
        self.assertIn("Заявка на вложение №", payload["text"])
        self.assertIn("ProjInvFlow", payload["text"])
        self.assertIn("250 000.00", payload["text"])
        self.assertIn("Проверка заявки на вложение", payload["text"])
        self.assertIn("Seed round", payload["text"])
        self.assertTrue(payload["text"].strip().startswith("<b>"))
        self.assertEqual(payload["buttons"][0][0]["label"], "✅ Проверено")

    @patch("apps.modules.investments.project_investment_approval_services.post_messaging_gateway")
    def test_webhook_invp_prefix_sets_confirmed(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 502}
        response = self.client.post(
            "/api/investments/project-investments/",
            {
                "date": "2026-05-01",
                "amount": "10000.00",
                "currency": "USD",
                "comment": "",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        pi = ProjectInvestment.objects.get(id=response.data["id"])
        first_step = pi.approvals.get(step=1)
        second_step = pi.approvals.get(step=2)
        ok_first = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "event": "interaction",
                "payload": f"invp_{first_step.id}:a",
                "user_id": str(self.approver1.telegram_from_id),
                "recipient_id": str(self.approver1.telegram_chat_id),
                "message_id": first_step.gateway_message_id or 502,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(ok_first.status_code, 200)
        second_step.refresh_from_db()
        ok_second = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "event": "interaction",
                "payload": f"invp_{second_step.id}:a",
                "user_id": str(self.approver2.telegram_from_id),
                "recipient_id": "166000",
                "message_id": second_step.gateway_message_id,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(ok_second.status_code, 200)
        pi.refresh_from_db()
        self.assertTrue(pi.confirmed)
        self.assertEqual(
            ProjectInvestmentApproval.objects.filter(project_investment=pi, decision="approved").count(), 2
        )

    @patch("apps.modules.investments.project_investment_approval_services.post_messaging_gateway")
    def test_reject_on_first_step_cascades_all_pending(self, bridge_mock):
        bridge_mock.return_value = {"message_id": 503}
        response = self.client.post(
            "/api/investments/project-investments/",
            {
                "date": "2026-05-01",
                "amount": "10000.00",
                "currency": "USD",
                "comment": "",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(response.status_code, 201)
        pi = ProjectInvestment.objects.get(id=response.data["id"])
        first_step = pi.approvals.get(step=1)
        second_step = pi.approvals.get(step=2)
        self.assertEqual(second_step.decision, ProjectInvestmentApproval.DECISION_PENDING)
        reject = self.client.post(
            "/api/investments/approvals/webhook/",
            {
                "event": "interaction",
                "payload": f"invp_{first_step.id}:r",
                "user_id": str(self.approver1.telegram_from_id),
                "recipient_id": str(self.approver1.telegram_chat_id),
                "message_id": first_step.gateway_message_id or 503,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(reject.status_code, 200)
        second_step.refresh_from_db()
        self.assertEqual(second_step.decision, ProjectInvestmentApproval.DECISION_REJECTED)
        self.assertEqual(second_step.decision_comment, INVESTMENT_APPROVAL_CASCADE_REJECTION_COMMENT)
        pi.refresh_from_db()
        self.assertFalse(pi.confirmed)
        self.assertFalse(
            ProjectInvestmentApproval.objects.filter(
                project_investment=pi, decision=ProjectInvestmentApproval.DECISION_PENDING
            ).exists()
        )


class BillingMonthRulesTests(SimpleTestCase):
    @patch("apps.modules.investments.billing_month_rules.tashkent_today", return_value=date(2026, 5, 10))
    def test_three_calendar_months_allowed_before_day_21(self, _mock):
        from apps.modules.investments.billing_month_rules import allowed_accrual_month_starts

        self.assertEqual(len(allowed_accrual_month_starts()), 3)

    @patch("apps.modules.investments.billing_month_rules.tashkent_today", return_value=date(2026, 5, 21))
    def test_two_calendar_months_allowed_from_day_21(self, _mock):
        from apps.modules.investments.billing_month_rules import allowed_accrual_month_starts

        self.assertEqual(len(allowed_accrual_month_starts()), 2)


class InvestReturnPnLBillingMonthTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PnLBilling", subdomain="pnlbilling", is_active=True)
        TenantReportSettings.objects.create(
            tenant=self.tenant,
            pnl_source=TenantReportSettings.PNL_SOURCE_BACKEND,
            pnl_config=full_backend_pnl_config(start_month="2026-02"),
        )
        self.user = User.objects.create_user(username="pnl_ir_u", password="x")

    def test_operational_line_uses_billing_month_as_report_date(self):
        ir = InvestReturn.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            date=date(2026, 5, 10),
            billing_date=date(2026, 3, 1),
            sum=Decimal("100"),
            sum_uzs=Decimal("1000000"),
            currency="USD",
            cbu_usd_uzs_rate=Decimal("10000"),
            type="дивиденды",
            recipient="инвестор",
            confirmed=True,
            comment="",
        )
        payload = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        rows = payload["operational_expenses"]
        match = next((r for r in rows if r["id"] == str(ir.id)), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["date"], "2026-03-01")

    def test_excluded_when_billing_month_before_config_start(self):
        ir = InvestReturn.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            date=date(2026, 6, 1),
            billing_date=date(2026, 1, 1),
            sum=Decimal("50"),
            sum_uzs=Decimal("500000"),
            currency="USD",
            cbu_usd_uzs_rate=Decimal("10000"),
            type="дивиденды",
            recipient="инвестор",
            confirmed=True,
            comment="",
        )
        payload = build_pnl_payload_from_db(tenant=self.tenant, query_params={})
        ids = {r["id"] for r in payload["operational_expenses"]}
        self.assertNotIn(str(ir.id), ids)
