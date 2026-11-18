from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.corporate_card.models import CardExpenseAutoRequestConfig
from apps.modules.requests.models import (
    Request,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.resolution import get_or_create_cash_wallet, get_or_create_corporate_wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class CardExpenseAutoRequestConfigApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Corp", subdomain="corp", is_active=True)
        self.admin = self._member("card_cfg_admin", TenantUserRole.ROLE_ADMIN)
        self.module = TenantModuleConfig.objects.create(
            tenant=self.tenant, module_key="corporate_card", is_enabled=True
        )
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        form_pt = RequestFormPaymentTypeConfig.objects.create(
            config=form_cfg, payment_type=Request.PAYMENT_TYPE_CARD, default_company_payer="ООО Корп"
        )
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=form_pt, name="Реклама", category="Маркетинг", is_active=True
        )
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=form_pt, name="Старое", category="", is_active=False
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Meta Ads", inn="123456789", created_by=self.admin
        )

    def _member(self, username, role):
        user = User.objects.create_user(username=username, password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def _headers(self, user=None):
        token = str(RefreshToken.for_user(user or self.admin).access_token)
        return {"HTTP_HOST": "corp.example.com", "HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _url(self, wallet_id=None):
        return f"/api/corporate-card/auto-request-configs/{wallet_id or self.wallet.pk}/"

    def _patch(self, data, *, user=None, wallet_id=None):
        return self.client.patch(self._url(wallet_id), data, format="json", **self._headers(user))

    def test_get_returns_defaults_without_row(self):
        response = self.client.get(self._url(), **self._headers())

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["wallet_id"], self.wallet.pk)
        self.assertEqual(data["currency"], "UZS")
        self.assertFalse(data["is_enabled"])
        self.assertEqual(data["payment_purpose"], "")
        self.assertIsNone(data["vendor_ref_id"])
        self.assertIsNone(data["updated_at"])
        self.assertEqual(data["options"]["payment_purposes"], [{"name": "Реклама", "category": "Маркетинг"}])
        self.assertEqual(data["options"]["vendors"], [{"id": self.vendor.pk, "name": "Meta Ads"}])
        self.assertEqual(data["options"]["default_company_payer"], "ООО Корп")
        self.assertFalse(CardExpenseAutoRequestConfig.objects.exists())

    def test_patch_creates_row_and_second_patch_updates_it(self):
        response = self._patch(
            {
                "is_enabled": True,
                "payment_purpose": " Реклама ",
                "vendor_ref_id": self.vendor.pk,
                "match_text": "META",
            }
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_enabled"])
        config = CardExpenseAutoRequestConfig.objects.get()
        self.assertEqual(config.wallet_id, self.wallet.pk)
        self.assertEqual(config.tenant_id, self.tenant.pk)
        self.assertEqual(config.payment_purpose, "Реклама")
        self.assertEqual(config.vendor_ref_id, self.vendor.pk)
        self.assertEqual(config.match_text, "META")
        self.assertEqual(config.updated_by_id, self.admin.pk)

        second = self._patch({"is_enabled": False, "vendor_ref_id": None})

        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(CardExpenseAutoRequestConfig.objects.count(), 1)
        config.refresh_from_db()
        self.assertFalse(config.is_enabled)
        self.assertIsNone(config.vendor_ref_id)
        self.assertEqual(config.payment_purpose, "Реклама")

    def test_enabling_without_purpose_is_rejected(self):
        response = self._patch({"is_enabled": True, "payment_purpose": ""})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("payment_purpose", response.json())
        self.assertFalse(CardExpenseAutoRequestConfig.objects.exists())

    def test_unknown_or_inactive_purpose_is_rejected(self):
        for purpose in ("Неизвестное", "Старое"):
            response = self._patch({"is_enabled": True, "payment_purpose": purpose})
            self.assertEqual(response.status_code, 400, response.content)
            self.assertIn("payment_purpose", response.json())
        self.assertFalse(CardExpenseAutoRequestConfig.objects.exists())

    def test_setting_with_deactivated_purpose_can_be_switched_off(self):
        # The modal always sends the stored purpose back, even if it was deactivated meanwhile.
        CardExpenseAutoRequestConfig.objects.create(
            tenant=self.tenant, wallet=self.wallet, is_enabled=True, payment_purpose="Старое"
        )

        response = self._patch({"is_enabled": False, "payment_purpose": "Старое", "match_text": ""})

        self.assertEqual(response.status_code, 200, response.content)
        config = CardExpenseAutoRequestConfig.objects.get()
        self.assertFalse(config.is_enabled)
        self.assertEqual(config.payment_purpose, "Старое")

    def test_deactivated_purpose_blocks_enabling_and_new_inactive_purpose(self):
        CardExpenseAutoRequestConfig.objects.create(
            tenant=self.tenant, wallet=self.wallet, is_enabled=False, payment_purpose="Старое"
        )

        enable = self._patch({"is_enabled": True, "payment_purpose": "Старое"})
        self.assertEqual(enable.status_code, 400, enable.content)
        self.assertIn("payment_purpose", enable.json())

        CardExpenseAutoRequestConfig.objects.update(payment_purpose="Реклама")
        change = self._patch({"is_enabled": False, "payment_purpose": "Старое"})
        self.assertEqual(change.status_code, 400, change.content)
        self.assertFalse(CardExpenseAutoRequestConfig.objects.get().is_enabled)

    def test_vendor_of_other_tenant_is_rejected(self):
        other_tenant = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        foreign_vendor = Vendor.objects.create(
            tenant=other_tenant, kind=Vendor.KIND_TRANSFER, name="Foreign", inn="987654321", created_by=self.admin
        )

        response = self._patch({"payment_purpose": "Реклама", "vendor_ref_id": foreign_vendor.pk})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("vendor_ref_id", response.json())

    def test_wallet_of_other_tenant_is_not_found(self):
        other_tenant = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        foreign_wallet = get_or_create_corporate_wallet(tenant=other_tenant, currency="UZS")

        self.assertEqual(self.client.get(self._url(foreign_wallet.pk), **self._headers()).status_code, 404)
        self.assertEqual(self._patch({"is_enabled": False}, wallet_id=foreign_wallet.pk).status_code, 404)
        self.assertFalse(CardExpenseAutoRequestConfig.objects.exists())

    def test_cash_wallet_is_not_found(self):
        cash_wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")

        self.assertEqual(self.client.get(self._url(cash_wallet.pk), **self._headers()).status_code, 404)
        self.assertEqual(self._patch({"is_enabled": False}, wallet_id=cash_wallet.pk).status_code, 404)

    def test_non_admin_roles_are_forbidden(self):
        for username, role in (
            ("card_cfg_director", TenantUserRole.ROLE_DIRECTOR),
            ("card_cfg_accountant", TenantUserRole.ROLE_ACCOUNTANT),
            ("card_cfg_cashier", TenantUserRole.ROLE_CASHIER),
        ):
            user = self._member(username, role)
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self._url(), **self._headers(user)).status_code, 403)
                self.assertEqual(self._patch({"is_enabled": False}, user=user).status_code, 403)
        self.assertFalse(CardExpenseAutoRequestConfig.objects.exists())

    def test_admin_is_forbidden_when_module_disabled(self):
        self.module.is_enabled = False
        self.module.save(update_fields=["is_enabled"])

        self.assertEqual(self.client.get(self._url(), **self._headers()).status_code, 403)
        self.assertEqual(self._patch({"is_enabled": False}).status_code, 403)

    def test_admin_get_and_patch_are_allowed(self):
        self.assertEqual(self.client.get(self._url(), **self._headers()).status_code, 200)
        self.assertEqual(self._patch({"match_text": "META"}).status_code, 200)
