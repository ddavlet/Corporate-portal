from datetime import date, datetime
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from urllib.parse import parse_qs, urlparse

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestCategory,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestFormPaymentTypeVendor,
    RequestPaymentPurposeConfig,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepConfig,
    RequestApprovalStepApproverConfig,
    UserRequestApproval,
    AutoRequestTemplate,
)
from apps.modules.requests.auto_requests import process_due_auto_requests, render_auto_request_template
from apps.modules.vendors.models import Vendor

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
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
                    "default_company_payer": "ACME LLC",
                    "payment_purposes": [{"name": "Office", "category": "Admin", "is_active": True}],
                }
            ]
        }
        res2 = self.client.put("/api/requests/form-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(any(pt["payment_type"] == "Наличные" for pt in res2.data.get("payment_types", [])))
        cash_pt = next(pt for pt in res2.data["payment_types"] if pt["payment_type"] == "Наличные")
        self.assertEqual(cash_pt.get("default_company_payer"), "ACME LLC")

    def test_non_admin_cannot_put_form_config(self):
        self.client.force_authenticate(self.requester_a)
        payload = {"payment_types": [{"payment_type": "Наличные", "is_enabled": True}]}
        res = self.client.put("/api/requests/form-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertIn(res.status_code, (403, 401))

    def test_admin_can_create_requester_via_form_config_requesters(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {"username": "new_req", "full_name": "New Requester"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200)
        u = User.objects.get(username="new_req")
        self.assertEqual(u.full_name, "New Requester")
        self.assertFalse(u.has_usable_password())
        self.assertTrue(
            TenantMembership.objects.filter(tenant=self.tenant, user=u, is_active=True).exists()
        )
        self.assertTrue(
            TenantUserRole.objects.filter(
                tenant=self.tenant,
                user=u,
                role=TenantUserRole.ROLE_REQUESTER,
                step=1,
            ).exists()
        )
        self.assertIn("payment_types", res.data)
        ids = {c["id"] for c in res.data.get("requester_candidates", [])}
        self.assertIn(u.id, ids)

    def test_create_requester_with_telegram_ids(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {
                "username": "tg_req",
                "full_name": "TG User",
                "telegram_chat_id": 111,
                "telegram_from_id": 222,
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200)
        u = User.objects.get(username="tg_req")
        self.assertEqual(u.telegram_chat_id, 111)
        self.assertEqual(u.telegram_from_id, 222)

    def test_create_requester_rejects_blank_full_name(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {"username": "x", "full_name": "   "},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)

    def test_create_requester_rejects_duplicate_username(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {"username": "req_a", "full_name": "Dup"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)

    def test_non_admin_cannot_post_form_config_requesters(self):
        self.client.force_authenticate(self.requester_a)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {"username": "hack", "full_name": "H"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertIn(res.status_code, (403, 401))

    def test_requester_module_catalog_excludes_finance_modules(self):
        """Requester-only user: allowed requests/vendors/notes; not cash/bank/payroll/corporate_card."""
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant, module_key="notes", defaults={"is_enabled": True}
        )
        for key in ("cash", "bank", "payroll", "corporate_card"):
            TenantModuleConfig.objects.update_or_create(
                tenant=self.tenant, module_key=key, defaults={"is_enabled": True}
            )

        solo = User.objects.create_user(username="solo_req", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=solo, is_active=True)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=solo, role=TenantUserRole.ROLE_REQUESTER, step=1
        )

        self.client.force_authenticate(solo)
        res = self.client.get("/api/modules/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        by_key = {m["module_key"]: m for m in res.data["modules"]}
        for k in ("requests", "vendors", "notes"):
            self.assertTrue(by_key[k]["tenant_enabled"], k)
            self.assertTrue(by_key[k]["user_allowed"], k)
        for k in ("cash", "bank", "payroll", "corporate_card"):
            self.assertTrue(by_key[k]["tenant_enabled"], k)
            self.assertFalse(by_key[k]["user_allowed"], k)

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

    def test_default_company_payer_applied_on_create(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(
            config=cfg,
            payment_type="Наличные",
            is_enabled=True,
            default_company_payer="ACME LLC",
        )
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
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["company_payer"], "ACME LLC")

    def test_admin_cannot_assign_requester_outside_form_subset(self):
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
        self.assertEqual(res.status_code, 400)
        self.assertIn("requester", res.data)

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

    def test_form_config_can_set_category_candidates(self):
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "requester_ids": [self.requester_a.id],
                    "vendor_ids": [],
                    "payment_purposes": [{"name": "Office", "category": "Admin", "is_active": True}],
                }
            ],
            "category_candidates": [" Admin ", "Ops", "", "Admin"],
        }
        res = self.client.put("/api/requests/form-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["category_candidates"], ["Admin", "Ops"])

        rows = RequestCategory.objects.filter(tenant=self.tenant, is_active=True).order_by("name")
        self.assertEqual(list(rows.values_list("name", flat=True)), ["Admin", "Ops"])

    def test_form_config_category_candidates_use_request_category_only(self):
        Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.requester_a,
            title="Legacy",
            category="LegacyOnly",
            billing_date=date(2026, 1, 1),
        )
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_cfg,
            name="Legacy purpose",
            category="LegacyPurposeOnly",
            is_active=True,
        )
        RequestCategory.objects.create(tenant=self.tenant, name="ConfiguredCategory", is_active=True)

        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/form-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["category_candidates"], ["ConfiguredCategory"])


@override_settings(BASE_DOMAIN="example.com", N8N_TOKEN="", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestApprovalsTests(APITestCase):
    def setUp(self):
        from django.utils import timezone

        self.timezone = timezone

        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.requester = User.objects.create_user(username="req", password="x")
        self.approver = User.objects.create_user(username="appr", password="x")
        self.other_approver = User.objects.create_user(username="appr_other", password="x")
        self.member_no_approver_role = User.objects.create_user(username="member_plain", password="x")
        # Values used by approval creation logic.
        self.approver.telegram_chat_id = 111
        self.approver.telegram_from_id = 222
        self.approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])

        for u in (self.admin, self.requester, self.approver, self.other_approver, self.member_no_approver_role):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN, step=1)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER, step=1
        )
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER, step=1
        )
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.other_approver, role=TenantUserRole.ROLE_APPROVER, step=1
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

    def test_patch_request_calls_telegram_refresh_and_dispatch(self):
        from unittest.mock import patch

        req_data = self._create_request()
        request_id = req_data["id"]
        self.client.force_authenticate(self.requester)
        with patch(
            "apps.modules.requests.views.refresh_request_messages",
            return_value=0,
        ) as mock_refresh:
            with patch(
                "apps.modules.requests.views.dispatch_pending_approvals",
                return_value=0,
            ) as mock_dispatch:
                res = self.client.patch(
                    f"/api/requests/{request_id}/",
                    {"title": "Updated title"},
                    format="json",
                    HTTP_HOST=self.host,
                )
        self.assertEqual(res.status_code, 200, res.content)
        mock_refresh.assert_called_once()
        mock_dispatch.assert_called_once()

    def test_post_manual_approval_calls_telegram_refresh_and_dispatch(self):
        from unittest.mock import patch

        req_data = self._create_request()
        request_id = req_data["id"]
        self.client.force_authenticate(self.admin)
        with patch(
            "apps.modules.requests.views.refresh_request_messages",
            return_value=0,
        ) as mock_refresh:
            with patch(
                "apps.modules.requests.views.dispatch_pending_approvals",
                return_value=0,
            ) as mock_dispatch:
                res = self.client.post(
                    f"/api/requests/{request_id}/approvals/",
                    {
                        "step": 2,
                        "step_type": Approval.STEP_TYPE_SERIAL,
                        "decision": Approval.DECISION_PENDING,
                        "approver_user": self.other_approver.id,
                    },
                    format="json",
                    HTTP_HOST=self.host,
                )
        self.assertEqual(res.status_code, 201, res.content)
        mock_refresh.assert_called_once()
        mock_dispatch.assert_called_once()

    def test_approvals_confirm_current_step_sets_request_approved(self):
        req_data = self._create_request()
        request_id = req_data["id"]
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver)

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval.id, "comment": "approved from portal"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver)
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)
        self.assertEqual(approval.comment, "approved from portal")
        self.assertIsNotNone(approval.decided_at)

        request_row = Request.objects.get(pk=request_id)
        self.assertEqual(request_row.status, Request.STATUS_APPROVED)

        self.assertEqual(res.data["request"]["id"], request_id)
        self.assertEqual(res.data["trigger_approval"]["id"], approval.id)
        self.assertEqual(len(res.data["approvals"]), 1)

    def test_reject_does_not_dispatch_pending_later_steps(self):
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.get(
            config__tenant=self.tenant, payment_type="Наличные"
        )
        step2 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=2,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
        )
        self.other_approver.telegram_chat_id = 333
        self.other_approver.telegram_from_id = 444
        self.other_approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])
        RequestApprovalStepApproverConfig.objects.create(step_config=step2, approver_user=self.other_approver)

        from unittest.mock import patch

        from apps.modules.requests.approval_workflow import confirm_approval_by_id

        with patch(
            "apps.modules.telegram_approvals.services._post_to_bridge",
            return_value={"message_id": 1},
        ) as mock_bridge:
            req_data = self._create_request()
            mock_bridge.reset_mock()
            request_id = req_data["id"]
            step1_approval = Approval.objects.get(
                request_id=request_id, approver_user=self.approver, step=1
            )
            confirm_approval_by_id(
                tenant=self.tenant,
                approval_id=step1_approval.id,
                request_id=request_id,
                approver_user_id=self.approver.id,
                decision=Approval.DECISION_REJECTED,
                comment="no",
            )
            step2_chat = self.other_approver.telegram_chat_id
            notified_step2 = any(
                (getattr(c, "kwargs", None) or {}).get("payload", {}).get("chat_id") == step2_chat
                for c in mock_bridge.call_args_list
            )
            self.assertFalse(
                notified_step2,
                "Rejected request must not trigger Telegram dispatch to later-step approvers.",
            )

        self.assertEqual(Request.objects.get(pk=request_id).status, Request.STATUS_REJECTED)
        step2_row = Approval.objects.get(request_id=request_id, approver_user=self.other_approver, step=2)
        self.assertEqual(step2_row.decision, Approval.DECISION_REJECTED)

    def test_serial_then_payment_pending_sets_request_approved(self):
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.get(
            config__tenant=self.tenant, payment_type="Наличные"
        )
        step2 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=2,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
            payment_webapp_url="https://acme.example.com/tg/payment?approval_id={approval_id}",
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step2, approver_user=self.other_approver)

        req_data = self._create_request()
        request_id = req_data["id"]
        approval_step1 = Approval.objects.get(
            request_id=request_id, approver_user=self.approver, step=1
        )
        self.assertEqual(Request.objects.get(pk=request_id).status, Request.STATUS_PROGRESS_1)

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval_step1.id, "comment": "ok"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        request_row = Request.objects.get(pk=request_id)
        self.assertEqual(request_row.status, Request.STATUS_APPROVED)
        payment_approval = Approval.objects.get(
            request_id=request_id, approver_user=self.other_approver, step=2
        )
        self.assertEqual(payment_approval.decision, Approval.DECISION_PENDING)
        self.assertEqual(payment_approval.step_type, Approval.STEP_TYPE_PAYMENT)

    def test_approvals_confirm_fails_for_non_assigned_approver(self):
        req_data = self._create_request()
        request_id = req_data["id"]
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver)

        self.client.force_authenticate(self.other_approver)
        res = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval.id, "comment": "attempt"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 403)

    def test_approvals_by_message_id_returns_full_context(self):
        req_data = self._create_request()
        request_id = req_data["id"]
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver)
        approval.message_id = 9001
        approval.message_sent = True
        approval.save(update_fields=["message_id", "message_sent"])

        self.client.force_authenticate(self.approver)
        res = self.client.get(
            "/api/requests/approvals/by-message-id/?message_id=9001",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["request"]["id"], request_id)
        self.assertEqual(res.data["trigger_approval"]["id"], approval.id)
        self.assertEqual(len(res.data["approvals"]), 1)

    def test_approvals_by_message_id_not_found(self):
        self._create_request()
        self.client.force_authenticate(self.approver)
        res = self.client.get(
            "/api/requests/approvals/by-message-id/?message_id=123456",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 404)

    def test_approval_config_allows_any_active_member_and_payment_mode_fields(self):
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": "payment",
                            "is_enabled": True,
                            "approver_user_ids": [self.member_no_approver_role.id],
                            "payment_action_mode": "webapp",
                            "payment_webapp_url": "https://acme.example.com/tg/payment?approval_id={approval_id}",
                        }
                    ],
                }
            ]
        }
        res = self.client.put("/api/requests/approval-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        cash_pt = next(row for row in res.data["payment_types"] if row["payment_type"] == "Наличные")
        step = cash_pt["steps"][0]
        self.assertEqual(step["payment_action_mode"], "webapp")
        self.assertIn("payment_webapp_url", step)
        self.assertIn(
            self.member_no_approver_role.id,
            [row["id"] for row in res.data["approver_candidates"]],
        )

    def test_payment_webapp_confirm_sets_expense_id_and_marks_paid(self):
        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.tenant)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Перечисление", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_action_mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
            payment_webapp_url="https://acme.example.com/tg/payment?approval_id={approval_id}",
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        RequestFormPaymentTypeConfig.objects.create(
            config=RequestFormConfig.objects.get(tenant=self.tenant),
            payment_type="Перечисление",
            is_enabled=True,
        )

        self.client.force_authenticate(self.requester)
        created = self.client.post(
            "/api/requests/",
            {
                "title": "T",
                "description": "",
                "amount": 10,
                "currency": "UZS",
                "payment_type": "Перечисление",
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(created.status_code, 201, created.content)
        request_id = created.data["id"]
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(Request.objects.get(pk=request_id).status, Request.STATUS_APPROVED)

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": "INV-2026-001"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        req = Request.objects.get(id=request_id)
        approval.refresh_from_db()
        self.assertEqual(req.expense_id, "INV-2026-001")
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)

@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
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


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class AutoRequestTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Auto", subdomain="auto", is_active=True)
        self.admin = User.objects.create_user(username="auto_admin", password="x")
        self.requester = User.objects.create_user(username="auto_req", password="x")
        for u in (self.admin, self.requester):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN, step=1)
        TenantUserRole.objects.create(
            tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER, step=1
        )
        self.app_user, app_created = User.objects.get_or_create(
            username="app",
            defaults={"full_name": "Система", "is_active": True},
        )
        if app_created:
            self.app_user.set_unusable_password()
            self.app_user.save(update_fields=["password"])
        TenantMembership.objects.get_or_create(tenant=self.tenant, user=self.app_user, defaults={"is_active": True})
        TenantUserRole.objects.get_or_create(
            tenant=self.tenant, user=self.app_user, role=TenantUserRole.ROLE_REQUESTER, defaults={"step": 1}
        )
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "auto.example.com"

    def _ensure_request_form_for_auto(self) -> Vendor:
        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=req_form_cfg,
            payment_type=Request.PAYMENT_TYPE_CASH,
            is_enabled=True,
            default_company_payer="PayCo LLC",
        )
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester)
        v = Vendor.objects.create(
            tenant=self.tenant, kind="cash", name="Auto Vendor", created_by=self.admin
        )
        RequestFormPaymentTypeVendor.objects.create(payment_type_config=pt_cfg, vendor=v)
        RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_cfg, name="Office", category="Admin", is_active=True
        )
        return v

    def test_template_render_month_ru(self):
        out = render_auto_request_template(
            "Отчет за {{billing_month_ru}}",
            now_dt=datetime(2026, 2, 3, 9, 0, 0),
            billing_month=date(2026, 2, 1),
        )
        self.assertEqual(out, "Отчет за Февраль 2026")

    def test_process_due_auto_requests_creates_once_per_month(self):
        v = self._ensure_request_form_for_auto()
        AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=True,
            name="Monthly",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=1,
            title_template="Заявка {{billing_month_ru}}",
            description_template="Дата {{now:%d.%m.%Y}}",
            requester=self.app_user,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
        )
        n1 = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 2, 10, 0, 0)))
        n2 = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 20, 10, 0, 0)))
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)
        self.assertEqual(Request.objects.filter(tenant=self.tenant).count(), 1)
        req = Request.objects.get(tenant=self.tenant)
        self.assertEqual(req.company_payer, "PayCo LLC")
        self.assertEqual(req.category, "Admin")
        self.assertEqual(req.vendor_ref_id, v.id)
        self.assertEqual(req.requester_id, self.app_user.id)
        self.assertEqual(req.billing_date, date(2026, 2, 1))

    def test_process_due_billing_month_previous(self):
        v = self._ensure_request_form_for_auto()
        AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=True,
            name="Prev",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=5,
            billing_month_mode=AutoRequestTemplate.BILLING_MONTH_PREVIOUS,
            title_template="{{billing_month_ru}}",
            description_template="",
            requester=self.app_user,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
        )
        n = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 3, 5, 10, 0, 0)))
        self.assertEqual(n, 1)
        req = Request.objects.get(tenant=self.tenant)
        self.assertEqual(req.billing_date, date(2026, 2, 1))
        self.assertIn("Февраль", req.title)

    def test_process_due_billing_month_next(self):
        v = self._ensure_request_form_for_auto()
        AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=True,
            name="Next",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=5,
            billing_month_mode=AutoRequestTemplate.BILLING_MONTH_NEXT,
            title_template="T",
            description_template="",
            requester=self.app_user,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
        )
        n = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 3, 5, 10, 0, 0)))
        self.assertEqual(n, 1)
        req = Request.objects.get(tenant=self.tenant)
        self.assertEqual(req.billing_date, date(2026, 4, 1))

    def test_auto_config_put_and_get(self):
        v = self._ensure_request_form_for_auto()
        self.client.force_authenticate(self.admin)
        payload = {
            "templates": [
                {
                    "is_enabled": True,
                    "name": "Rent",
                    "payment_type": "Наличные",
                    "day_of_month": 5,
                    "title_template": "Аренда {{billing_month_ru}}",
                    "description_template": "Платеж за {{billing_month:%B %Y}}",
                    "vendor_ref_id": v.id,
                    "payment_purpose": "Office",
                }
            ]
        }
        put_res = self.client.put("/api/requests/auto-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(put_res.status_code, 200)
        self.assertEqual(len(put_res.data["templates"]), 1)
        self.assertEqual(put_res.data["templates"][0]["requester_id"], self.app_user.id)
        get_res = self.client.get("/api/requests/auto-config/", HTTP_HOST=self.host)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.data["templates"][0]["name"], "Rent")
        self.assertEqual(get_res.data["templates"][0]["requester_id"], self.app_user.id)
        self.assertEqual(get_res.data["templates"][0]["billing_month_mode"], AutoRequestTemplate.BILLING_MONTH_CURRENT)
        self.assertIn("form_payment_types", get_res.data)


