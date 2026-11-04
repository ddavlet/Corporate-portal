"""Переотправка Telegram-карточек согласования вложений и выплат (как у заявок на расходы)."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.modules.investments.models import (
    CbuExchangeRate,
    InvestmentApprovalConfigStep,
    InvestmentProjectApprovalConfigStep,
    InvestmentReturnApproval,
    InvestReturn,
    ProjectInvestment,
    ProjectInvestmentApproval,
)
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


def _gateway_response(message_id):
    body = {"result": {"message_id": message_id}} if message_id is not None else {}
    resp = type("Resp", (), {"status_code": 200, "content": b"{}"})()
    resp.json = lambda: body
    return resp


@override_settings(
    BASE_DOMAIN="example.com",
    MESSAGING_GATEWAY_SEND_URL="https://resend.example.com/v1/messaging/send",
    ALLOWED_HOSTS=["*"],
)
class InvestmentApprovalResendTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="InvResend", subdomain="invresend", is_active=True)
        self.host = "invresend.example.com"
        self.admin = User.objects.create_user(username="ir_admin", password="x")
        self.approver = User.objects.create_user(
            username="ir_appr", password="x", telegram_chat_id=455001, telegram_from_id=477001
        )
        self.outsider = User.objects.create_user(username="ir_outsider", password="x")
        for user in (self.admin, self.approver, self.outsider):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.outsider, role=TenantUserRole.ROLE_INVESTOR)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="investments", is_enabled=True)
        CbuExchangeRate.objects.create(date=date(2026, 4, 15), usd_uzs_rate=Decimal("10000"))

        self.project = ProjectInvestment.objects.create(
            tenant=self.tenant,
            date=date(2026, 4, 15),
            amount=Decimal("1000.00"),
            currency="USD",
            funding_method=ProjectInvestment.FundingMethod.CASH,
            created_by=self.admin,
        )
        self.project_approval = ProjectInvestmentApproval.objects.create(
            tenant=self.tenant,
            project_investment=self.project,
            step=1,
            step_type=InvestmentProjectApprovalConfigStep.STEP_TYPE_SERIAL,
            approver_user=self.approver,
            approver_recipient_id="455001",
            approver_external_user_id=477001,
            telegram_message=self._message(4321),
        )
        self.client.force_authenticate(self.admin)

    def _message(self, message_id):
        return TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id="455001",
            external_user_id=477001,
            message_id=message_id,
            sent_at=timezone.now(),
        )

    def _resend_project(self):
        return self.client.post(
            f"/api/investments/project-approvals/{self.project_approval.id}/resend/",
            {},
            format="json",
            HTTP_HOST=self.host,
        )

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_project_investment_card_resend_keeps_message_row_and_swaps_message_id(self, mocked_post):
        mocked_post.side_effect = [_gateway_response(4321), _gateway_response(9999)]

        res = self._resend_project()

        self.assertEqual(res.status_code, 200, res.content)
        self.project_approval.refresh_from_db()
        self.assertEqual(self.project_approval.decision, ProjectInvestmentApproval.DECISION_PENDING)
        tm = self.project_approval.telegram_message
        self.assertEqual(tm.message_id, 9999)
        self.assertEqual(tm.resend_count, 1)
        self.assertEqual(mocked_post.call_count, 2)
        deact_payload = mocked_post.call_args_list[0].kwargs.get("json", {})
        send_payload = mocked_post.call_args_list[1].kwargs.get("json", {})
        self.assertEqual(deact_payload.get("buttons"), [])
        self.assertTrue(send_payload.get("buttons"))
        self.assertIn("Заявка на вложение", send_payload.get("text", ""))

        rows = self.client.get(
            f"/api/investments/project-investment-approvals/?project_investment={self.project.id}",
            HTTP_HOST=self.host,
        ).data
        self.assertEqual(rows[0]["resend_count"], 1)
        self.assertTrue(rows[0]["can_resend"])
        self.assertIsNotNone(rows[0]["resend_available_at"])

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_project_investment_second_resend_within_cooldown_is_throttled(self, mocked_post):
        mocked_post.side_effect = [_gateway_response(4321), _gateway_response(9999)]
        self.assertEqual(self._resend_project().status_code, 200)
        self.assertEqual(self._resend_project().status_code, 429)

    def test_project_investment_resend_rejected_after_limit(self):
        tm = self.project_approval.telegram_message
        tm.resend_count = 3
        tm.save(update_fields=["resend_count"])

        res = self._resend_project()

        self.assertEqual(res.status_code, 400, res.content)
        rows = self.client.get(
            f"/api/investments/project-investment-approvals/?project_investment={self.project.id}",
            HTTP_HOST=self.host,
        ).data
        self.assertFalse(rows[0]["can_resend"])

    def test_project_investment_resend_rejected_when_decided(self):
        self.project_approval.decision = ProjectInvestmentApproval.DECISION_APPROVED
        self.project_approval.save(update_fields=["decision"])
        self.assertEqual(self._resend_project().status_code, 400)

    def test_project_investment_resend_requires_manager_role(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self._resend_project().status_code, 403)

    def test_project_investment_resend_is_tenant_scoped(self):
        other = Tenant.objects.create(name="Other", subdomain="otherresend", is_active=True)
        TenantMembership.objects.create(tenant=other, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=other, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=other, module_key="investments", is_enabled=True)
        res = self.client.post(
            f"/api/investments/project-approvals/{self.project_approval.id}/resend/",
            {},
            format="json",
            HTTP_HOST="otherresend.example.com",
        )
        self.assertEqual(res.status_code, 400, res.content)
        self.project_approval.telegram_message.refresh_from_db()
        self.assertEqual(self.project_approval.telegram_message.resend_count, 0)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_invest_return_card_resend(self, mocked_post):
        mocked_post.side_effect = [_gateway_response(5321), _gateway_response(8888)]
        invest_return = InvestReturn.objects.create(
            tenant=self.tenant,
            date=date(2026, 4, 15),
            billing_date=date(2026, 4, 1),
            sum=Decimal("1200.00"),
            currency="USD",
            type=InvestReturn.ReturnType.choices[0][0],
            recipient=InvestReturn.Recipient.choices[0][0],
            created_by=self.admin,
        )
        approval = InvestmentReturnApproval.objects.create(
            tenant=self.tenant,
            invest_return=invest_return,
            step=1,
            step_type=InvestmentApprovalConfigStep.STEP_TYPE_SERIAL,
            approver_user=self.approver,
            approver_recipient_id="455001",
            approver_external_user_id=477001,
            telegram_message=self._message(5321),
        )

        res = self.client.post(
            f"/api/investments/approvals/{approval.id}/resend/", {}, format="json", HTTP_HOST=self.host
        )

        self.assertEqual(res.status_code, 200, res.content)
        approval.refresh_from_db()
        self.assertEqual(approval.telegram_message.message_id, 8888)
        self.assertEqual(approval.telegram_message.resend_count, 1)
        rows = self.client.get(
            f"/api/investments/return-approvals/?invest_return={invest_return.id}", HTTP_HOST=self.host
        ).data
        self.assertEqual(rows[0]["resend_count"], 1)
