from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from urllib.parse import parse_qs, urlparse

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.requests.models import (
    Approval,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestPaymentPurposeConfig,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepConfig,
    RequestApprovalStepApproverConfig,
    UserRequestApproval,
)

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class RequestFormConfigTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.requester_a = User.objects.create_user(username="req_a", password="x")
        self.requester_b = User.objects.create_user(username="req_b", password="x")

        for u in (self.admin, self.requester_a, self.requester_b):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN, step=1)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester_a, role=TenantUserRole.ROLE_REQUESTER, step=1)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester_b, role=TenantUserRole.ROLE_REQUESTER, step=1)

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="vendors", is_enabled=True)

        self.host = "acme.example.com"

    def test_admin_can_get_and_put_form_config(self):
        self.client.force_authenticate(self.admin)

        res = self.client.get("/api/requests/form-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)

        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "requester_ids": [self.requester_a.id],
                    "vendor_ids": [],
                    "payment_purposes": [{"name": "Office", "category": "Admin", "is_active": True}],
                }
            ]
        }
        res2 = self.client.put("/api/requests/form-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(any(pt["payment_type"] == "Наличные" for pt in res2.data.get("payment_types", [])))

    def test_non_admin_cannot_put_form_config(self):
        self.client.force_authenticate(self.requester_a)
        payload = {"payment_types": [{"payment_type": "Наличные", "is_enabled": True}]}
        res = self.client.put("/api/requests/form-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertIn(res.status_code, (403, 401))

    def test_disabled_payment_type_rejected_on_create(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=False)

        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 1,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester_a.id,
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("payment_type", res.data)

    def test_category_auto_set_from_payment_purpose(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_cfg,
            name="Office",
            category="Admin",
            is_active=True,
        )

        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 1,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester_a.id,
                "payment_purpose": "Office",
                "category": "Wrong",
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["category"], "Admin")

    def test_admin_can_assign_requester_outside_form_subset(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester_a)

        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 1,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester_b.id,
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["requester"], self.requester_b.id)

    def test_non_admin_rejected_when_self_not_in_requester_subset(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester_a)

        self.client.force_authenticate(self.requester_b)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 1,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("requester", res.data)

    def test_non_admin_payload_requester_for_actor_only(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester_a)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester_b)

        self.client.force_authenticate(self.requester_a)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 1,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester_b.id,
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["requester"], self.requester_a.id)

    def test_form_options_requesters_match_config_only(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester_a)

        self.client.force_authenticate(self.requester_a)
        res = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        pts = res.data["payment_types"]
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0]["payment_type"], "Наличные")
        ids = {r["id"] for r in pts[0]["requesters"]}
        self.assertEqual(ids, {self.requester_a.id})

    def test_form_options_no_fallback_when_requesters_not_configured(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)

        self.client.force_authenticate(self.requester_a)
        res = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        pts = res.data["payment_types"]
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0]["requesters"], [])


    def test_public_create_does_not_use_client_supplied_id(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/",
            {
                "id": 99999,
                "title": "T",
                "description": "",
                "amount": 1,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "requester": self.requester_a.id,
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("id", res.data)

    def test_form_options_includes_admin_flag_and_requester_candidates(self):
        self.client.force_authenticate(self.requester_a)
        res = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertIs(res.data["is_tenant_admin"], False)
        cand_ids = {r["id"] for r in res.data["requester_candidates"]}
        self.assertEqual(cand_ids, {self.requester_a.id, self.requester_b.id})

        self.client.force_authenticate(self.admin)
        res2 = self.client.get("/api/requests/form-options/", HTTP_HOST=self.host)
        self.assertEqual(res2.status_code, 200)
        self.assertIs(res2.data["is_tenant_admin"], True)


@override_settings(BASE_DOMAIN="example.com", N8N_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestApprovalsTests(APITestCase):
    def setUp(self):
        from django.utils import timezone

        self.timezone = timezone

        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.requester = User.objects.create_user(username="req", password="x")
        self.approver = User.objects.create_user(username="appr", password="x")
        # Values used by approval creation logic.
        self.approver.telegram_chat_id = 111
        self.approver.telegram_from_id = 222
        self.approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])

        for u in (self.admin, self.requester, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN, step=1)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER, step=1
        )
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER, step=1
        )

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        self.host = "acme.example.com"

        # Minimal request-form config so `payment_type` is allowed.
        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(config=req_form_cfg, payment_type="Наличные", is_enabled=True)

        # Approvals config: one step with explicit approver user.
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

    def _create_request(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 10,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        if res.status_code != 201:
            raise AssertionError(
                f"Expected 201, got {res.status_code}. Response content: {res.content!r}"
            )
        return res.data

    def test_approvals_created_and_inbox_synced(self):
        req_data = self._create_request()
        request_id = req_data["id"]

        approval_qs = Approval.objects.filter(request_id=request_id, approver_user=self.approver)
        self.assertEqual(approval_qs.count(), 1)
        approval = approval_qs.first()
        self.assertEqual(approval.decision, Approval.DECISION_PENDING)
        self.assertEqual(approval.step, 1)
        self.assertEqual(approval.step_type, Approval.STEP_TYPE_SERIAL)
        self.assertEqual(approval.approver_tg_id, self.approver.telegram_chat_id)
        self.assertEqual(approval.approver_tg_from_id, self.approver.telegram_from_id)

        inbox_qs = UserRequestApproval.objects.filter(request_id=request_id, approver_user=self.approver)
        self.assertEqual(inbox_qs.count(), 1)
        inbox = inbox_qs.first()
        self.assertEqual(inbox.decision, Approval.DECISION_PENDING)
        self.assertEqual(inbox.step, 1)
        self.assertEqual(inbox.approver_tg_from_id, self.approver.telegram_from_id)

        self.client.force_authenticate(self.approver)
        res = self.client.get("/api/requests/my-approvals/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["request"]["id"], request_id)
        self.assertEqual(len(res.data[0]["approvals"]), 1)
        self.assertEqual(res.data[0]["approvals"][0]["decision"], Approval.DECISION_PENDING)

    def test_inbox_updates_on_approval_decision_change(self):
        req_data = self._create_request()
        request_id = req_data["id"]
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver)

        approval.decision = Approval.DECISION_APPROVED
        approval.decided_at = self.timezone.now()
        approval.comment = "ok"
        approval.save()

        inbox = UserRequestApproval.objects.get(request_id=request_id, approver_user=self.approver)
        self.assertEqual(inbox.decision, Approval.DECISION_APPROVED)
        self.assertIsNotNone(inbox.decided_at)
        self.assertEqual(inbox.comment, "ok")

        self.client.force_authenticate(self.approver)
        res = self.client.get("/api/requests/my-approvals/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data[0]["approvals"][0]["decision"], Approval.DECISION_APPROVED)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class RequestFileLinkRewriteTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.requester = User.objects.create_user(username="req", password="x")

        TenantMembership.objects.create(tenant=self.tenant, user=self.requester, is_active=True)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER, step=1
        )

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        # Minimal request-form config so `payment_type` is allowed.
        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.requester)
        RequestFormPaymentTypeConfig.objects.create(config=req_form_cfg, payment_type="Наличные", is_enabled=True)

        self.host = "acme.example.com"
        self.client.force_authenticate(self.requester)

    def _create_request(self, *, file_link: str) -> int:
        res = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 10,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
                "file_link": file_link,
            },
            format="json",
            HTTP_HOST=self.host,
        )
        if res.status_code != 201:
            raise AssertionError(
                f"Expected 201, got {res.status_code}. Response content: {res.content!r}"
            )
        return res.data["id"]

    def test_file_link_http_goes_through_gateway(self):
        raw = "https://example.com/doc.pdf"
        request_id = self._create_request(file_link=raw)

        res = self.client.get(f"/api/requests/{request_id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        file_url = res.data.get("file_link")
        self.assertIsInstance(file_url, str)

        self.assertIn("/api/files/gateway/", file_url)
        parsed = urlparse(file_url)
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get("path", [None])[0], raw)

    def test_file_link_relative_goes_through_download(self):
        raw = "requests/1/2/doc.pdf"
        request_id = self._create_request(file_link=raw)

        res = self.client.get(f"/api/requests/{request_id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        file_url = res.data.get("file_link")
        self.assertIsInstance(file_url, str)

        self.assertIn("/api/files/download/", file_url)
        parsed = urlparse(file_url)
        qs = parse_qs(parsed.query)
        self.assertEqual(qs.get("path", [None])[0], raw)

