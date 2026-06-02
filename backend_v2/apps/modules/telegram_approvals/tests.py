import json
import os
from datetime import date
from io import StringIO
from unittest.mock import patch

import requests as _real_requests

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.common.test_utils import list_results
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
)
from apps.modules.telegram_approvals.models import TelegramMessage, TenantTelegramChat
from apps.modules.telegram_approvals.services import (
    ensure_callback_identity,
    get_tenant_bot_token,
    build_approval_message,
    normalize_gateway_buttons,
    post_messaging_gateway,
)
from apps.tenants.models import Tenant, TenantIntegrationConfig, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(
    BASE_DOMAIN="example.com",
    MESSAGING_GATEWAY_SEND_URL="https://acme.example.com/v1/messaging/send",
    N8N_INTEGRATION_TOKEN="test-n8n-token",
    ALLOWED_HOSTS=["*"],
)
class TelegramApprovalsTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.requester = User.objects.create_user(
            username="req",
            password="x",
            full_name="Иван Иванов",
        )
        self.approver = User.objects.create_user(
            username="appr",
            password="x",
            full_name="Петр Петров",
            telegram_chat_id=555001,
            telegram_from_id=777001,
        )
        for user in (self.admin, self.requester, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(config=req_form_cfg, payment_type="Наличные", is_enabled=True)
        RequestFormPaymentTypeConfig.objects.create(config=req_form_cfg, payment_type="Перечисление", is_enabled=True)

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        self.host = "acme.example.com"
        self.webhook_token = "test-n8n-token"

    def _create_approval_with_message(self, message_id, **kwargs):
        """Create an Approval linked to a TelegramMessage (gateway_message_id and message_sent are now properties)."""
        recipient_id = kwargs.get("approver_recipient_id")
        external_user_id = kwargs.get("approver_external_user_id")
        tm = TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id=str(recipient_id or "999"),
            external_user_id=external_user_id,
            message_id=message_id,
            sent_at=timezone.now(),
        )
        return Approval.objects.create(
            telegram_message=tm,
            **kwargs,
        )

    def test_tenant_bot_token_is_read_from_tenant_model(self):
        """Regression: token must not be taken from TenantIntegrationConfig (no bot token there)."""
        self.tenant.set_telegram_bot_token("111222333:AAATESTBOTTOKEN")
        self.tenant.save(update_fields=["telegram_bot_token_enc"])
        TenantIntegrationConfig.objects.get_or_create(
            tenant=self.tenant, defaults={"updated_by": self.admin}
        )
        self.assertEqual(get_tenant_bot_token(self.tenant), "111222333:AAATESTBOTTOKEN")

    def test_normalize_gateway_buttons_converts_callback_data_to_value(self):
        rows = normalize_gateway_buttons(
            [[{"label": "Done", "callback_data": "task_a_1"}, {"label": "Web", "url": "https://t.me/bot"}]]
        )
        self.assertEqual(rows[0][0], {"label": "Done", "value": "task_a_1"})
        self.assertEqual(rows[0][1], {"label": "Web", "url": "https://t.me/bot"})

    def test_ensure_callback_identity_raises_on_recipient_mismatch(self):
        with self.assertRaises(ValidationError):
            ensure_callback_identity(
                callback_message_id=10,
                stored_message_id=10,
                callback_recipient_id="111",
                stored_recipient_id="222",
                callback_external_user_id=7,
                stored_external_user_id=7,
            )

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_request_create_dispatches_telegram_message_and_saves_message_id(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":9001}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 9001}}
        self.client.force_authenticate(self.requester)

        res = self.client.post(
            "/api/requests/",
            {
                "title": "Lemonfit",
                "description": "TEST",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester.id,
                "billing_date": "2026-03-31",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)

        approval = Approval.objects.get(request_id=res.data["id"], approver_user=self.approver)
        self.assertEqual(approval.gateway_message_id, 9001)
        self.assertTrue(approval.message_sent)
        self.assertIsNotNone(approval.message_sent_at)

        self.assertTrue(mocked_post.called)
        payload = mocked_post.call_args.kwargs.get("json", {})
        self.assertEqual(payload.get("action"), "send_interactive")
        self.assertEqual(payload.get("recipient_id"), "555001")
        self.assertIn("buttons", payload)
        self.assertIn("text", payload)
        self.assertIn("Иван Иванов", payload.get("text", ""))
        self.assertNotIn("• Заявитель: req", payload.get("text", ""))

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_request_create_fails_when_response_has_no_message_id(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"ok":true}'
        mocked_post.return_value.json.return_value = {"ok": True}
        self.client.force_authenticate(self.requester)

        res = self.client.post(
            "/api/requests/",
            {
                "title": "Lemonfit",
                "description": "TEST",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester.id,
                "billing_date": "2026-03-31",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("telegram", res.data)
        self.assertEqual(Request.objects.count(), 1)
        self.assertEqual(Approval.objects.count(), 1)
        approval = Approval.objects.select_related("request").get()
        self.assertIsNone(approval.gateway_message_id)
        self.assertFalse(approval.message_sent)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_gateway_http_error_is_logged_and_approval_skipped(self, mocked_post):
        err_resp = type("R", (), {})()
        err_resp.status_code = 502
        err_resp.text = "bad gateway"
        err_resp.content = b"bad gateway"
        err_resp.json = lambda: {}
        mocked_post.return_value = err_resp

        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "Lemonfit",
                "description": "TEST",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester.id,
                "billing_date": "2026-03-31",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        # Gateway failure is logged and skipped — request still created
        self.assertEqual(res.status_code, 201, res.content)
        # Only 1 call — no secondary error-webhook call
        self.assertEqual(mocked_post.call_count, 1)

    @patch("apps.modules.telegram_approvals.services.get_requests_messaging_gateway_settings")
    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_post_gateway_survives_telegram_settings_resolution_error(self, mocked_post, mocked_settings_get):
        mocked_settings_get.side_effect = RuntimeError("broken tenant integration settings")
        result = post_messaging_gateway(
            tenant=self.tenant,
            payload={"action": "send", "text": "hello"},
        )
        self.assertIsNone(result)
        self.assertEqual(mocked_post.call_count, 1)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_pending_step_deactivates_old_and_sends_new_message(self, mocked_post):
        send_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":9999}}'})()
        send_response.json = lambda: {"result": {"message_id": 9999}}
        edit_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":4321}}'})()
        edit_response.json = lambda: {"result": {"message_id": 4321}}
        mocked_post.side_effect = [edit_response, send_response]

        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Needs resend",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        approval = self._create_approval_with_message(
            message_id=4321,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        self.client.force_authenticate(self.admin)
        res = self.client.post(
            f"/api/requests/{request_row.id}/approvals/resend/",
            {},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data.get("resent"), 1)

        approval.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_CANCELED)
        self.assertEqual(approval.gateway_message_id, 4321)
        new_approval = Approval.objects.filter(request=request_row, replaced_approval=approval).get()
        self.assertEqual(new_approval.decision, Approval.DECISION_PENDING)
        self.assertTrue(new_approval.message_sent)
        self.assertEqual(new_approval.gateway_message_id, 9999)
        self.assertIsNotNone(new_approval.resend_key)
        self.assertTrue(str(new_approval.resend_key).startswith("auto:"))
        self.assertEqual(mocked_post.call_count, 2)
        first_payload = mocked_post.call_args_list[0].kwargs.get("json", {})
        second_payload = mocked_post.call_args_list[1].kwargs.get("json", {})
        self.assertEqual(first_payload.get("action"), "edit_interactive")
        self.assertEqual(first_payload.get("buttons"), [])
        self.assertEqual(second_payload.get("action"), "send_interactive")
        self.assertTrue(second_payload.get("buttons"))

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_with_same_idempotency_key_is_noop(self, mocked_post):
        send_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":9999}}'})()
        send_response.json = lambda: {"result": {"message_id": 9999}}
        edit_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":4321}}'})()
        edit_response.json = lambda: {"result": {"message_id": 4321}}
        mocked_post.side_effect = [edit_response, send_response]

        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Needs resend",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        self._create_approval_with_message(
            message_id=4321,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )
        self.client.force_authenticate(self.admin)

        payload = {"idempotency_key": "r-1"}
        res1 = self.client.post(
            f"/api/requests/{request_row.id}/approvals/resend/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res1.status_code, 200, res1.content)
        self.assertEqual(Approval.objects.filter(request=request_row, decision=Approval.DECISION_PENDING).count(), 1)

        mocked_post.reset_mock()
        res2 = self.client.post(
            f"/api/requests/{request_row.id}/approvals/resend/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        self.assertEqual(res2.data.get("resent"), 1)
        self.assertEqual(Approval.objects.filter(request=request_row, decision=Approval.DECISION_PENDING).count(), 1)
        self.assertEqual(
            Approval.objects.filter(request=request_row, resend_key="r-1", decision=Approval.DECISION_PENDING).count(),
            1,
        )

    def test_resend_fails_when_no_pending_on_current_step(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="No pending",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        self._create_approval_with_message(
            message_id=4321,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            f"/api/requests/{request_row.id}/approvals/resend/",
            {},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_works_for_approved_status_with_pending_payment(self, mocked_post):
        send_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":10001}}'})()
        send_response.json = lambda: {"result": {"message_id": 10001}}
        edit_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":7654}}'})()
        edit_response.json = lambda: {"result": {"message_id": 7654}}
        mocked_post.side_effect = [edit_response, send_response]

        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Payment pending",
            status=Request.STATUS_APPROVED,
            payment_type="Перечисление",
            billing_date=date(2026, 3, 31),
        )
        old_payment = self._create_approval_with_message(
            message_id=7654,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=2,
            step_type=Approval.STEP_TYPE_PAYMENT,
            decision=Approval.DECISION_PENDING,
        )

        self.client.force_authenticate(self.admin)
        res = self.client.post(
            f"/api/requests/{request_row.id}/approvals/resend/",
            {"idempotency_key": "payment-resend-1"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data.get("resent"), 1)

        old_payment.refresh_from_db()
        self.assertEqual(old_payment.decision, Approval.DECISION_CANCELED)
        new_payment = Approval.objects.get(request=request_row, replaced_approval=old_payment)
        self.assertEqual(new_payment.decision, Approval.DECISION_PENDING)
        self.assertEqual(new_payment.step_type, Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(new_payment.gateway_message_id, 10001)
        self.assertTrue(new_payment.message_sent)
        self.assertEqual(mocked_post.call_count, 2)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_webhook_callback_confirms_approval_with_identity_checks(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":4321}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 4321}}
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Needs approval",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        approval = self._create_approval_with_message(
            message_id=4321,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        payload = {
            "event": "interaction",
            "payload": json.dumps({"approval_id": approval.id, "decision": "approved"}),
            "user_id": "777001",
            "recipient_id": "555001",
            "message_id": 4321,
            "platform": "telegram",
        }
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        approval.refresh_from_db()
        request_row.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)
        self.assertEqual(request_row.status, Request.STATUS_APPROVED)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_request_lifecycle_records_history_telegram_message_and_callback_approves(self, mocked_post):
        """Full flow: new request → approval dispatched → history fields + TelegramMessage
        recorded → callback (using the stored identifiers) confirms the decision, and the
        TelegramMessage is not duplicated by the post-decision message edit."""
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":9100}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 9100}}

        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "Lemonfit",
                "description": "TEST",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester.id,
                "billing_date": "2026-03-31",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)

        approval = Approval.objects.get(request_id=res.data["id"], approver_user=self.approver)
        # History recorded on the approval itself.
        self.assertEqual(approval.gateway_message_id, 9100)
        self.assertTrue(approval.message_sent)
        self.assertIsNotNone(approval.message_sent_at)
        # TelegramMessage history row created and linked.
        self.assertIsNotNone(approval.telegram_message)
        tg_msg = approval.telegram_message
        self.assertEqual(tg_msg.message_id, 9100)
        self.assertEqual(tg_msg.recipient_id, approval.approver_recipient_id)
        self.assertEqual(tg_msg.external_user_id, approval.approver_external_user_id)
        self.assertEqual(tg_msg.tenant_id, self.tenant.id)
        self.assertIsNotNone(tg_msg.sent_at)
        self.assertEqual(TelegramMessage.objects.filter(tenant=self.tenant).count(), 1)

        # Simulate the gateway callback using exactly what was stored (round-trip).
        self.client.force_authenticate(None)
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            {
                "event": "interaction",
                "payload": json.dumps({"approval_id": approval.id, "decision": "approved"}),
                "user_id": str(approval.approver_external_user_id),
                "recipient_id": approval.approver_recipient_id,
                "message_id": approval.gateway_message_id,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        approval.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)
        self.assertEqual(approval.request.status, Request.STATUS_APPROVED)
        # Post-decision message edit must reuse the same TelegramMessage, not create a new one.
        self.assertEqual(approval.telegram_message_id, tg_msg.id)
        self.assertEqual(TelegramMessage.objects.filter(tenant=self.tenant).count(), 1)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_request_lifecycle_callback_rejects(self, mocked_post):
        """Reject path still records history + TelegramMessage and applies the decision."""
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":9200}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 9200}}

        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "Lemonfit",
                "description": "TEST",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester.id,
                "billing_date": "2026-03-31",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)

        approval = Approval.objects.get(request_id=res.data["id"], approver_user=self.approver)
        self.assertEqual(approval.gateway_message_id, 9200)
        self.assertIsNotNone(approval.telegram_message)
        self.assertEqual(approval.telegram_message.message_id, 9200)

        self.client.force_authenticate(None)
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            {
                "event": "interaction",
                "payload": json.dumps({"approval_id": approval.id, "decision": "rejected"}),
                "user_id": str(approval.approver_external_user_id),
                "recipient_id": approval.approver_recipient_id,
                "message_id": approval.gateway_message_id,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        approval.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_REJECTED)
        self.assertEqual(approval.request.status, Request.STATUS_REJECTED)
        self.assertEqual(TelegramMessage.objects.filter(tenant=self.tenant).count(), 1)

    def test_webhook_invp_prefix_delegates_to_investment_handler(self):
        """Regression: project investment inline buttons use invp_<id>:a|r — not inv_."""
        payload = {
            "event": "interaction",
            "payload": "invp_999999:a",
            "user_id": "777001",
            "recipient_id": "555001",
            "message_id": 4321,
            "platform": "telegram",
        }
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)
        # Wrong path was request-approval parser → "approval_id is required and must be integer."
        self.assertNotIn("must be integer", str(res.content))
        self.assertIn("Approval not found", str(res.content))

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_webhook_callback_rejects_wrong_chat(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":4321}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 4321}}
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Needs approval",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        approval = self._create_approval_with_message(
            message_id=4321,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        payload = {
            "event": "interaction",
            "payload": json.dumps({"approval_id": approval.id, "decision": "approved"}),
            "user_id": "777001",
            "recipient_id": "888888",
            "message_id": 4321,
            "platform": "telegram",
        }
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)
        approval.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_PENDING)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_webhook_callback_conflict_refreshes_message_without_buttons(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":4321}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 4321}}
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Already decided",
            status=Request.STATUS_APPROVED,
            billing_date=date(2026, 3, 31),
        )
        approval = self._create_approval_with_message(
            message_id=4321,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )
        payload = {
            "event": "interaction",
            "payload": f"v2_{approval.id}:a",
            "user_id": "777001",
            "recipient_id": "555001",
            "message_id": 4321,
            "platform": "telegram",
        }
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.data.get("detail"), "Решение по согласованию уже принято.")
        self.assertEqual(mocked_post.call_count, 1)
        edit_payload = mocked_post.call_args.kwargs.get("json", {})
        self.assertEqual(edit_payload.get("action"), "edit_interactive")
        self.assertEqual(edit_payload.get("buttons"), [])
        self.assertIn("полностью одобрена", edit_payload.get("text", ""))

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_webhook_callback_conflict_uses_callback_message_id_when_missing_on_approval(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":3694}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 3694}}
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Already decided without message_id",
            status=Request.STATUS_APPROVED,
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )
        payload = {
            "event": "interaction",
            "payload": f"v2_{approval.id}:a",
            "user_id": "777001",
            "recipient_id": "555001",
            "message_id": 3694,
            "platform": "telegram",
        }
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(mocked_post.call_count, 1)
        edit_payload = mocked_post.call_args.kwargs.get("json", {})
        self.assertEqual(edit_payload.get("action"), "edit_interactive")
        self.assertEqual(edit_payload.get("message_id"), 3694)
        self.assertEqual(edit_payload.get("recipient_id"), "555001")
        self.assertEqual(edit_payload.get("buttons"), [])

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_webhook_callback_persists_missing_message_id_from_callback(self, mocked_post):
        mocked_post.return_value.status_code = 200
        # Edit call is expected to keep the same message_id as in callback.
        mocked_post.return_value.content = b'{"result":{"message_id":4123}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 4123}}
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Needs approval",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        payload = {
            "event": "interaction",
            "payload": f"v2_{approval.id}:a",
            "user_id": "777001",
            "recipient_id": "555001",
            "message_id": 4123,
            "platform": "telegram",
        }
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        approval.refresh_from_db()
        self.assertEqual(approval.gateway_message_id, 4123)
        self.assertTrue(approval.message_sent)
        self.assertIsNotNone(approval.message_sent_at)

    def test_webhook_callback_allows_missing_message_id(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Missing message_id is allowed",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )
        payload = {
            "event": "interaction",
            "payload": f"v2_{approval.id}:a",
            "user_id": "777001",
            "recipient_id": "555001",
            "platform": "telegram",
        }
        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        approval.refresh_from_db()
        self.assertIsNone(approval.gateway_message_id)
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_payment_callback_mode_buttons_use_vyplatit_otmenit(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":5002}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 5002}}
        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.tenant)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Перечисление", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        self.client.force_authenticate(self.requester)
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
        row = payload.get("buttons", [[{}, {}]])[0]
        self.assertEqual(row[0]["label"], "💰 Выплатить")
        self.assertIn("value", row[0])
        self.assertEqual(row[1]["label"], "❌ Отменить")

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_payment_webapp_mode_uses_url_button(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":5003}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 5003}}
        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.tenant)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Перечисление", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=2,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
            payment_webapp_url="https://acme.example.com/tg/payment?approval_id={approval_id}&request_id={request_id}",
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        self.client.force_authenticate(self.requester)
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
        row = payload.get("buttons", [[{}, {}]])[0]
        self.assertEqual(row[0]["label"], "💰 Выплатить")
        self.assertIn("url", row[0])
        self.assertIn("approval_id=", row[0]["url"])
        self.assertEqual(row[1]["label"], "❌ Отменить")

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_payment_webapp_tme_base_url_appends_startapp(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":5004}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 5004}}
        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.tenant)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Перечисление", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=2,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
            payment_webapp_url="https://t.me/kolberg_requests_bot/payment",
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        self.client.force_authenticate(self.requester)
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
        aid = payload.get("approval_id")
        self.assertIsNotNone(aid)
        row = payload.get("buttons", [[{}, {}]])[0]
        self.assertEqual(row[0]["label"], "💰 Выплатить")
        url = row[0]["url"]
        self.assertTrue(url.startswith("https://t.me/kolberg_requests_bot/payment"))
        self.assertIn("startapp=", url)
        # approval_id in buttons is str now
        self.assertIn("startapp=", url)

    def test_message_headers_for_statuses(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Need review",
            status=Request.STATUS_APPROVED,
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            decision=Approval.DECISION_APPROVED,
        )
        txt = build_approval_message(request_obj=request_row, approval=approval)
        self.assertIn("✅ Заявка №", txt)
        self.assertIn("полностью одобрена", txt)
        self.assertNotIn("Ответственный за оплату", txt)
        self.assertNotIn("Сейчас ожидается решение от", txt)

    def test_pending_build_approval_message_shows_who_must_decide(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Pending serial",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )
        txt = build_approval_message(request_obj=request_row, approval=approval)
        self.assertIn("Сейчас ожидается решение от", txt)
        self.assertIn("Петр Петров", txt)
        self.assertNotIn("Ответственный за оплату", txt)
        self.assertNotIn("appr", txt)

    def test_approved_pending_payment_shows_decision_actor_not_payment_subheader(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Awaiting payment",
            status=Request.STATUS_APPROVED,
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=2,
            step_type=Approval.STEP_TYPE_PAYMENT,
            decision=Approval.DECISION_PENDING,
        )
        txt = build_approval_message(request_obj=request_row, approval=approval)
        self.assertIn("полностью одобрена", txt)
        self.assertNotIn("Ответственный за оплату", txt)
        self.assertIn("Сейчас ожидается решение от", txt)
        self.assertIn("Петр Петров", txt)

    def test_rejected_subheader_uses_full_name(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Rejected request",
            status=Request.STATUS_REJECTED,
            billing_date=date(2026, 3, 31),
        )
        Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            approver_external_user_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_REJECTED,
        )
        txt = build_approval_message(request_obj=request_row, approval=None)
        self.assertIn("Петр Петров", txt)
        self.assertNotIn("appr", txt)

    def test_build_approval_message_billing_month_from_billing_date_without_expense(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="No expense fields",
            status=Request.STATUS_APPROVED,
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )
        txt = build_approval_message(request_obj=request_row, approval=approval)
        self.assertIn("Месяц начисления", txt)
        self.assertIn("March 2026", txt)
        self.assertNotIn("2026-03-31", txt)
        self.assertNotIn("31.03", txt)

    def test_build_approval_message_billing_month_prefers_expense_over_billing_date(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Expense vs billing",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 2, 1),
            expense_year=2026,
            expense_month=4,
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )
        txt = build_approval_message(request_obj=request_row, approval=approval)
        self.assertIn("April 2026", txt)
        self.assertNotIn("February 2026", txt)

    def test_build_approval_message_formats_amount_with_thousands_and_two_decimals(self):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Amount formatting",
            status=Request.STATUS_PROGRESS_1,
            amount=1000000,
            currency="UZS",
            payment_type="Наличные",
            billing_date=date(2026, 3, 31),
        )
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id="555001",
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )
        txt = build_approval_message(request_obj=request_row, approval=approval)
        self.assertIn("• Сумма: 1 000 000.00 UZS", txt)

    @patch("apps.modules.telegram_approvals.management.commands.refresh_telegram_approval_messages.refresh_request_messages")
    def test_refresh_telegram_approval_messages_command(self, mock_refresh):
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Mgmt refresh",
            status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 3, 31),
        )
        mock_refresh.return_value = 2
        out = StringIO()
        call_command("refresh_telegram_approval_messages", str(request_row.pk), stdout=out)
        mock_refresh.assert_called_once()
        _args, kwargs = mock_refresh.call_args
        self.assertEqual(kwargs.get("request_obj").id, request_row.id)
        self.assertIn("обновлено карточек: 2", out.getvalue())


# ---------------------------------------------------------------------------
# TenantTelegramChat API tests
# ---------------------------------------------------------------------------

@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TenantTelegramChatApiTests(APITestCase):
    """
    3 tests:
    1. create a chat via API
    2. unique (tenant, chat_id) constraint returns 400
    3. tenant isolation: tenant B cannot see tenant A chats
    """

    def setUp(self):
        self.tenant_a = Tenant.objects.create(name="Alpha", subdomain="alpha", is_active=True)
        self.tenant_b = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True)

        self.admin_a = User.objects.create_user(username="chat_admin_a", password="x")
        self.admin_b = User.objects.create_user(username="chat_admin_b", password="x")

        TenantMembership.objects.create(tenant=self.tenant_a, user=self.admin_a, is_active=True)
        TenantMembership.objects.create(tenant=self.tenant_b, user=self.admin_b, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant_a, user=self.admin_a, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant_b, user=self.admin_b, role=TenantUserRole.ROLE_ADMIN)

        self.host_a = "alpha.example.com"
        self.host_b = "beta.example.com"
        self.url = "/api/messaging-gateway/chats/"

    def test_create_chat(self):
        self.client.force_authenticate(self.admin_a)
        res = self.client.post(
            self.url,
            {"name": "Finance group", "chat_id": "-1001234567890", "is_active": True},
            format="json",
            HTTP_HOST=self.host_a,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["name"], "Finance group")
        self.assertEqual(res.data["chat_id"], "-1001234567890")
        self.assertTrue(TenantTelegramChat.objects.filter(tenant=self.tenant_a, chat_id="-1001234567890").exists())

    def test_duplicate_chat_id_returns_400(self):
        TenantTelegramChat.objects.create(
            tenant=self.tenant_a, name="Existing", chat_id="-1001111111111"
        )
        self.client.force_authenticate(self.admin_a)
        res = self.client.post(
            self.url,
            {"name": "Duplicate", "chat_id": "-1001111111111", "is_active": True},
            format="json",
            HTTP_HOST=self.host_a,
        )
        self.assertEqual(res.status_code, 400, res.content)

    def test_tenant_b_cannot_see_tenant_a_chats(self):
        TenantTelegramChat.objects.create(
            tenant=self.tenant_a, name="Alpha only", chat_id="-1009998887771"
        )
        self.client.force_authenticate(self.admin_b)
        res = self.client.get(self.url, HTTP_HOST=self.host_b)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(len(list_results(res)), 0)


# ---------------------------------------------------------------------------
# Integration tests — real gateway + real Telegram API
#
# Requirements:
#   - Gateway running at MESSAGING_GATEWAY_SEND_URL (default localhost:8080)
#   - TELEGRAM_BOT_TOKEN env var (or hardcoded default for the test bot)
#   - TELEGRAM_TEST_RECIPIENT_ID env var (or hardcoded default)
#
# Run:
#   RUN_INTEGRATION_TESTS=1 python manage.py test apps.modules.telegram_approvals.tests.TelegramGatewayIntegrationTests
# ---------------------------------------------------------------------------

_GATEWAY_URL = os.environ.get(
    "MESSAGING_GATEWAY_SEND_URL",
    "http://localhost:8080/v1/messaging/send",
)
_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8411387505:AAE0BSIOft8st2vPxrkOU7FuIdgymG81nsg",
)
_RECIPIENT_ID = os.environ.get("TELEGRAM_TEST_RECIPIENT_ID", "8306054387")


def _gateway_reachable() -> bool:
    if not os.environ.get("RUN_INTEGRATION_TESTS"):
        return False
    health = _GATEWAY_URL.rsplit("/v1/messaging/send", 1)[0] + "/health"
    try:
        r = _real_requests.get(health, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


_GATEWAY_UP = _gateway_reachable()


@override_settings(
    BASE_DOMAIN="example.com",
    MESSAGING_GATEWAY_SEND_URL=_GATEWAY_URL,
    TELEGRAM_BOT_TOKEN=_BOT_TOKEN,
    ALLOWED_HOSTS=["*"],
)
class TelegramGatewayIntegrationTests(APITestCase):
    """
    End-to-end tests: Django backend → real gateway → real Telegram API.
    No requests.post mock — every HTTP call hits the actual gateway.

    Skip by default. Enable with: RUN_INTEGRATION_TESTS=1
    """

    def setUp(self):
        if not _GATEWAY_UP:
            self.skipTest("Gateway not reachable — set RUN_INTEGRATION_TESTS=1 and start the gateway")

        self._cleanup_message_ids: list[int] = []

        self.tenant = Tenant.objects.create(name="IntegTest", subdomain="integ", is_active=True)
        self.admin = User.objects.create_user(username="integ_admin", password="x")
        self.requester = User.objects.create_user(
            username="integ_req", password="x", full_name="Integration Tester"
        )
        self.approver = User.objects.create_user(
            username="integ_appr",
            password="x",
            full_name="Real Approver",
            telegram_chat_id=int(_RECIPIENT_ID),
            telegram_from_id=int(_RECIPIENT_ID),
        )
        for user in (self.admin, self.requester, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(config=req_form_cfg, payment_type="Наличные", is_enabled=True)

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg, step=1, step_type=Approval.STEP_TYPE_SERIAL, is_enabled=True
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        self.host = "integ.example.com"

    def _create_approval_with_message(self, message_id, **kwargs):
        recipient_id = kwargs.get("approver_recipient_id")
        external_user_id = kwargs.get("approver_external_user_id")
        tm = TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id=str(recipient_id or "999"),
            external_user_id=external_user_id,
            message_id=message_id,
            sent_at=timezone.now(),
        )
        return Approval.objects.create(
            telegram_message=tm,
            **kwargs,
        )

    def tearDown(self):
        for mid in self._cleanup_message_ids:
            try:
                _real_requests.post(_GATEWAY_URL, json={
                    "action": "delete",
                    "bot_token": _BOT_TOKEN,
                    "tenant_id": "integ",
                    "recipient_id": _RECIPIENT_ID,
                    "message_id": mid,
                }, timeout=5)
            except Exception:
                pass

    def _send_via_gateway(self, text: str, buttons: list | None = None) -> int:
        """Helper: send a real message via gateway, register for cleanup, return message_id."""
        payload: dict = {
            "action": "send_interactive" if buttons else "send",
            "bot_token": _BOT_TOKEN,
            "tenant_id": "integ",
            "recipient_id": _RECIPIENT_ID,
            "text": text,
        }
        if buttons is not None:
            payload["buttons"] = buttons
        resp = _real_requests.post(_GATEWAY_URL, json=payload, timeout=10)
        self.assertEqual(resp.status_code, 200, f"Gateway send failed: {resp.text}")
        mid = resp.json()["message_id"]
        self._cleanup_message_ids.append(mid)
        return mid

    # ── Test 1: sendMessage ──────────────────────────────────────────────────

    def test_request_create_sends_real_message_and_saves_message_id(self):
        """
        Creating a request must call the gateway which calls Telegram sendMessage.
        The real message_id returned by Telegram must be persisted on the Approval row.
        """
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "[Integration] sendMessage test",
                "description": "Real gateway test — verifying sendMessage",
                "amount": 50000,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester.id,
                "billing_date": "2026-04-30",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)

        approval = Approval.objects.get(request_id=res.data["id"])
        self.assertIsNotNone(approval.gateway_message_id, "Telegram sendMessage must return a real message_id")
        self.assertIsInstance(approval.gateway_message_id, int)
        self.assertGreater(approval.gateway_message_id, 0)
        self.assertTrue(approval.message_sent)
        self.assertIsNotNone(approval.message_sent_at)
        self._cleanup_message_ids.append(approval.gateway_message_id)

    # ── Test 2: editMessage — approve via webhook ────────────────────────────

    def test_webhook_approval_triggers_real_edit_message(self):
        """
        Sending the approval webhook must:
        1. Confirm the approval in the DB
        2. Call the gateway editMessageText to remove the buttons from the Telegram message
        """
        mid = self._send_via_gateway(
            text="<b>[Integration] editMessage test</b>\nApprove or reject?",
            buttons=[[
                {"label": "✅ Одобрить", "value": "v2_0:a"},
                {"label": "❌ Отклонить", "value": "v2_0:r"},
            ]],
        )

        request_row = Request.objects.create(
            tenant=self.tenant, created_by=self.admin, requester=self.requester,
            title="editMessage test", status=Request.STATUS_PROGRESS_1,
            billing_date=date(2026, 4, 30),
        )
        approval = self._create_approval_with_message(
            message_id=mid,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id=int(_RECIPIENT_ID),
            approver_external_user_id=int(_RECIPIENT_ID),
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        # Update the button values to reference the real approval id
        edit_resp = _real_requests.post(_GATEWAY_URL, json={
            "action": "edit_interactive",
            "bot_token": _BOT_TOKEN,
            "tenant_id": "integ",
            "recipient_id": _RECIPIENT_ID,
            "message_id": mid,
            "text": "<b>[Integration] editMessage test</b>\nApprove or reject?",
            "buttons": [[
                {"label": "✅ Одобрить", "value": f"v2_{approval.id}:a"},
                {"label": "❌ Отклонить", "value": f"v2_{approval.id}:r"},
            ]],
        }, timeout=10)
        self.assertEqual(edit_resp.status_code, 200, edit_resp.text)

        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            {
                "event": "interaction",
                "payload": f"v2_{approval.id}:a",
                "user_id": _RECIPIENT_ID,
                "recipient_id": _RECIPIENT_ID,
                "message_id": mid,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        approval.refresh_from_db()
        request_row.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)
        self.assertEqual(request_row.status, Request.STATUS_APPROVED)

    # ── Test 3: conflict callback deactivates buttons via editMessage ────────

    def test_conflict_callback_calls_real_edit_to_deactivate_buttons(self):
        """
        A duplicate callback on an already-decided approval must call the gateway
        editMessageText with buttons=[] — removing the buttons from the Telegram message.
        Returns 409 to the caller.
        """
        mid = self._send_via_gateway(
            text="<b>[Integration] conflict/deactivate test</b>\nAlready decided.",
            buttons=[[
                {"label": "✅ Одобрить", "value": "v2_0:a"},
                {"label": "❌ Отклонить", "value": "v2_0:r"},
            ]],
        )

        request_row = Request.objects.create(
            tenant=self.tenant, created_by=self.admin, requester=self.requester,
            title="Conflict deactivate test", status=Request.STATUS_APPROVED,
            billing_date=date(2026, 4, 30),
        )
        approval = self._create_approval_with_message(
            message_id=mid,
            request=request_row,
            approver_user=self.approver,
            approver_recipient_id=int(_RECIPIENT_ID),
            approver_external_user_id=int(_RECIPIENT_ID),
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )

        res = self.client.post(
            "/api/messaging-gateway/webhook/",
            {
                "event": "interaction",
                "payload": f"v2_{approval.id}:a",
                "user_id": _RECIPIENT_ID,
                "recipient_id": _RECIPIENT_ID,
                "message_id": mid,
                "platform": "telegram",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.data.get("detail"), "Решение по согласованию уже принято.")

