import json
from datetime import date
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

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
from apps.modules.telegram_approvals.services import build_approval_message, post_telegram_bridge
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(
    BASE_DOMAIN="example.com",
    TELEGRAM_APPROVALS_BRIDGE_DISPATCH_URL="https://acme.example.com/n8n/telegram/dispatch",
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
        self.assertEqual(approval.message_id, 9001)
        self.assertTrue(approval.message_sent)
        self.assertIsNotNone(approval.message_sent_at)

        self.assertTrue(mocked_post.called)
        payload = mocked_post.call_args.kwargs.get("json", {})
        self.assertEqual(payload.get("action"), "send_approval_message")
        self.assertEqual(payload.get("chat_id"), 555001)
        self.assertIn("inline_keyboard", payload)
        self.assertEqual(payload.get("company"), "")
        self.assertIn("message", payload)
        self.assertIn("Иван Иванов", payload.get("message", ""))
        self.assertNotIn("• Заявитель: req", payload.get("message", ""))

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
        self.assertIsNone(approval.message_id)
        self.assertFalse(approval.message_sent)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_bridge_http_error_notifies_n8n_error_webhook(self, mocked_post):
        err_resp = type("R", (), {})()
        err_resp.status_code = 502
        err_resp.text = "bad gateway"
        err_resp.content = b"bad gateway"
        ok_resp = type("R", (), {})()
        ok_resp.status_code = 200
        ok_resp.content = b'{"result":{"message_id":9002}}'
        ok_resp.json = lambda: {"result": {"message_id": 9002}}
        mocked_post.side_effect = [err_resp, ok_resp]

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
        self.assertEqual(mocked_post.call_count, 2)
        error_call = mocked_post.call_args_list[1]
        self.assertIn("/n8n/error", error_call[0][0])
        err_payload = error_call[1].get("json", {})
        self.assertEqual(err_payload.get("source"), "telegram_approvals_bridge")
        self.assertEqual(err_payload.get("error_kind"), "http_error")
        self.assertEqual(err_payload.get("http_status"), 502)
        self.assertEqual(err_payload.get("payload_action"), "send_approval_message")
        self.assertIn("bad gateway", err_payload.get("response_body", ""))

    @patch("apps.modules.telegram_approvals.services.get_requests_telegram_integration_settings")
    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_post_bridge_survives_telegram_settings_resolution_error(self, mocked_post, mocked_settings_get):
        mocked_settings_get.side_effect = RuntimeError("broken tenant integration settings")
        result = post_telegram_bridge(
            tenant=self.tenant,
            payload={"action": "send_approval_message", "message": "hello"},
        )
        self.assertIsNone(result)
        self.assertEqual(mocked_post.call_count, 0)

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
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=4321,
            message_sent=True,
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
        self.assertEqual(approval.message_id, 4321)
        new_approval = Approval.objects.filter(request=request_row, replaced_approval=approval).get()
        self.assertEqual(new_approval.decision, Approval.DECISION_PENDING)
        self.assertTrue(new_approval.message_sent)
        self.assertEqual(new_approval.message_id, 9999)
        self.assertEqual(mocked_post.call_count, 2)
        first_payload = mocked_post.call_args_list[0].kwargs.get("json", {})
        second_payload = mocked_post.call_args_list[1].kwargs.get("json", {})
        self.assertEqual(first_payload.get("action"), "edit_approval_message")
        self.assertEqual(first_payload.get("inline_keyboard"), [])
        self.assertEqual(second_payload.get("action"), "send_approval_message")
        self.assertTrue(second_payload.get("inline_keyboard"))

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
        Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=4321,
            message_sent=True,
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
        Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=4321,
            message_sent=True,
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
        old_payment = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=7654,
            message_sent=True,
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
        self.assertEqual(new_payment.message_id, 10001)
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
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=4321,
            message_sent=True,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        payload = {
            "callback_query": {
                "id": "cbq1",
                "from": {"id": 777001},
                "message": {"message_id": 4321, "chat": {"id": 555001}},
                "data": json.dumps(
                    {
                        "approval_id": approval.id,
                        "request_id": request_row.id,
                        "step": 1,
                        "decision": "approved",
                    }
                ),
            }
        }
        res = self.client.post(
            "/api/telegram-approvals/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
            HTTP_X_N8N_INTEGRATION_TOKEN=self.webhook_token,
        )
        self.assertEqual(res.status_code, 200, res.content)

        approval.refresh_from_db()
        request_row.refresh_from_db()
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)
        self.assertEqual(request_row.status, Request.STATUS_APPROVED)

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
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=4321,
            message_sent=True,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        payload = {
            "callback_query": {
                "from": {"id": 777001},
                "message": {"message_id": 4321, "chat": {"id": 888888}},
                "data": json.dumps({"approval_id": approval.id, "decision": "approved"}),
            }
        }
        res = self.client.post(
            "/api/telegram-approvals/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
            HTTP_X_N8N_INTEGRATION_TOKEN=self.webhook_token,
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
        approval = Approval.objects.create(
            request=request_row,
            approver_user=self.approver,
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=4321,
            message_sent=True,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )
        payload = {
            "callback_query": {
                "id": "cbq-conflict",
                "from": {"id": 777001},
                "message": {"message_id": 4321, "chat": {"id": 555001}},
                "data": f"v2_{approval.id}:a",
            }
        }
        res = self.client.post(
            "/api/telegram-approvals/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
            HTTP_X_N8N_INTEGRATION_TOKEN=self.webhook_token,
        )
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.data.get("detail"), "Решение по согласованию уже принято.")
        self.assertEqual(mocked_post.call_count, 1)
        edit_payload = mocked_post.call_args.kwargs.get("json", {})
        self.assertEqual(edit_payload.get("action"), "edit_approval_message")
        self.assertEqual(edit_payload.get("inline_keyboard"), [])
        self.assertIn("полностью одобрена", edit_payload.get("message", ""))

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
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=None,
            message_sent=True,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_APPROVED,
        )
        payload = {
            "callback_query": {
                "id": "cbq-conflict-no-mid",
                "from": {"id": 777001},
                "message": {"message_id": 3694, "chat": {"id": 555001}},
                "data": f"v2_{approval.id}:a",
            }
        }
        res = self.client.post(
            "/api/telegram-approvals/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
            HTTP_X_N8N_INTEGRATION_TOKEN=self.webhook_token,
        )
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(mocked_post.call_count, 1)
        edit_payload = mocked_post.call_args.kwargs.get("json", {})
        self.assertEqual(edit_payload.get("action"), "edit_approval_message")
        self.assertEqual(edit_payload.get("message_id"), 3694)
        self.assertEqual(edit_payload.get("chat_id"), 555001)
        self.assertEqual(edit_payload.get("inline_keyboard"), [])

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_webhook_callback_persists_missing_message_id_from_callback(self, mocked_post):
        mocked_post.return_value.status_code = 200
        mocked_post.return_value.content = b'{"result":{"message_id":5001}}'
        mocked_post.return_value.json.return_value = {"result": {"message_id": 5001}}
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
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            message_id=None,
            message_sent=False,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        payload = {
            "callback_query": {
                "id": "cbq-persist-mid",
                "from": {"id": 777001},
                "message": {"message_id": 4123, "chat": {"id": 555001}},
                "data": f"v2_{approval.id}:a",
            }
        }
        res = self.client.post(
            "/api/telegram-approvals/webhook/",
            payload,
            format="json",
            HTTP_HOST=self.host,
            HTTP_X_N8N_INTEGRATION_TOKEN=self.webhook_token,
        )
        self.assertEqual(res.status_code, 200, res.content)
        approval.refresh_from_db()
        self.assertEqual(approval.message_id, 4123)
        self.assertTrue(approval.message_sent)
        self.assertIsNotNone(approval.message_sent_at)

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
        row = payload.get("inline_keyboard", [[{}, {}]])[0]
        self.assertEqual(row[0]["text"], "💰 Выплатить")
        self.assertIn("callback_data", row[0])
        self.assertEqual(row[1]["text"], "❌ Отменить")

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
        row = payload.get("inline_keyboard", [[{}, {}]])[0]
        self.assertEqual(row[0]["text"], "💰 Выплатить")
        self.assertIn("url", row[0])
        self.assertIn("approval_id=", row[0]["url"])
        self.assertEqual(row[1]["text"], "❌ Отменить")

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
        row = payload.get("inline_keyboard", [[{}, {}]])[0]
        self.assertEqual(row[0]["text"], "💰 Выплатить")
        url = row[0]["url"]
        self.assertTrue(url.startswith("https://t.me/kolberg_requests_bot/payment"))
        self.assertIn("startapp=", url)
        self.assertIn(f"startapp={aid}", url)

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
            approver_tg_id=555001,
            approver_tg_from_id=777001,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            decision=Approval.DECISION_APPROVED,
        )
        txt = build_approval_message(request_obj=request_row, approval=approval)
        self.assertIn("✅ Заявка №", txt)
        self.assertIn("полностью одобрена", txt)
        self.assertIn("Петр Петров", txt)
        self.assertNotIn("appr", txt)

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
            approver_tg_id=555001,
            approver_tg_from_id=777001,
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
            approver_tg_id=555001,
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
            approver_tg_id=555001,
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
            approver_tg_id=555001,
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

