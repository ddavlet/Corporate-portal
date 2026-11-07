from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.dividend_payouts.fixtures import FOUNDER_PURPOSE, PARTNER_PURPOSE, DividendPayoutFixtures
from apps.modules.dividend_payouts.models import DividendPayoutLink, DividendPayoutRule
from apps.modules.investments.models import InvestmentFormConfig, InvestReturn
from apps.tenants.models import Tenant, TenantMembership, TenantUserRole

RULES_URL = "/api/dividend-payouts/rules/"
OPTIONS_URL = "/api/dividend-payouts/options/"
User = get_user_model()


def detail_url(rule_id: int) -> str:
    return f"{RULES_URL}{rule_id}/"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class RulesApiTests(DividendPayoutFixtures, APITestCase):
    def setUp(self):
        self.make_fixtures()
        self.other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        self.client.force_authenticate(self.admin)

    def _post(self, payload):
        return self.client.post(RULES_URL, payload, format="json", HTTP_HOST=self.host)

    def test_list_returns_only_own_rules(self):
        own = self.make_rule()
        self.make_rule(tenant=self.other)
        res = self.client.get(RULES_URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.json(),
            [
                {
                    "id": own.id,
                    "payment_purpose": FOUNDER_PURPOSE,
                    "return_type": InvestReturn.ReturnType.PRINCIPAL,
                    "recipient": InvestReturn.Recipient.INVESTOR,
                    "is_active": True,
                }
            ],
        )

    def test_create_strips_purpose(self):
        res = self._post(
            {
                "payment_purpose": f"  {PARTNER_PURPOSE}  ",
                "return_type": InvestReturn.ReturnType.DIVIDEND,
                "recipient": InvestReturn.Recipient.PARTNER,
            }
        )
        self.assertEqual(res.status_code, 201, res.content)
        rule = DividendPayoutRule.objects.get(pk=res.json()["id"])
        self.assertEqual(rule.tenant_id, self.tenant.id)
        self.assertEqual(rule.payment_purpose, PARTNER_PURPOSE)
        self.assertEqual(rule.return_type, InvestReturn.ReturnType.DIVIDEND)
        self.assertEqual(rule.recipient, InvestReturn.Recipient.PARTNER)
        self.assertTrue(rule.is_active)

    def test_create_rejects_case_insensitive_duplicate(self):
        self.make_rule()
        res = self._post(
            {
                "payment_purpose": " ДИВИДЕНДЫ учредителю",
                "return_type": InvestReturn.ReturnType.PRINCIPAL,
                "recipient": InvestReturn.Recipient.INVESTOR,
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("payment_purpose", res.json())
        self.assertEqual(DividendPayoutRule.objects.filter(tenant=self.tenant).count(), 1)

    def test_same_purpose_allowed_in_other_tenant(self):
        self.make_rule(tenant=self.other)
        res = self._post(
            {
                "payment_purpose": FOUNDER_PURPOSE,
                "return_type": InvestReturn.ReturnType.PRINCIPAL,
                "recipient": InvestReturn.Recipient.INVESTOR,
            }
        )
        self.assertEqual(res.status_code, 201, res.content)

    def test_create_rejects_blank_purpose(self):
        res = self._post(
            {
                "payment_purpose": "   ",
                "return_type": InvestReturn.ReturnType.PRINCIPAL,
                "recipient": InvestReturn.Recipient.INVESTOR,
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("payment_purpose", res.json())

    def test_create_rejects_disabled_return_type(self):
        InvestmentFormConfig.objects.create(tenant=self.tenant, allowed_return_types=[InvestReturn.ReturnType.DIVIDEND])
        res = self._post(
            {
                "payment_purpose": FOUNDER_PURPOSE,
                "return_type": InvestReturn.ReturnType.PRINCIPAL,
                "recipient": InvestReturn.Recipient.INVESTOR,
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("return_type", res.json())
        self.assertFalse(DividendPayoutRule.objects.exists())

    def test_create_rejects_unknown_choice(self):
        res = self._post({"payment_purpose": FOUNDER_PURPOSE, "return_type": "bonus", "recipient": "инвестор"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("return_type", res.json())

    def test_patch_updates_fields(self):
        rule = self.make_rule()
        res = self.client.patch(
            detail_url(rule.id),
            {"is_active": False, "recipient": InvestReturn.Recipient.PARTNER},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertEqual(rule.recipient, InvestReturn.Recipient.PARTNER)
        self.assertEqual(res.json()["is_active"], False)

    def test_patch_same_purpose_other_case_is_allowed(self):
        rule = self.make_rule()
        res = self.client.patch(
            detail_url(rule.id), {"payment_purpose": "дивиденды учредителю"}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 200, res.content)

    def test_patch_rejects_duplicate_of_other_rule(self):
        self.make_rule()
        second = self.make_rule(purpose=PARTNER_PURPOSE)
        res = self.client.patch(
            detail_url(second.id), {"payment_purpose": FOUNDER_PURPOSE.upper()}, format="json", HTTP_HOST=self.host
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("payment_purpose", res.json())

    def test_patch_toggle_allowed_when_type_later_disabled(self):
        rule = self.make_rule()
        InvestmentFormConfig.objects.create(tenant=self.tenant, allowed_return_types=[InvestReturn.ReturnType.DIVIDEND])
        res = self.client.patch(detail_url(rule.id), {"is_active": False}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)

    def test_patch_other_tenant_rule_is_404(self):
        foreign = self.make_rule(tenant=self.other)
        res = self.client.patch(detail_url(foreign.id), {"is_active": False}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 404)
        foreign.refresh_from_db()
        self.assertTrue(foreign.is_active)

    def test_delete_keeps_link_history(self):
        rule = self.make_rule()
        req = self.make_request()
        link = DividendPayoutLink.objects.create(
            request=req, rule=rule, status=DividendPayoutLink.Status.FAILED, error="x"
        )
        res = self.client.delete(detail_url(rule.id), HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 204)
        self.assertFalse(DividendPayoutRule.objects.filter(pk=rule.id).exists())
        link.refresh_from_db()
        self.assertIsNone(link.rule_id)

    def test_delete_other_tenant_rule_is_404(self):
        foreign = self.make_rule(tenant=self.other)
        res = self.client.delete(detail_url(foreign.id), HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 404)
        self.assertTrue(DividendPayoutRule.objects.filter(pk=foreign.id).exists())

    def test_options(self):
        InvestmentFormConfig.objects.create(
            tenant=self.tenant,
            allowed_return_types=[InvestReturn.ReturnType.DIVIDEND, InvestReturn.ReturnType.PRINCIPAL],
        )
        self.make_purpose(name=PARTNER_PURPOSE)
        self.make_purpose(name=FOUNDER_PURPOSE)
        self.make_purpose(name=FOUNDER_PURPOSE, payment_type="Наличные")
        self.make_purpose(name="Старое назначение", is_active=False)
        self.make_purpose(tenant=self.other, name="Чужое назначение")

        res = self.client.get(OPTIONS_URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(
            data["return_types"],
            [
                {"value": "дивиденды", "label": "Дивиденды"},
                {"value": "тело_инвестиций", "label": "Тело инвестиций"},
            ],
        )
        self.assertEqual(
            data["recipients"],
            [{"value": "инвестор", "label": "Инвестор"}, {"value": "партнер", "label": "Партнер"}],
        )
        self.assertEqual(data["payment_purposes"], [PARTNER_PURPOSE, FOUNDER_PURPOSE])

    def test_options_without_form_config_lists_all_types(self):
        res = self.client.get(OPTIONS_URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["return_types"]), len(InvestReturn.ReturnType.choices))
        self.assertEqual(res.json()["payment_purposes"], [])

    def test_non_admin_forbidden(self):
        member = User.objects.create_user(username="dp-requester", password="x", full_name="Рядовой")
        TenantMembership.objects.create(tenant=self.tenant, user=member, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=member, role=TenantUserRole.ROLE_REQUESTER)
        self.client.force_authenticate(member)
        rule = self.make_rule()
        self.assertEqual(self.client.get(RULES_URL, HTTP_HOST=self.host).status_code, 403)
        self.assertEqual(self.client.get(OPTIONS_URL, HTTP_HOST=self.host).status_code, 403)
        res = self.client.delete(detail_url(rule.id), HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 403)
        self.assertTrue(DividendPayoutRule.objects.filter(pk=rule.id).exists())

    def test_admin_of_other_tenant_forbidden(self):
        outsider = User.objects.create_user(username="dp-outsider", password="x")
        TenantMembership.objects.create(tenant=self.other, user=outsider, is_active=True)
        TenantUserRole.objects.create(tenant=self.other, user=outsider, role=TenantUserRole.ROLE_ADMIN)
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(RULES_URL, HTTP_HOST=self.host).status_code, 403)

    def test_director_allowed(self):
        director = User.objects.create_user(username="dp-director", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=director, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=director, role=TenantUserRole.ROLE_DIRECTOR)
        self.client.force_authenticate(director)
        self.assertEqual(self.client.get(RULES_URL, HTTP_HOST=self.host).status_code, 200)
