import json
from datetime import date
from io import StringIO
from unittest.mock import patch

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
        mocked_post.return_value.status_code = 500
        mocked_post.return_value.content = b"Gateway Error"
        result = post_messaging_gateway(
            tenant=self.tenant,
            payload={"action": "send", "text": "hello"},
        )
        self.assertIsNone(result)
        self.assertEqual(mocked_post.call_count, 1)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_card_deactivates_old_and_sends_new_message(self, mocked_post):
        """Per-card resend: same Approval + same TelegramMessage stay; only message_id mutates."""
        edit_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":4321}}'})()
        edit_response.json = lambda: {"result": {"message_id": 4321}}
        send_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":9999}}'})()
        send_response.json = lambda: {"result": {"message_id": 9999}}
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
        tm_pk = approval.telegram_message_id

        self.client.force_authenticate(self.admin)
        res = self.client.post(
            f"/api/requests/{request_row.id}/approvals/{approval.id}/resend/",
            {},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        # Approval row stays PENDING — no cancel+create churn.
        approval.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_PENDING)
        # Same TelegramMessage row, new message_id, resend_count incremented.
        self.assertEqual(approval.telegram_message_id, tm_pk)
        tm = approval.telegram_message
        self.assertEqual(tm.message_id, 9999)
        self.assertEqual(tm.resend_count, 1)
        # Gateway called twice: deactivate (no buttons) then send (with buttons).
        self.assertEqual(mocked_post.call_count, 2)
        deact_payload = mocked_post.call_args_list[0].kwargs.get("json", {})
        send_payload = mocked_post.call_args_list[1].kwargs.get("json", {})
        self.assertEqual(deact_payload.get("buttons"), [])
        self.assertTrue(send_payload.get("buttons"))

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_card_cooldown_returns_429(self, mocked_post):
        """Second resend within 10s must be rejected with 429 (cooldown)."""
        edit_response = type("Resp", (), {"status_code": 200, "content": b'{}'})()
        edit_response.json = lambda: {}
        send_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":9999}}'})()
        send_response.json = lambda: {"result": {"message_id": 9999}}
        mocked_post.side_effect = [edit_response, send_response]

        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="Cooldown test",
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
        res1 = self.client.post(
            f"/api/requests/{request_row.id}/approvals/{approval.id}/resend/",
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res1.status_code, 200, res1.content)

        # Immediate second resend must be throttled.
        res2 = self.client.post(
            f"/api/requests/{request_row.id}/approvals/{approval.id}/resend/",
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res2.status_code, 429, res2.content)

    def test_resend_card_fails_when_approval_already_decided(self):
        """Resend must fail when the approval is not PENDING (already approved/rejected)."""
        request_row = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester,
            title="No pending",
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
            decision=Approval.DECISION_APPROVED,
        )
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            f"/api/requests/{request_row.id}/approvals/{approval.id}/resend/",
            {},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_card_works_for_payment_step(self, mocked_post):
        """Payment-step cards can be resent with the same per-card mechanism."""
        edit_response = type("Resp", (), {"status_code": 200, "content": b'{}'})()
        edit_response.json = lambda: {}
        send_response = type("Resp", (), {"status_code": 200, "content": b'{"result":{"message_id":10001}}'})()
        send_response.json = lambda: {"result": {"message_id": 10001}}
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
        payment_approval = self._create_approval_with_message(
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
            f"/api/requests/{request_row.id}/approvals/{payment_approval.id}/resend/",
            {},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        payment_approval.refresh_from_db()
        self.assertEqual(payment_approval.decision, Approval.DECISION_PENDING)
        self.assertEqual(payment_approval.telegram_message.message_id, 10001)
        self.assertEqual(payment_approval.telegram_message.resend_count, 1)
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


@override_settings(
    BASE_DOMAIN="example.com",
    MESSAGING_GATEWAY_SEND_URL="https://acme.example.com/v1/messaging/send",
    ALLOWED_HOSTS=["*"],
)
class MessagingGatewayAuxiliaryCallbackTests(APITestCase):
    """Task buttons and invest_pay callbacks routed through the main messaging webhook."""

    def setUp(self):
        from decimal import Decimal

        from apps.modules.investments.models import InvestNotificationConfig, InvestPayoutSchedule
        from apps.modules.tasks.models import Task

        self._Decimal = Decimal
        self._InvestNotificationConfig = InvestNotificationConfig
        self._InvestPayoutSchedule = InvestPayoutSchedule
        self._Task = Task

        self.tenant = Tenant.objects.create(name="AuxCo", subdomain="auxco", is_active=True)
        self.assignee = User.objects.create_user(
            username="task-assignee",
            password="x",
            telegram_chat_id=88001,
            telegram_from_id=88001,
        )
        self.responsible = User.objects.create_user(
            username="invest-responsible",
            password="x",
            telegram_chat_id=88002,
        )
        for user in (self.assignee, self.responsible):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        self.host = "auxco.example.com"

    def _webhook(self, payload: dict):
        return self.client.post(
            "/api/messaging-gateway/webhook/",
            {"event": "interaction", "platform": "telegram", **payload},
            format="json",
            HTTP_HOST=self.host,
        )

    def test_task_progress_callback_moves_task_to_in_progress(self):
        now = timezone.now()
        task = self._Task.objects.create(
            tenant=self.tenant,
            title="Callback task",
            description="",
            status=self._Task.Status.NEW,
            assignee=self.assignee,
            created_by=self.assignee,
            last_edit_at=now,
            last_edit_by=self.assignee,
        )
        res = self._webhook(
            {
                "payload": f"task_p_{task.pk}",
                "user_id": str(self.assignee.telegram_from_id),
                "recipient_id": str(self.assignee.telegram_chat_id),
            }
        )
        self.assertEqual(res.status_code, 200, res.content)
        task.refresh_from_db()
        self.assertEqual(task.status, self._Task.Status.IN_PROGRESS)

    def test_task_done_callback_archives_task(self):
        now = timezone.now()
        task = self._Task.objects.create(
            tenant=self.tenant,
            title="Done task",
            description="",
            status=self._Task.Status.IN_PROGRESS,
            assignee=self.assignee,
            created_by=self.assignee,
            last_edit_at=now,
            last_edit_by=self.assignee,
        )
        res = self._webhook(
            {
                "payload": f"task_a_{task.pk}",
                "user_id": str(self.assignee.telegram_from_id),
                "recipient_id": str(self.assignee.telegram_chat_id),
            }
        )
        self.assertEqual(res.status_code, 200, res.content)
        task.refresh_from_db()
        self.assertEqual(task.status, self._Task.Status.DONE)

    def test_task_callback_rejects_non_assignee(self):
        now = timezone.now()
        other = User.objects.create_user(
            username="other-user",
            password="x",
            telegram_from_id=99999,
        )
        task = self._Task.objects.create(
            tenant=self.tenant,
            title="Protected task",
            description="",
            status=self._Task.Status.NEW,
            assignee=self.assignee,
            created_by=self.assignee,
            last_edit_at=now,
            last_edit_by=self.assignee,
        )
        res = self._webhook(
            {
                "payload": f"task_p_{task.pk}",
                "user_id": str(other.telegram_from_id),
                "recipient_id": str(other.telegram_from_id),
            }
        )
        self.assertEqual(res.status_code, 403, res.content)
        task.refresh_from_db()
        self.assertEqual(task.status, self._Task.Status.NEW)

    @patch(
        "apps.modules.investments.notification_services.remove_payout_notification_button",
        return_value=True,
    )
    def test_invest_pay_callback_creates_return_for_schedule(self, _cleanup_mock):
        from apps.modules.investments.models import InvestCompany, InvestReturn

        company = InvestCompany.objects.create(
            tenant=self.tenant,
            name="Aux invest co",
            created_by=self.responsible,
        )
        self._InvestNotificationConfig.objects.create(
            tenant=self.tenant,
            responsible_user=self.responsible,
            days_before=3,
            is_active=True,
        )
        schedule = self._InvestPayoutSchedule.objects.create(
            tenant=self.tenant,
            company=company,
            payout_date=date(2026, 6, 15),
            amount=self._Decimal("1000.00"),
            currency="USD",
            return_type=InvestReturn.ReturnType.DIVIDEND,
            recipient=InvestReturn.Recipient.INVESTOR,
            created_by=self.responsible,
        )
        res = self._webhook(
            {
                "payload": f"invest_pay:{schedule.pk}",
                "user_id": str(self.responsible.telegram_chat_id),
                "recipient_id": str(self.responsible.telegram_chat_id),
                "message_id": 12001,
            }
        )
        self.assertEqual(res.status_code, 201, res.content)
        schedule.refresh_from_db()
        self.assertIsNotNone(schedule.created_return_id)
        self.assertIn("создана", res.data.get("detail", "").lower())



# ── TelegramMessageHistory tests ──────────────────────────────────────────────

@override_settings(
    BASE_DOMAIN="example.com",
    MESSAGING_GATEWAY_SEND_URL="http://fake-gateway/send",
    N8N_INTEGRATION_TOKEN="test-n8n-token",
    ALLOWED_HOSTS=["*"],
)
class TelegramMessageHistoryTests(APITestCase):
    """Verify that TelegramDispatcher records history rows correctly."""

    def setUp(self):
        from apps.tenants.models import Tenant, TenantMembership
        self.tenant = Tenant.objects.create(name="HistTenant", subdomain="hist", is_active=True)

    def _make_tm(self, message_id=100):
        return TelegramMessage.objects.create(
            tenant=self.tenant,
            recipient_id="123456",
            message_id=message_id,
            sent_at=timezone.now(),
        )

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_send_creates_history_row(self, mock_post):
        from apps.modules.telegram_approvals.models import TelegramMessageHistory
        from apps.modules.telegram_approvals.services import TelegramDispatcher

        resp = type("R", (), {"status_code": 200, "content": b'{"message_id":42}'})()
        resp.json = lambda: {"message_id": 42}
        mock_post.return_value = resp

        dispatcher = TelegramDispatcher(self.tenant)
        msg = dispatcher.send(action="send", recipient_id="123", text="Hello", buttons=[])

        self.assertIsNotNone(msg)
        history = TelegramMessageHistory.objects.filter(telegram_message=msg, action=TelegramMessageHistory.ACTION_SEND)
        self.assertEqual(history.count(), 1)
        row = history.first()
        self.assertEqual(row.message_id, 42)
        self.assertTrue(row.success)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_send_history_redacts_bot_token(self, mock_post):
        from apps.modules.telegram_approvals.models import TelegramMessageHistory
        from apps.modules.telegram_approvals.services import TelegramDispatcher

        resp = type("R", (), {"status_code": 200, "content": b'{"message_id":99}'})()
        resp.json = lambda: {"message_id": 99}
        mock_post.return_value = resp

        dispatcher = TelegramDispatcher(self.tenant)
        dispatcher.bot_token = "secret-token-12345"
        msg = dispatcher.send(action="send", recipient_id="123", text="Test")

        row = TelegramMessageHistory.objects.get(telegram_message=msg, action=TelegramMessageHistory.ACTION_SEND)
        stored = row.request_payload or {}
        self.assertEqual(stored.get("bot_token"), "***", "bot_token must be redacted in history")
        self.assertNotIn("secret-token-12345", str(stored))

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_edit_creates_history_row(self, mock_post):
        from apps.modules.telegram_approvals.models import TelegramMessageHistory
        from apps.modules.telegram_approvals.services import TelegramDispatcher

        resp = type("R", (), {"status_code": 200, "content": b'{}'})()
        resp.json = lambda: {}
        mock_post.return_value = resp

        tm = self._make_tm(200)
        dispatcher = TelegramDispatcher(self.tenant)
        dispatcher.edit(tm, action="edit", text="Edited text")

        row = TelegramMessageHistory.objects.get(telegram_message=tm, action=TelegramMessageHistory.ACTION_EDIT)
        self.assertTrue(row.success)
        self.assertEqual(row.message_id, 200)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_deactivate_records_deactivate_action(self, mock_post):
        from apps.modules.telegram_approvals.models import TelegramMessageHistory
        from apps.modules.telegram_approvals.services import TelegramDispatcher

        resp = type("R", (), {"status_code": 200, "content": b'{}'})()
        resp.json = lambda: {}
        mock_post.return_value = resp

        tm = self._make_tm(300)
        dispatcher = TelegramDispatcher(self.tenant)
        dispatcher.deactivate(tm, action="edit", text="Closed")

        row = TelegramMessageHistory.objects.get(telegram_message=tm, action=TelegramMessageHistory.ACTION_DEACTIVATE)
        self.assertIsNotNone(row)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_creates_two_history_rows_and_mutates_message_id(self, mock_post):
        from apps.modules.telegram_approvals.models import TelegramMessageHistory
        from apps.modules.telegram_approvals.services import TelegramDispatcher

        deact_resp = type("R", (), {"status_code": 200, "content": b'{}'})()
        deact_resp.json = lambda: {}
        new_send_resp = type("R", (), {"status_code": 200, "content": b'{"message_id":999}'})()
        new_send_resp.json = lambda: {"message_id": 999}
        mock_post.side_effect = [deact_resp, new_send_resp]

        tm = self._make_tm(500)
        original_id = tm.pk
        dispatcher = TelegramDispatcher(self.tenant)
        result = dispatcher.resend(tm, action_deactivate="edit", action_send="send", text="New card")

        self.assertIsNotNone(result)
        self.assertEqual(result.message_id, 999)
        self.assertEqual(result.resend_count, 1)

        tm.refresh_from_db()
        self.assertEqual(tm.message_id, 999)
        self.assertEqual(tm.resend_count, 1)

        old_row = TelegramMessageHistory.objects.get(telegram_message_id=original_id, action=TelegramMessageHistory.ACTION_RESEND_OLD)
        self.assertEqual(old_row.message_id, 500)
        new_row = TelegramMessageHistory.objects.get(telegram_message_id=original_id, action=TelegramMessageHistory.ACTION_RESEND_NEW)
        self.assertEqual(new_row.message_id, 999)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_resend_gateway_failure_returns_none(self, mock_post):
        from apps.modules.telegram_approvals.services import TelegramDispatcher

        deact_resp = type("R", (), {"status_code": 200, "content": b'{}'})()
        deact_resp.json = lambda: {}
        fail_resp = type("R", (), {"status_code": 500, "content": b'error'})()
        mock_post.side_effect = [deact_resp, fail_resp]

        tm = self._make_tm(600)
        dispatcher = TelegramDispatcher(self.tenant)
        result = dispatcher.resend(tm, action_deactivate="edit", action_send="send", text="New")

        self.assertIsNone(result)
        # message_id must NOT have changed
        tm.refresh_from_db()
        self.assertEqual(tm.message_id, 600)
        self.assertEqual(tm.resend_count, 0)
