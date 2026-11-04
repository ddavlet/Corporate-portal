from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.modules.requests.models import (
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    Approval,
)
from apps.modules.telegram_approvals.miniapp_links import (
    bot_setup_checklist,
    default_payment_webapp_url,
    direct_link,
)
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


class DirectLinkTests(TestCase):
    def test_direct_link_uses_bot_username(self):
        for stored in ("@lemonfit2_bot", "lemonfit2_bot"):
            tenant = Tenant(name="x", subdomain="x", telegram_bot_username=stored)
            self.assertEqual(direct_link(tenant, "payment"), "https://t.me/lemonfit2_bot/payment")
            self.assertEqual(default_payment_webapp_url(tenant), "https://t.me/lemonfit2_bot/payment")

    def test_direct_link_empty_without_username(self):
        tenant = Tenant(name="x", subdomain="x", telegram_bot_username="")
        self.assertEqual(direct_link(tenant, "payment"), "")
        self.assertEqual(default_payment_webapp_url(tenant), "")


class ChecklistTests(TestCase):
    def _tenant(self):
        tenant = Tenant.objects.create(
            name="Acme", subdomain="acme", is_active=True, telegram_bot_username="@acme_bot"
        )
        tenant.set_telegram_bot_token("123456:abcdef")
        tenant.save(update_fields=["telegram_bot_token_enc"])
        return tenant

    @override_settings(BASE_DOMAIN="kolberg.uz")
    def test_checklist_values(self):
        self.assertEqual(
            bot_setup_checklist(self._tenant()),
            {
                "bot_username": "acme_bot",
                "has_bot_token": True,
                "main_app_url": "https://acme.kolberg.uz/app/tg/",
                "launch_mode": "fullscreen",
                "direct_links": [
                    {
                        "short_name": "payment",
                        "web_app_url": "https://acme.kolberg.uz/app/tg/payment",
                        "link": "https://t.me/acme_bot/payment",
                    },
                    {
                        "short_name": "portal",
                        "web_app_url": "https://acme.kolberg.uz/app/tg/",
                        "link": "https://t.me/acme_bot/portal",
                    },
                ],
                "auto_synced": ["commands", "description", "menu_button"],
            },
        )

    @override_settings(BASE_DOMAIN="localhost")
    def test_checklist_without_base_domain_has_empty_urls(self):
        data = bot_setup_checklist(self._tenant())
        self.assertEqual(data["main_app_url"], "")
        self.assertEqual([d["web_app_url"] for d in data["direct_links"]], ["", ""])
        self.assertEqual(data["direct_links"][0]["link"], "https://t.me/acme_bot/payment")


@override_settings(
    BASE_DOMAIN="example.com",
    MESSAGING_GATEWAY_SEND_URL="https://acme.example.com/v1/messaging/send",
    N8N_INTEGRATION_TOKEN="test-n8n-token",
    ALLOWED_HOSTS=["*"],
)
class PaymentButtonDefaultLinkTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name="Acme", subdomain="acme", is_active=True, telegram_bot_username="@acme_bot"
        )
        self.admin = User.objects.create_user(username="admin", password="x")
        self.requester = User.objects.create_user(username="req", password="x", full_name="Иван Иванов")
        self.approver = User.objects.create_user(
            username="appr", password="x", full_name="Петр Петров", telegram_chat_id=555001, telegram_from_id=777001
        )
        for user in (self.admin, self.requester, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(config=form_cfg, payment_type="Перечисление", is_enabled=True)
        self.host = "acme.example.com"

    def _create_request_with_payment_step(self, *, webapp_url):
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Перечисление", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
            payment_webapp_url=webapp_url,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        self.client.force_authenticate(self.requester)
        with patch("apps.modules.telegram_approvals.services.requests.post") as mocked_post:
            mocked_post.return_value.status_code = 200
            mocked_post.return_value.content = b'{"result":{"message_id":6001}}'
            mocked_post.return_value.json.return_value = {"result": {"message_id": 6001}}
            res = self.client.post(
                "/api/requests/",
                {
                    "title": "Payment request",
                    "description": "TEST",
                    "amount": 100,
                    "currency": "UZS",
                    "payment_type": "Перечисление",
                    "urgency": "Обычно",
                    "requester": self.requester.id,
                    "billing_date": "2026-03-31",
                },
                format="json",
                HTTP_HOST=self.host,
            )
            self.assertEqual(res.status_code, 201, res.content)
            payload = mocked_post.call_args.kwargs.get("json", {})
        return payload.get("buttons", [[{}, {}]])[0][0]

    def test_payment_button_uses_default_link_when_step_url_blank(self):
        button = self._create_request_with_payment_step(webapp_url="")
        approval = Approval.objects.get(step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(button["url"], f"https://t.me/acme_bot/payment?startapp={approval.id}")

    def test_payment_button_keeps_manual_url(self):
        button = self._create_request_with_payment_step(webapp_url="https://t.me/other_bot/custom")
        approval = Approval.objects.get(step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(button["url"], f"https://t.me/other_bot/custom?startapp={approval.id}")

    def test_payment_button_falls_back_to_callback_without_username(self):
        self.tenant.telegram_bot_username = ""
        self.tenant.save(update_fields=["telegram_bot_username"])
        button = self._create_request_with_payment_step(webapp_url="")
        self.assertNotIn("url", button)
        self.assertIn("value", button)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class BotSetupEndpointTests(APITestCase):
    def test_bot_setup_endpoint_requires_admin_and_returns_checklist(self):
        tenant = Tenant.objects.create(
            name="Acme", subdomain="acme", is_active=True, telegram_bot_username="acme_bot"
        )
        admin = User.objects.create_user(username="adm", password="x")
        member = User.objects.create_user(username="mem", password="x")
        for user, role in ((admin, TenantUserRole.ROLE_ADMIN), (member, TenantUserRole.ROLE_REQUESTER)):
            TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
            TenantUserRole.objects.create(tenant=tenant, user=user, role=role)
        url = "/api/messaging-gateway/bot-setup/"

        self.client.force_authenticate(member)
        self.assertEqual(self.client.get(url, HTTP_HOST="acme.example.com").status_code, 403)

        self.client.force_authenticate(admin)
        res = self.client.get(url, HTTP_HOST="acme.example.com")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["bot_username"], "acme_bot")
        self.assertEqual(len(res.data["direct_links"]), 2)
        self.assertEqual(res.data["direct_links"][0]["link"], "https://t.me/acme_bot/payment")
