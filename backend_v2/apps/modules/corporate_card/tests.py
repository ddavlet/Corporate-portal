from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.corporate_card.serializers import _tashkent_date_from_datetime
from apps.modules.wallets.resolution import get_or_create_corporate_wallet
from apps.tenants.models import TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.requests.models import Request, RequestApprovalConfig, RequestApprovalPaymentTypeConfig


User = get_user_model()


class CorporateCardSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="u", password="x")

    def test_can_create_card_expense(self):
        dt = timezone.now()
        w = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        obj = CardExpense.objects.create(
            tenant=self.tenant,
            title="Taxi",
            amount=5,
            currency="UZS",
            wallet=w,
            expense_at=dt,
            note="",
            payload={},
            created_by=self.user,
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(CardExpense.objects.filter(tenant=self.tenant).count(), 1)

    def test_can_create_card_revenue(self):
        dt = timezone.now()
        w = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        obj = CardRevenue.objects.create(
            tenant=self.tenant,
            external_id="rev-1",
            confirmed=True,
            operation="Refund",
            currency="UZS",
            total_sum=7,
            wallet=w,
            revenue_at=dt,
            payload={},
            created_by=self.user,
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(CardRevenue.objects.filter(tenant=self.tenant).count(), 1)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class CorporateCardExpenseRequestRequiredApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Corp", subdomain="corp", is_active=True)
        self.admin = User.objects.create_user(username="card_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="corporate_card", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        self.appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        self.pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=self.appr_cfg,
            payment_type=Request.PAYMENT_TYPE_CARD,
            is_enabled=True,
        )

    def _headers(self):
        token = str(RefreshToken.for_user(self.admin).access_token)
        return {
            "HTTP_HOST": "corp.example.com",
            "HTTP_AUTHORIZATION": f"Bearer {token}",
        }

    def test_request_highlight_contract_scenarios(self):
        dt = timezone.now()
        required_missing = CardExpense.objects.create(
            tenant=self.tenant,
            title="Card required missing",
            amount=10,
            currency="UZS",
            wallet=self.wallet,
            expense_at=dt,
            note="",
            payload={},
            created_by=self.admin,
        )
        required_paid = CardExpense.objects.create(
            tenant=self.tenant,
            title="Card required paid",
            amount=20,
            currency="UZS",
            wallet=self.wallet,
            expense_at=dt,
            note="",
            payload={},
            created_by=self.admin,
        )
        optional_missing = CardExpense.objects.create(
            tenant=self.tenant,
            title="Card optional",
            amount=30,
            currency="UZS",
            wallet=self.wallet,
            expense_at=dt,
            note="",
            payload={"category": "ops"},
            created_by=self.admin,
        )
        self.pt_cfg.request_not_required_rules = [{"field": "category", "operator": "eq", "value": "ops"}]
        self.pt_cfg.save(update_fields=["request_not_required_rules"])
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Card paid request",
            amount="20.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD,
            urgency=Request.URGENCY_NORMAL,
            billing_date=dt.date(),
            status=Request.STATUS_PAYED,
            expense_ref_id=required_paid.id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )

        res = self.client.get("/api/corporate-card/expenses/", **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        by_id = {row["id"]: row for row in rows}
        self.assertTrue(by_id[required_missing.id]["request_required"])
        self.assertFalse(by_id[required_missing.id]["has_paid_request"])
        self.assertTrue(by_id[required_paid.id]["request_required"])
        self.assertTrue(by_id[required_paid.id]["has_paid_request"])
        self.assertFalse(by_id[optional_missing.id]["request_required"])
        self.assertFalse(by_id[optional_missing.id]["has_paid_request"])

    def test_card_revenue_api_dual_read_legacy_payload(self):
        dt = timezone.now()
        CardRevenue.objects.create(
            tenant=self.tenant,
            external_id="legacy-rev",
            currency="UZS",
            total_sum=100,
            wallet=self.wallet,
            revenue_at=dt,
            payload={
                "title": "Legacy operation title",
                "note": "Legacy comment",
                "direction": "in",
                "organization": "Legacy Org",
                "source_year": dt.year,
            },
            created_by=self.admin,
        )
        res = self.client.get("/api/corporate-card/revenues/", **self._headers())
        self.assertEqual(res.status_code, 200, res.content)
        payload = res.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        row = next(item for item in rows if item["external_id"] == "legacy-rev")
        self.assertEqual(row["operation"], "Legacy operation title")
        self.assertEqual(row["comment"], "Legacy comment")
        self.assertEqual(row["direction"], "in")
        self.assertEqual(row["organization"], "Legacy Org")
        self.assertEqual(row["source_year"], dt.year)
        self.assertEqual(row["revenue_date"], _tashkent_date_from_datetime(dt).isoformat())
        self.assertNotIn("amount", row)
        self.assertNotIn("note", row)
        self.assertNotIn("title", row)

    def test_card_revenue_model_has_no_duplicate_columns(self):
        field_names = {f.name for f in CardRevenue._meta.get_fields()}
        for removed in (
            "title",
            "amount",
            "note",
            "revenue_date",
            "source_year",
            "direction",
            "organization",
            "unit",
            "employee",
            "cash_type",
            "account",
        ):
            self.assertNotIn(removed, field_names, msg=f"duplicate column {removed} should be dropped")

