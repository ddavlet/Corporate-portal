import base64
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from urllib.parse import parse_qs, urlparse

from apps.common.test_utils import list_results
from apps.tenants.models import Tenant, TenantIntegrationConfig, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestCategory,
    RequestComment,
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
    RequestAttachment,
)
from apps.modules.requests.auto_requests import (
    _next_auto_requests_run_at,
    process_due_auto_requests,
    render_auto_request_template,
)
from apps.modules.requests.integration_settings import get_requests_messaging_gateway_settings
from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.corporate_card.models import CardExpense
from apps.modules.vendors.models import Vendor
from apps.modules.contracts.models import Contract
from apps.modules.wallets.models import (
    BankAccount,
    CashRegister,
    CorporateCardAccount,
    Wallet,
)

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestFormConfigTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.director = User.objects.create_user(username="director", password="x")
        self.requester_a = User.objects.create_user(username="req_a", password="x")
        self.requester_b = User.objects.create_user(username="req_b", password="x")

        for u in (self.admin, self.director, self.requester_a, self.requester_b):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester_a, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester_b, role=TenantUserRole.ROLE_REQUESTER)

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

    def test_director_can_get_and_put_form_config(self):
        self.client.force_authenticate(self.director)
        res = self.client.get("/api/requests/form-config/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        payload = {"payment_types": [{"payment_type": "Наличные", "is_enabled": True}]}
        res2 = self.client.put("/api/requests/form-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res2.status_code, 200)

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

    def test_create_requester_rejects_invalid_username(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {"username": "bad username", "full_name": "Valid Full Name"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("username", res.data)

    def test_non_admin_cannot_post_form_config_requesters(self):
        self.client.force_authenticate(self.requester_a)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {"username": "hack", "full_name": "H"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertIn(res.status_code, (403, 401))

    def test_director_can_post_form_config_requesters(self):
        self.client.force_authenticate(self.director)
        res = self.client.post(
            "/api/requests/form-config/requesters/",
            {"username": "dir_req", "full_name": "Director Requester"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

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
        TenantUserRole.objects.create(tenant=self.tenant, user=solo, role=TenantUserRole.ROLE_REQUESTER)

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


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestApprovalsTests(APITestCase):
    def setUp(self):
        from django.utils import timezone

        self.timezone = timezone

        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin", password="x")
        self.director = User.objects.create_user(username="appr_director", password="x")
        self.requester = User.objects.create_user(username="req", password="x")
        self.approver = User.objects.create_user(username="appr", password="x")
        self.other_approver = User.objects.create_user(username="appr_other", password="x")
        self.member_no_approver_role = User.objects.create_user(username="member_plain", password="x")
        # Values used by approval creation logic.
        self.approver.telegram_chat_id = 111
        self.approver.telegram_from_id = 222
        self.approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])

        for u in (self.admin, self.director, self.requester, self.approver, self.other_approver, self.member_no_approver_role):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.other_approver, role=TenantUserRole.ROLE_APPROVER)

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
        self.assertEqual(approval.approver_recipient_id, str(self.approver.telegram_chat_id))
        self.assertEqual(approval.approver_external_user_id, self.approver.telegram_from_id)

        inbox_qs = UserRequestApproval.objects.filter(request_id=request_id, approver_user=self.approver)
        self.assertEqual(inbox_qs.count(), 1)
        inbox = inbox_qs.first()
        self.assertEqual(inbox.decision, Approval.DECISION_PENDING)
        self.assertEqual(inbox.step, 1)
        self.assertEqual(inbox.approver_external_user_id, self.approver.telegram_from_id)

        self.client.force_authenticate(self.approver)
        res = self.client.get("/api/requests/my-approvals/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["request"]["id"], request_id)
        self.assertEqual(len(res.data[0]["approvals"]), 1)
        self.assertEqual(res.data[0]["approvals"][0]["decision"], Approval.DECISION_PENDING)

    @patch("apps.modules.telegram_approvals.services._post_to_gateway")
    def test_notification_step_dispatches_without_buttons_and_auto_approves(self, gateway_mock):
        gateway_mock.return_value = {"message_id": 901}
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.get(
            config__tenant=self.tenant, payment_type="Наличные"
        )
        RequestApprovalStepConfig.objects.filter(payment_type_config=pt_cfg).delete()
        step1 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_NOTIFICATION,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step1, approver_user=self.approver)
        step2 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=2,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step2, approver_user=self.other_approver)
        self.other_approver.telegram_chat_id = 333
        self.other_approver.telegram_from_id = 444
        self.other_approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])

        req_data = self._create_request()
        request_id = req_data["id"]
        notif = Approval.objects.get(request_id=request_id, step=1, approver_user=self.approver)
        serial = Approval.objects.get(request_id=request_id, step=2, approver_user=self.other_approver)
        self.assertEqual(notif.step_type, Approval.STEP_TYPE_NOTIFICATION)
        self.assertEqual(notif.decision, Approval.DECISION_APPROVED)
        self.assertTrue(notif.message_sent)
        self.assertEqual(serial.decision, Approval.DECISION_PENDING)

        calls = [c.kwargs["payload"] for c in gateway_mock.call_args_list]
        notify_sends = [
            p
            for p in calls
            if p.get("approval_id") == str(notif.id) and p.get("buttons") == []
        ]
        serial_sends = [
            p
            for p in calls
            if p.get("approval_id") == str(serial.id) and p.get("buttons")
        ]
        self.assertTrue(notify_sends, "ожидался send notification без кнопок")
        self.assertTrue(serial_sends, "ожидался send serial с кнопками")
        self.assertLess(calls.index(notify_sends[0]), calls.index(serial_sends[0]))

    def test_cannot_manually_confirm_notification_step(self):
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.get(
            config__tenant=self.tenant, payment_type="Наличные"
        )
        RequestApprovalStepConfig.objects.filter(payment_type_config=pt_cfg).delete()
        step1 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_NOTIFICATION,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step1, approver_user=self.approver)

        req_data = self._create_request()
        request_id = req_data["id"]
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver)
        approval.decision = Approval.DECISION_PENDING
        approval.message_sent = False
        approval.gateway_message_id = None
        approval.save(update_fields=["decision", "message_sent", "gateway_message_id"])

        from rest_framework.exceptions import ValidationError

        from apps.modules.requests.approval_workflow import confirm_approval_by_id

        with self.assertRaises(ValidationError) as ctx:
            confirm_approval_by_id(
                tenant=self.tenant,
                approval_id=approval.id,
                approver_user_id=self.approver.id,
                decision=Approval.DECISION_APPROVED,
            )
        self.assertIn("notification", str(ctx.exception.detail).lower())

    def test_approver_list_shows_only_participating_or_requester_requests(self):
        req_data = self._create_request()
        visible_request_id = req_data["id"]

        hidden_request = Request.objects.create(
            tenant=self.tenant,
            created_by=self.requester,
            requester=self.requester,
            title="Hidden from approver",
            description="",
            amount=Decimal("15"),
            currency="UZS",
            payment_type="Наличные",
            urgency="Обычно",
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        Approval.objects.filter(request=hidden_request).delete()
        UserRequestApproval.objects.filter(request=hidden_request).delete()

        own_request = Request.objects.create(
            tenant=self.tenant,
            created_by=self.approver,
            requester=self.approver,
            title="Own requester draft",
            description="",
            amount=Decimal("20"),
            currency="UZS",
            payment_type="Наличные",
            urgency="Обычно",
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )

        self.client.force_authenticate(self.approver)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        ids = {row["id"] for row in list_results(res)}
        self.assertIn(visible_request_id, ids)
        self.assertIn(own_request.id, ids)
        self.assertNotIn(hidden_request.id, ids)

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

        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.requester,
            requester=self.requester,
            title="D",
            description="",
            amount=Decimal("1"),
            currency="UZS",
            payment_type="Наличные",
            urgency="Обычно",
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        self.client.force_authenticate(self.requester)
        with patch(
            "apps.modules.telegram_approvals.services.refresh_request_messages",
            return_value=0,
        ) as mock_refresh:
            with patch(
                "apps.modules.telegram_approvals.services.dispatch_pending_approvals",
                return_value=0,
            ) as mock_dispatch:
                res = self.client.patch(
                    f"/api/requests/{req.id}/",
                    {"title": "Updated title"},
                    format="json",
                    HTTP_HOST=self.host,
                )
        self.assertEqual(res.status_code, 200, res.content)
        mock_refresh.assert_called_once()
        # DRAFT has no approval step in progress: workflow refreshes state only.
        mock_dispatch.assert_not_called()

    def test_copy_request_creates_new_draft_for_actor(self):
        self.client.force_authenticate(self.requester)
        create_res = self.client.post(
            "/api/requests/",
            {
                "title": "Source",
                "description": "Original description",
                "amount": 150,
                "currency": "USD",
                "payment_type": "Наличные",
                "urgency": "Срочно",
                "billing_date": "2026-03-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(create_res.status_code, 201, create_res.content)
        source_id = create_res.data["id"]

        copier = User.objects.create_user(username="copy_actor", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=copier, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=copier, role=TenantUserRole.ROLE_REQUESTER)
        self.client.force_authenticate(copier)
        res = self.client.post(
            f"/api/requests/{source_id}/copy/",
            {},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIn("request_id", res.data)

        copied = Request.objects.get(pk=res.data["request_id"])
        source = Request.objects.get(pk=source_id)
        self.assertEqual(copied.status, Request.STATUS_DRAFT)
        self.assertEqual(copied.created_by_id, copier.id)
        self.assertEqual(copied.requester_id, copier.id)
        self.assertEqual(copied.description, source.description)
        self.assertEqual(copied.amount, source.amount)
        self.assertEqual(copied.currency, source.currency)
        self.assertEqual(copied.payment_type, source.payment_type)
        self.assertEqual(copied.urgency, source.urgency)
        self.assertEqual(copied.billing_date, source.billing_date)

    def test_post_manual_approval_calls_telegram_refresh_and_dispatch(self):
        from unittest.mock import patch

        req_data = self._create_request()
        request_id = req_data["id"]
        self.client.force_authenticate(self.admin)
        with patch(
            "apps.modules.telegram_approvals.services.refresh_request_messages",
            return_value=0,
        ) as mock_refresh:
            with patch(
                "apps.modules.telegram_approvals.services.dispatch_pending_approvals",
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

    def test_director_can_resend_approvals(self):
        req_data = self._create_request()
        request_id = req_data["id"]

        self.client.force_authenticate(self.director)
        with patch("apps.modules.requests.views.resend_current_pending_step", return_value=1):
            with patch("apps.modules.requests.views.route_request_approvals", return_value=None):
                res = self.client.post(
                    f"/api/requests/{request_id}/approvals/resend/",
                    {},
                    format="json",
                    HTTP_HOST=self.host,
                )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["resent"], 1)

    def test_cannot_confirm_or_decide_inactive_step_while_earlier_step_pending(self):
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

        req_data = self._create_request()
        request_id = req_data["id"]
        step2_approval = Approval.objects.get(
            request_id=request_id, approver_user=self.other_approver, step=2
        )

        self.client.force_authenticate(self.other_approver)
        res_confirm = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": step2_approval.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res_confirm.status_code, 400, res_confirm.content)

        res_decision = self.client.post(
            f"/api/requests/{request_id}/approvals/decision/",
            {"step": 2, "decision": Approval.DECISION_APPROVED},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res_decision.status_code, 400, res_decision.content)

        step2_approval.refresh_from_db()
        self.assertEqual(step2_approval.decision, Approval.DECISION_PENDING)

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
            "apps.modules.telegram_approvals.services._post_to_gateway",
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
                (getattr(c, "kwargs", None) or {}).get("payload", {}).get("recipient_id") == str(step2_chat)
                for c in mock_bridge.call_args_list
            )
            self.assertFalse(
                notified_step2,
                "Rejected request must not trigger Telegram dispatch to later-step approvers.",
            )

        self.assertEqual(Request.objects.get(pk=request_id).status, Request.STATUS_REJECTED)
        step2_row = Approval.objects.get(request_id=request_id, approver_user=self.other_approver, step=2)
        self.assertEqual(step2_row.decision, Approval.DECISION_CANCELED)

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

    def test_request_detail_exposes_payment_action_mode_for_payment_step(self):
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
        approval_step1 = Approval.objects.get(request_id=request_id, approver_user=self.approver, step=1)
        self.client.force_authenticate(self.approver)
        approve_res = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval_step1.id, "comment": "ok"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(approve_res.status_code, 200, approve_res.content)

        self.client.force_authenticate(self.other_approver)
        res = self.client.get(f"/api/requests/{request_id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        payment_rows = [a for a in res.data.get("approvals", []) if a.get("step_type") == Approval.STEP_TYPE_PAYMENT]
        self.assertEqual(len(payment_rows), 1)
        self.assertEqual(payment_rows[0].get("payment_action_mode"), RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP)

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
        approval.gateway_message_id = 9001
        approval.message_sent = True
        approval.save(update_fields=["gateway_message_id", "message_sent"])

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

    def test_director_can_put_approval_config(self):
        self.client.force_authenticate(self.director)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": "serial",
                            "is_enabled": True,
                            "approver_user_ids": [self.member_no_approver_role.id],
                        }
                    ],
                }
            ]
        }
        res = self.client.put("/api/requests/approval-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)

    def test_director_cannot_manage_request_not_required_rules(self):
        self.client.force_authenticate(self.director)
        payload = {
            "payment_types": [
                {
                    "payment_type": "Наличные",
                    "is_enabled": True,
                    "request_not_required_rules": [
                        {"field": "title", "operator": "eq", "value": "Optional"}
                    ],
                    "steps": [
                        {
                            "step": 1,
                            "step_type": "serial",
                            "is_enabled": True,
                            "approver_user_ids": [self.member_no_approver_role.id],
                        }
                    ],
                }
            ]
        }
        res = self.client.put("/api/requests/approval-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 403, res.content)

    def test_approval_purpose_exception_overrides_base_steps(self):
        form_cfg = RequestFormConfig.objects.get(tenant=self.tenant)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.get(config=form_cfg, payment_type=Request.PAYMENT_TYPE_CASH)
        tax_purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg,
            name="Налог на прибыль",
            category="Налоги",
            is_active=True,
        )
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": Request.PAYMENT_TYPE_CASH,
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": Approval.STEP_TYPE_SERIAL,
                            "is_enabled": True,
                            "approver_user_ids": [self.approver.id],
                        }
                    ],
                    "purpose_exceptions": [
                        {
                            "name": "Налоги согласует директор",
                            "is_enabled": True,
                            "payment_purpose_ids": [tax_purpose.id],
                            "steps": [
                                {
                                    "step": 1,
                                    "step_type": Approval.STEP_TYPE_SERIAL,
                                    "is_enabled": True,
                                    "approver_user_ids": [self.other_approver.id],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        res = self.client.put("/api/requests/approval-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)

        self.client.force_authenticate(self.requester)
        created = self.client.post(
            "/api/requests/",
            {
                "title": "Tax request",
                "description": "",
                "amount": 10,
                "currency": "UZS",
                "payment_type": Request.PAYMENT_TYPE_CASH,
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
                "payment_purpose": "Налог на прибыль",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(created.status_code, 201, created.content)
        request_id = created.data["id"]
        self.assertTrue(Approval.objects.filter(request_id=request_id, approver_user=self.other_approver).exists())
        self.assertFalse(Approval.objects.filter(request_id=request_id, approver_user=self.approver).exists())

    def test_approval_purpose_exception_fallbacks_to_base_steps_when_not_matched(self):
        form_cfg = RequestFormConfig.objects.get(tenant=self.tenant)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.get(config=form_cfg, payment_type=Request.PAYMENT_TYPE_CASH)
        tax_purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg,
            name="НДС",
            category="Налоги",
            is_active=True,
        )
        base_purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg,
            name="Офисные расходы",
            category="Операционные",
            is_active=True,
        )
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": Request.PAYMENT_TYPE_CASH,
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": Approval.STEP_TYPE_SERIAL,
                            "is_enabled": True,
                            "approver_user_ids": [self.approver.id],
                        }
                    ],
                    "purpose_exceptions": [
                        {
                            "name": "НДС",
                            "is_enabled": True,
                            "payment_purpose_ids": [tax_purpose.id],
                            "steps": [
                                {
                                    "step": 1,
                                    "step_type": Approval.STEP_TYPE_SERIAL,
                                    "is_enabled": True,
                                    "approver_user_ids": [self.other_approver.id],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        res = self.client.put("/api/requests/approval-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)

        self.client.force_authenticate(self.requester)
        created = self.client.post(
            "/api/requests/",
            {
                "title": "Base flow",
                "description": "",
                "amount": 10,
                "currency": "UZS",
                "payment_type": Request.PAYMENT_TYPE_CASH,
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
                "payment_purpose": base_purpose.name,
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(created.status_code, 201, created.content)
        request_id = created.data["id"]
        self.assertTrue(Approval.objects.filter(request_id=request_id, approver_user=self.approver).exists())

    def test_approval_purpose_exception_rejects_duplicate_purpose_in_multiple_exceptions(self):
        form_cfg = RequestFormConfig.objects.get(tenant=self.tenant)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.get(config=form_cfg, payment_type=Request.PAYMENT_TYPE_CASH)
        tax_purpose = RequestPaymentPurposeConfig.objects.create(
            payment_type_config=pt_form_cfg,
            name="Соцналог",
            category="Налоги",
            is_active=True,
        )
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": Request.PAYMENT_TYPE_CASH,
                    "is_enabled": True,
                    "steps": [],
                    "purpose_exceptions": [
                        {
                            "name": "E1",
                            "is_enabled": True,
                            "payment_purpose_ids": [tax_purpose.id],
                            "steps": [],
                        },
                        {
                            "name": "E2",
                            "is_enabled": True,
                            "payment_purpose_ids": [tax_purpose.id],
                            "steps": [],
                        },
                    ],
                }
            ]
        }
        res = self.client.put("/api/requests/approval-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400, res.content)

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
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        bank_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.BANK,
            currency="UZS",
            bank_account=bank_account,
        )
        bank_expense = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 1, 2),
            process_date=date(2026, 1, 2),
            expense_year=2026,
            expense_month=1,
            expense_day=2,
            doc_no="INV-2026-001",
            debit_turnover=Decimal("10.00"),
            payment_purpose="x",
            wallet=bank_wallet,
        )
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
                "expense_year": 2026,
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
        self.assertEqual(req.expense_ref_id, bank_expense.id)
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(approval.decision, Approval.DECISION_APPROVED)

    @override_settings(N8N_INTERNAL_BASE_URL="")
    @patch("apps.modules.n8n_integration.event_handlers.threading.Thread")
    @patch("apps.modules.n8n_integration.views._n8n_session.post")
    def test_payment_webapp_confirm_sends_n8n_payed_event(self, mock_n8n_post, mock_thread):
        mock_n8n_post.return_value = MagicMock(status_code=200, content=b"{}")
        mock_thread.side_effect = lambda target, daemon: Mock(start=target)

        # Provide an integration token via the tenant config so that
        # notify_request_payed passes the token guard (class-level settings
        # keep N8N_INTEGRATION_TOKEN="" intentionally).
        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        cfg.set_n8n_integration_token("test-integ-token")
        cfg.save()

        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_TRANSFER)
        approval = Approval.objects.get(
            request_id=request_id,
            approver_user=self.approver,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        bank_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.BANK,
            currency="UZS",
            bank_account=bank_account,
        )
        BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 1, 2),
            process_date=date(2026, 1, 2),
            expense_year=2026,
            expense_month=1,
            expense_day=2,
            doc_no="INV-2026-002",
            debit_turnover=Decimal("10.00"),
            payment_purpose="x",
            wallet=bank_wallet,
        )

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": "INV-2026-002"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        target = None
        for call in mock_n8n_post.call_args_list:
            if call.args and "new-payed-request" in str(call.args[0]):
                target = call
                break
        self.assertIsNotNone(target, mock_n8n_post.call_args_list)
        self.assertEqual(target.args[0], "https://acme.example.com/n8n/events/new-payed-request")
        self.assertEqual(target.kwargs.get("timeout"), 10)
        self.assertEqual(target.kwargs["json"]["id"], request_id)
        self.assertEqual(target.kwargs["json"]["status"], Request.STATUS_PAYED)

    def test_payment_webapp_confirm_cash_resolves_numeric_expense_id_to_canonical(self):
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_CASH,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_CASH)
        approval = Approval.objects.get(
            request_id=request_id,
            approver_user=self.approver,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        cash_expense = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="1-000000343",
            confirmed=True,
            title="Resolved cash expense",
            amount=Decimal("10.00"),
            currency="UZS",
            expense_at=datetime(2026, 1, 2, 10, 0, 0),
            expense_year=2026,
            expense_month=1,
            expense_day=2,
            created_by=self.admin,
            wallet=cash_wallet,
        )

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": "343"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.expense_ref_id, cash_expense.id)
        self.assertEqual(req.expense_id, "1-000000343")

    def test_payment_webapp_confirm_cash_zero_pad_without_prefix_resolves_short_id(self):
        self.tenant.cash_expense_external_id_prefix = ""
        self.tenant.cash_expense_external_id_digit_width = 11
        self.tenant.save(update_fields=["cash_expense_external_id_prefix", "cash_expense_external_id_digit_width"])

        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_CASH,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_CASH)
        approval = Approval.objects.get(
            request_id=request_id,
            approver_user=self.approver,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main cash pad")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        cash_expense = CashExpense.objects.create(
            tenant=self.tenant,
            external_id="00000000459",
            confirmed=True,
            title="Padded id expense",
            amount=Decimal("10.00"),
            currency="UZS",
            expense_at=datetime(2026, 1, 2, 10, 0, 0),
            expense_year=2026,
            expense_month=1,
            expense_day=2,
            created_by=self.admin,
            wallet=cash_wallet,
        )

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": "459"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.expense_ref_id, cash_expense.id)
        self.assertEqual(req.expense_id, "00000000459")

    def test_payment_webapp_confirm_bank_resolves_same_doc_no_by_amount(self):
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_TRANSFER)
        approval = Approval.objects.get(
            request_id=request_id,
            approver_user=self.approver,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        bank_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.BANK,
            currency="UZS",
            bank_account=bank_account,
        )
        wrong_amount_expense = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 1, 2),
            process_date=date(2026, 1, 2),
            expense_year=2026,
            expense_month=1,
            expense_day=2,
            doc_no="DUP-2026-001",
            debit_turnover=Decimal("20.00"),
            payment_purpose="wrong amount",
            wallet=bank_wallet,
        )
        matching_expense = BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=2,
            doc_date=date(2026, 1, 3),
            process_date=date(2026, 1, 3),
            expense_year=2026,
            expense_month=1,
            expense_day=3,
            doc_no="DUP-2026-001",
            debit_turnover=Decimal("10.00"),
            payment_purpose="matching amount",
            wallet=bank_wallet,
        )

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": "DUP-2026-001"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)

        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.expense_ref_id, matching_expense.id)
        self.assertNotEqual(req.expense_ref_id, wrong_amount_expense.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)

    def test_payment_webapp_confirm_cash_skips_link_when_amount_mismatch(self):
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_CASH,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_CASH)
        approval = Approval.objects.get(
            request_id=request_id,
            approver_user=self.approver,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Cash amount")
        cash_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        CashExpense.objects.create(
            tenant=self.tenant,
            external_id="CASH-AMT-1",
            confirmed=True,
            title="Wrong amount expense",
            amount=Decimal("99.00"),
            currency="UZS",
            expense_at=datetime(2026, 1, 2, 10, 0, 0),
            expense_year=2026,
            expense_month=1,
            expense_day=2,
            created_by=self.admin,
            wallet=cash_wallet,
        )

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": "CASH-AMT-1"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.expense_id, "CASH-AMT-1")
        self.assertIsNone(req.expense_ref_id)

    def test_payment_webapp_confirm_card_skips_link_when_amount_mismatch(self):
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant,
            module_key="corporate_card",
            defaults={"is_enabled": True},
        )
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_CARD,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_CARD)
        approval = Approval.objects.get(
            request_id=request_id,
            approver_user=self.approver,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )
        card_account = CorporateCardAccount.objects.create(tenant=self.tenant, currency="UZS", label="Corp amt")
        card_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CORPORATE_CARD,
            currency="UZS",
            corporate_card_account=card_account,
        )
        card_expense = CardExpense.objects.create(
            tenant=self.tenant,
            title="Card wrong amount",
            amount=Decimal("99.00"),
            currency="UZS",
            expense_at=datetime(2026, 1, 2, 10, 0, 0),
            created_by=self.admin,
            wallet=card_wallet,
        )

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": str(card_expense.id)},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.expense_id, str(card_expense.id))
        self.assertIsNone(req.expense_ref_id)

    def test_payment_webapp_confirm_bank_skips_link_when_only_amount_mismatch(self):
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_WEBAPP,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_TRANSFER)
        approval = Approval.objects.get(
            request_id=request_id,
            approver_user=self.approver,
            step_type=Approval.STEP_TYPE_PAYMENT,
        )
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Bank amt only")
        bank_wallet = Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.BANK,
            currency="UZS",
            bank_account=bank_account,
        )
        BankExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            row_no=1,
            doc_date=date(2026, 1, 2),
            process_date=date(2026, 1, 2),
            expense_year=2026,
            expense_month=1,
            expense_day=2,
            doc_no="BANK-AMT-ONLY",
            debit_turnover=Decimal("99.00"),
            payment_purpose="wrong amount only",
            wallet=bank_wallet,
        )

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            "/api/requests/approvals/payment-webapp/confirm/",
            {"approval_id": approval.id, "expense_id": "BANK-AMT-ONLY"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.expense_id, "BANK-AMT-ONLY")
        self.assertIsNone(req.expense_ref_id)

    def _configure_payment_step(self, *, payment_type: str, mode: str) -> None:
        appr_cfg = RequestApprovalConfig.objects.get(tenant=self.tenant)
        RequestApprovalPaymentTypeConfig.objects.filter(
            config=appr_cfg,
            payment_type=payment_type,
        ).delete()
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg,
            payment_type=payment_type,
            is_enabled=True,
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_PAYMENT,
            is_enabled=True,
            payment_action_mode=mode,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)
        RequestFormPaymentTypeConfig.objects.update_or_create(
            config=RequestFormConfig.objects.get(tenant=self.tenant),
            payment_type=payment_type,
            defaults={"is_enabled": True},
        )

    def _create_request_for_payment_type(self, payment_type: str) -> int:
        self.client.force_authenticate(self.requester)
        created = self.client.post(
            "/api/requests/",
            {
                "title": f"{payment_type} request",
                "description": "auto",
                "amount": "10.00",
                "currency": "UZS",
                "payment_type": payment_type,
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
                "expense_year": 2026,
                "expense_month": 1,
                "expense_day": 2,
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(created.status_code, 201, created.content)
        return created.data["id"]

    def test_payment_create_mode_creates_cash_expense_and_links_request(self):
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant,
            module_key="cash",
            defaults={"is_enabled": True},
        )
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CASH,
            currency="UZS",
            cash_register=cash_register,
        )
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_CASH,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_CASH)
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver, step_type=Approval.STEP_TYPE_PAYMENT)

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CASH)
        self.assertTrue(CashExpense.objects.filter(tenant=self.tenant, id=req.expense_ref_id).exists())

    def test_payment_create_mode_creates_bank_expense_and_links_request(self):
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant,
            module_key="bank",
            defaults={"is_enabled": True},
        )
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.BANK,
            currency="UZS",
            bank_account=bank_account,
        )
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_TRANSFER)
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver, step_type=Approval.STEP_TYPE_PAYMENT)

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_BANK)
        self.assertTrue(BankExpense.objects.filter(tenant=self.tenant, id=req.expense_ref_id).exists())

    def test_payment_create_mode_creates_card_expense_and_links_request(self):
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant,
            module_key="corporate_card",
            defaults={"is_enabled": True},
        )
        card_account = CorporateCardAccount.objects.create(tenant=self.tenant, currency="UZS", label="Corp")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.CORPORATE_CARD,
            currency="UZS",
            corporate_card_account=card_account,
        )
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_CARD,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_CARD)
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver, step_type=Approval.STEP_TYPE_PAYMENT)

        self.client.force_authenticate(self.approver)
        res = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req = Request.objects.get(pk=request_id)
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD)
        self.assertTrue(CardExpense.objects.filter(tenant=self.tenant, id=req.expense_ref_id).exists())

    def test_payment_create_mode_disallowed_when_target_module_disabled(self):
        self.client.force_authenticate(self.admin)
        payload = {
            "payment_types": [
                {
                    "payment_type": Request.PAYMENT_TYPE_TRANSFER,
                    "is_enabled": True,
                    "steps": [
                        {
                            "step": 1,
                            "step_type": Approval.STEP_TYPE_PAYMENT,
                            "is_enabled": True,
                            "approver_user_ids": [self.approver.id],
                            "payment_action_mode": RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE,
                        }
                    ],
                }
            ]
        }
        res = self.client.put("/api/requests/approval-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400, res.content)

    def test_payment_create_mode_is_idempotent_on_repeat_confirm(self):
        TenantModuleConfig.objects.update_or_create(
            tenant=self.tenant,
            module_key="bank",
            defaults={"is_enabled": True},
        )
        bank_account = BankAccount.objects.create(tenant=self.tenant, label="Main")
        Wallet.objects.create(
            tenant=self.tenant,
            wallet_type=Wallet.Type.BANK,
            currency="UZS",
            bank_account=bank_account,
        )
        self._configure_payment_step(
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            mode=RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE,
        )
        request_id = self._create_request_for_payment_type(Request.PAYMENT_TYPE_TRANSFER)
        approval = Approval.objects.get(request_id=request_id, approver_user=self.approver, step_type=Approval.STEP_TYPE_PAYMENT)

        self.client.force_authenticate(self.approver)
        first = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(first.status_code, 200, first.content)
        second = self.client.post(
            f"/api/requests/{request_id}/approvals/confirm/",
            {"approval_id": approval.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(second.status_code, 409, second.content)
        self.assertEqual(BankExpense.objects.filter(tenant=self.tenant).count(), 1)

@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestFileLinkRewriteTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.requester = User.objects.create_user(username="req", password="x")

        TenantMembership.objects.create(tenant=self.tenant, user=self.requester, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)

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
class RequestAttachmentsTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Attach", subdomain="attach", is_active=True)
        self.requester = User.objects.create_user(username="att_req", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.requester, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.requester)
        RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        self.host = "attach.example.com"
        self.client.force_authenticate(self.requester)
        created = self.client.post(
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
        self.request_id = created.data["id"]

    def _upload(self, name: str, content: bytes, content_type: str):
        file_obj = SimpleUploadedFile(name=name, content=content, content_type=content_type)
        return self.client.post(
            f"/api/requests/{self.request_id}/file-upload/",
            {"file": file_obj},
            HTTP_HOST=self.host,
        )

    def test_upload_valid_attachment(self):
        res = self._upload("ok.pdf", b"dummy", "application/pdf")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(RequestAttachment.objects.filter(request_id=self.request_id).count(), 1)

    def test_reject_unsupported_extension(self):
        res = self._upload("bad.exe", b"dummy", "application/octet-stream")
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("file", res.data)

    def test_reject_file_too_large(self):
        res = self._upload("big.pdf", b"a" * (10 * 1024 * 1024 + 1), "application/pdf")
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("file", res.data)

    def test_reject_more_than_five_attachments(self):
        for idx in range(5):
            ok = self._upload(f"ok-{idx}.pdf", b"ok", "application/pdf")
            self.assertEqual(ok.status_code, 200, ok.content)
        blocked = self._upload("blocked.pdf", b"ok", "application/pdf")
        self.assertEqual(blocked.status_code, 400, blocked.content)
        self.assertIn("file", blocked.data)

    def test_delete_attachment_only_for_draft(self):
        uploaded = self._upload("to-delete.pdf", b"ok", "application/pdf")
        self.assertEqual(uploaded.status_code, 200, uploaded.content)
        attachment_id = uploaded.data["id"]

        req = Request.objects.get(pk=self.request_id)
        req.status = Request.STATUS_APPROVED
        req.save(update_fields=["status"])

        res = self.client.delete(
            f"/api/requests/{self.request_id}/attachments/{attachment_id}/",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)
        self.assertTrue(RequestAttachment.objects.filter(id=attachment_id).exists())

@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class AutoRequestTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Auto", subdomain="auto", is_active=True)
        self.admin = User.objects.create_user(username="auto_admin", password="x")
        self.director = User.objects.create_user(username="auto_director", password="x")
        self.approver = User.objects.create_user(username="auto_appr_cfg", password="x")
        self.requester = User.objects.create_user(username="auto_req", password="x")
        for u in (self.admin, self.director, self.approver, self.requester):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        self.app_user, app_created = User.objects.get_or_create(
            username="app",
            defaults={"full_name": "Система", "is_active": True},
        )
        if app_created:
            self.app_user.set_unusable_password()
            self.app_user.save(update_fields=["password"])
        TenantMembership.objects.get_or_create(tenant=self.tenant, user=self.app_user, defaults={"is_active": True})
        TenantUserRole.objects.get_or_create(tenant=self.tenant, user=self.app_user, role=TenantUserRole.ROLE_REQUESTER)
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

    def test_next_auto_requests_run_at_same_day_morning(self):
        now_dt = timezone.make_aware(datetime(2026, 2, 3, 7, 15, 0), ZoneInfo("Asia/Tashkent"))
        run_dt = _next_auto_requests_run_at(now_dt)
        local_run_dt = timezone.localtime(run_dt, ZoneInfo("Asia/Tashkent"))
        self.assertEqual(local_run_dt, datetime(2026, 2, 3, 8, 0, 0, tzinfo=ZoneInfo("Asia/Tashkent")))

    def test_next_auto_requests_run_at_next_day_after_8am(self):
        now_dt = timezone.make_aware(datetime(2026, 2, 3, 8, 1, 0), ZoneInfo("Asia/Tashkent"))
        run_dt = _next_auto_requests_run_at(now_dt)
        local_run_dt = timezone.localtime(run_dt, ZoneInfo("Asia/Tashkent"))
        self.assertEqual(local_run_dt, datetime(2026, 2, 4, 8, 0, 0, tzinfo=ZoneInfo("Asia/Tashkent")))

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
        n1 = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 1, 10, 0, 0)))
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

    def test_process_due_auto_requests_runs_only_on_exact_run_day(self):
        v = self._ensure_request_form_for_auto()
        AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=True,
            name="ExactDayOnly",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=10,
            title_template="Exact",
            description_template="",
            requester=self.app_user,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
        )
        before_day = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 9, 10, 0, 0)))
        run_day = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 10, 10, 0, 0)))
        after_day = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 11, 10, 0, 0)))
        self.assertEqual(before_day, 0)
        self.assertEqual(run_day, 1)
        self.assertEqual(after_day, 0)
        self.assertEqual(Request.objects.filter(tenant=self.tenant).count(), 1)

    def test_process_due_auto_requests_day_31_runs_on_short_month_last_day(self):
        v = self._ensure_request_form_for_auto()
        AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=True,
            name="Day31",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=31,
            title_template="ShortMonth",
            description_template="",
            requester=self.app_user,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
        )
        before_last_day = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 27, 10, 0, 0)))
        last_day = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 28, 10, 0, 0)))
        self.assertEqual(before_last_day, 0)
        self.assertEqual(last_day, 1)
        self.assertEqual(Request.objects.filter(tenant=self.tenant).count(), 1)

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
        self.assertEqual(req.title, self.tenant.name)

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
                    "requester_id": self.requester.id,
                }
            ]
        }
        put_res = self.client.put("/api/requests/auto-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(put_res.status_code, 200)
        self.assertEqual(len(put_res.data["templates"]), 1)
        self.assertEqual(put_res.data["templates"][0]["requester_id"], self.requester.id)
        get_res = self.client.get("/api/requests/auto-config/", HTTP_HOST=self.host)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.data["templates"][0]["name"], "Rent")
        self.assertEqual(get_res.data["templates"][0]["requester_id"], self.requester.id)
        self.assertIn("requester_candidates", get_res.data)
        self.assertEqual(get_res.data["templates"][0]["billing_month_mode"], AutoRequestTemplate.BILLING_MONTH_CURRENT)
        self.assertIn("form_payment_types", get_res.data)

    def test_auto_config_create_copy_ignores_template_run_day(self):
        v = self._ensure_request_form_for_auto()
        self.client.force_authenticate(self.admin)
        today = timezone.localdate()
        not_today_run_day = 1 if today.day != 1 else 2
        template = AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=False,
            name="Manual copy",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=not_today_run_day,
            title_template="Копия {{billing_month_ru}}",
            description_template="",
            requester=self.requester,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
        )

        res = self.client.post(
            "/api/requests/auto-config/",
            {"template_id": template.id},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIn("request_id", res.data)
        self.assertEqual(Request.objects.filter(tenant=self.tenant).count(), 1)
        req = Request.objects.get(tenant=self.tenant, id=res.data["request_id"])
        self.assertEqual(req.requester_id, self.requester.id)
        self.assertEqual(req.vendor_ref_id, v.id)
        self.assertEqual(req.billing_date, today.replace(day=1))

    def test_auto_config_director_allowed(self):
        v = self._ensure_request_form_for_auto()
        self.client.force_authenticate(self.director)
        payload = {
            "templates": [
                {
                    "is_enabled": True,
                    "name": "Director template",
                    "payment_type": "Наличные",
                    "day_of_month": 7,
                    "title_template": "Director {{billing_month_ru}}",
                    "description_template": "",
                    "vendor_ref_id": v.id,
                    "payment_purpose": "Office",
                    "requester_id": self.requester.id,
                }
            ]
        }
        put_res = self.client.put("/api/requests/auto-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(put_res.status_code, 200, put_res.content)
        get_res = self.client.get("/api/requests/auto-config/", HTTP_HOST=self.host)
        self.assertEqual(get_res.status_code, 200, get_res.content)

    def test_auto_config_approver_forbidden(self):
        v = self._ensure_request_form_for_auto()
        self.client.force_authenticate(self.approver)
        payload = {
            "templates": [
                {
                    "is_enabled": True,
                    "name": "Approver template",
                    "payment_type": "Наличные",
                    "day_of_month": 10,
                    "title_template": "Шаблон {{billing_month_ru}}",
                    "description_template": "",
                    "vendor_ref_id": v.id,
                    "payment_purpose": "Office",
                    "requester_id": self.requester.id,
                }
            ]
        }
        put_res = self.client.put("/api/requests/auto-config/", payload, format="json", HTTP_HOST=self.host)
        self.assertEqual(put_res.status_code, 403, put_res.content)
        get_res = self.client.get("/api/requests/auto-config/", HTTP_HOST=self.host)
        self.assertEqual(get_res.status_code, 403, get_res.content)

    def test_auto_config_requester_forbidden(self):
        self.client.force_authenticate(self.requester)
        get_res = self.client.get("/api/requests/auto-config/", HTTP_HOST=self.host)
        self.assertEqual(get_res.status_code, 403, get_res.content)

    @patch("apps.modules.requests.auto_requests.dispatch_draft_request_notification")
    def test_process_due_auto_without_amount_stays_draft_and_notifies(self, mock_dispatch):
        v = self._ensure_request_form_for_auto()
        self.requester.telegram_chat_id = 900_001
        self.requester.save(update_fields=["telegram_chat_id"])
        AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=True,
            name="NoAmt",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=1,
            title_template="Черновик {{billing_month_ru}}",
            description_template="",
            requester=self.requester,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
            amount=None,
        )
        n = process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 1, 10, 0, 0)))
        self.assertEqual(n, 1)
        req = Request.objects.get(tenant=self.tenant)
        self.assertEqual(req.status, Request.STATUS_DRAFT)
        self.assertEqual(req.amount, Decimal("0"))
        self.assertEqual(Approval.objects.filter(request=req).count(), 0)
        mock_dispatch.assert_called_once()
        call_kw = mock_dispatch.call_args.kwargs
        self.assertEqual(call_kw["request_obj"].id, req.id)
        self.assertEqual(call_kw["chat_id"], 900_001)

    def test_process_due_auto_with_amount_still_creates_approvals(self):
        v = self._ensure_request_form_for_auto()
        self.approver = User.objects.create_user(username="auto_appr", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.approver, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
        self.approver.telegram_chat_id = 111
        self.approver.save(update_fields=["telegram_chat_id"])
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type=Request.PAYMENT_TYPE_CASH, is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg, step=1, step_type=Approval.STEP_TYPE_SERIAL, is_enabled=True
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)

        AutoRequestTemplate.objects.create(
            tenant=self.tenant,
            is_enabled=True,
            name="WithAmt",
            payment_type=Request.PAYMENT_TYPE_CASH,
            day_of_month=1,
            title_template="Сумма",
            description_template="",
            requester=self.requester,
            updated_by=self.admin,
            vendor_ref=v,
            payment_purpose="Office",
            amount=Decimal("5000"),
        )
        process_due_auto_requests(now_dt=timezone.make_aware(datetime(2026, 2, 1, 10, 0, 0)))
        req = Request.objects.get(tenant=self.tenant)
        self.assertNotEqual(req.status, Request.STATUS_DRAFT)
        self.assertGreaterEqual(Approval.objects.filter(request=req).count(), 1)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestRoleVisibilityTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Roles", subdomain="roles", is_active=True)
        self.admin = User.objects.create_user(username="rv_admin", password="x")
        self.director = User.objects.create_user(username="rv_dir", password="x")
        self.accountant = User.objects.create_user(username="rv_acc", password="x")
        self.cashier = User.objects.create_user(username="rv_cash", password="x")
        for u in (self.admin, self.director, self.accountant, self.cashier):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.accountant, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.cashier, role=TenantUserRole.ROLE_CASHIER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "roles.example.com"

        for idx, pt in enumerate(
            [
                Request.PAYMENT_TYPE_CASH,
                Request.PAYMENT_TYPE_TRANSFER,
                Request.PAYMENT_TYPE_TOPUP,
                Request.PAYMENT_TYPE_CARD,
            ],
            start=1,
        ):
            Request.objects.create(
                tenant=self.tenant,
                created_by=self.admin,
                requester=self.admin,
                title=f"Req {idx}",
                description="",
                amount=Decimal("100"),
                currency="UZS",
                payment_type=pt,
                urgency=Request.URGENCY_NORMAL,
                billing_date=date(2026, 1, 1),
                status=Request.STATUS_DRAFT,
                submitted_at=timezone.now(),
                company_payer="",
            )

    def test_accountant_sees_only_transfer_topup_and_card_requests(self):
        self.client.force_authenticate(self.accountant)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        visible_types = {row["payment_type"] for row in list_results(res)}
        self.assertEqual(
            visible_types,
            {
                Request.PAYMENT_TYPE_TRANSFER,
                Request.PAYMENT_TYPE_TOPUP,
                Request.PAYMENT_TYPE_CARD,
            },
        )

    def test_cashier_sees_only_cash_requests(self):
        self.client.force_authenticate(self.cashier)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        visible_types = {row["payment_type"] for row in list_results(res)}
        self.assertEqual(visible_types, {Request.PAYMENT_TYPE_CASH})

    def test_admin_sees_all_requests(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        visible_types = {row["payment_type"] for row in list_results(res)}
        self.assertEqual(
            visible_types,
            {
                Request.PAYMENT_TYPE_CASH,
                Request.PAYMENT_TYPE_TRANSFER,
                Request.PAYMENT_TYPE_TOPUP,
                Request.PAYMENT_TYPE_CARD,
            },
        )

    def test_director_sees_all_requests(self):
        self.client.force_authenticate(self.director)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        visible_types = {row["payment_type"] for row in list_results(res)}
        self.assertEqual(
            visible_types,
            {
                Request.PAYMENT_TYPE_CASH,
                Request.PAYMENT_TYPE_TRANSFER,
                Request.PAYMENT_TYPE_TOPUP,
                Request.PAYMENT_TYPE_CARD,
            },
        )

    def test_requester_sees_only_where_he_is_requester(self):
        requester = User.objects.create_user(username="rv_req", password="x")
        created_only = User.objects.create_user(username="rv_created_only", password="x")
        for u in (requester, created_only):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
            TenantUserRole.objects.create(tenant=self.tenant, user=u, role=TenantUserRole.ROLE_REQUESTER)

        visible = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=requester,
            title="Visible requester row",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        hidden = Request.objects.create(
            tenant=self.tenant,
            created_by=requester,
            requester=created_only,
            title="Hidden created_by row",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )

        self.client.force_authenticate(requester)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        ids = {row["id"] for row in list_results(res)}
        self.assertIn(visible.id, ids)
        self.assertNotIn(hidden.id, ids)

    def test_requester_with_finance_role_still_sees_own_auto_like_draft(self):
        requester = User.objects.create_user(username="rv_req_fin", password="x")
        other = User.objects.create_user(username="rv_req_fin_other", password="x")
        for u in (requester, other):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
            TenantUserRole.objects.create(tenant=self.tenant, user=u, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(
            tenant=self.tenant,
            user=requester,
            role=TenantUserRole.ROLE_ACCOUNTANT,
        )

        visible = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=requester,
            title="Own cash draft",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        hidden = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=other,
            title="Other user cash draft",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )

        self.client.force_authenticate(requester)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        ids = {row["id"] for row in list_results(res)}
        self.assertIn(visible.id, ids)
        self.assertNotIn(hidden.id, ids)

    def test_approver_with_finance_role_still_sees_assigned_request(self):
        approver = User.objects.create_user(username="rv_appr_fin", password="x")
        other = User.objects.create_user(username="rv_appr_fin_other", password="x")
        for u in (approver, other):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=approver, role=TenantUserRole.ROLE_APPROVER)
        TenantUserRole.objects.create(tenant=self.tenant, user=approver, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantUserRole.objects.create(tenant=self.tenant, user=other, role=TenantUserRole.ROLE_REQUESTER)

        visible_req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=other,
            title="Assigned cash request",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_PROGRESS_1,
            submitted_at=timezone.now(),
            company_payer="",
        )
        hidden_req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=other,
            title="Not assigned cash request",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_PROGRESS_1,
            submitted_at=timezone.now(),
            company_payer="",
        )
        Approval.objects.create(
            request=visible_req,
            approver_user=approver,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            decision=Approval.DECISION_PENDING,
        )

        self.client.force_authenticate(approver)
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        ids = {row["id"] for row in list_results(res)}
        self.assertIn(visible_req.id, ids)
        self.assertNotIn(hidden_req.id, ids)

    def test_list_can_filter_amortized_only(self):
        amortized = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Amortized",
            description="",
            amount=Decimal("1200"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            amortization_months=6,
            amortization_start_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        plain = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Plain",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            amortization_months=1,
            amortization_start_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/requests/?amortized_only=1", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        ids = {row["id"] for row in list_results(res)}
        self.assertIn(amortized.id, ids)
        self.assertNotIn(plain.id, ids)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class PayedMissingExpenseFilterTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PayedGap", subdomain="payedgap", is_active=True)
        self.admin = User.objects.create_user(username="payedgap_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        self.host = "payedgap.example.com"
        self.client.force_authenticate(self.admin)

    def test_payed_missing_expense_filter_excludes_linked_cash(self):
        from apps.modules.cashier.models import CashExpense
        from apps.modules.wallets.models import CashRegister, Wallet

        register = CashRegister.objects.create(
            tenant=self.tenant,
            name="Main",
            currency="UZS",
            is_active=True,
            sort_order=1,
        )
        wallet = Wallet.objects.create(tenant=self.tenant, type=Wallet.Type.CASH, cash_register=register)
        expense = CashExpense.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            wallet=wallet,
            external_id="E-1",
            expense_year=2026,
            title="Office",
            amount="50.00",
            currency="UZS",
            expense_at=timezone.now(),
        )
        missing = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Paid no link",
            amount="10.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_PAYED,
        )
        linked = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Paid with cash",
            amount="50.00",
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_PAYED,
            expense_ref_id=expense.id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CASH,
            expense_id=expense.external_id,
            expense_year=expense.expense_year,
        )
        res = self.client.get("/api/requests/?payed_missing_expense=1", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        ids = {row["id"] for row in list_results(res)}
        self.assertIn(missing.id, ids)
        self.assertNotIn(linked.id, ids)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class AuditMonthShiftsTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="AuditCo", subdomain="auditco", is_active=True)
        self.admin = User.objects.create_user(username="audit_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "auditco.example.com"

        # Minimal request-form config so `payment_type` is allowed.
        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        RequestFormPaymentTypeConfig.objects.create(config=req_form_cfg, payment_type=Request.PAYMENT_TYPE_CASH, is_enabled=True)

        self.client.force_authenticate(self.admin)

    def test_audit_month_shifts_returns_only_shifted_or_amortized(self):
        shifted_posted_in_march = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Shifted A",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 2, 1),
            expense_year=2026,
            expense_month=3,
            expense_day=1,
            amortization_months=1,
            amortization_start_date=date(2026, 2, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        shifted_billed_in_march = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Shifted B",
            description="",
            amount=Decimal("200"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            expense_year=2026,
            expense_month=2,
            expense_day=1,
            amortization_months=1,
            amortization_start_date=date(2026, 3, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        plain = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Plain",
            description="",
            amount=Decimal("300"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 3, 1),
            expense_year=2026,
            expense_month=3,
            expense_day=1,
            amortization_months=1,
            amortization_start_date=date(2026, 3, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )
        amortized = Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Amortized",
            description="",
            amount=Decimal("600"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CASH,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 1, 1),
            expense_year=2026,
            expense_month=1,
            expense_day=1,
            amortization_months=6,
            amortization_start_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="",
        )

        res = self.client.get("/api/requests/audit-month-shifts/?month=2026-03", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["months"]["current"], "2026-03")
        row_ids = {row["request_id"] for row in res.data.get("rows", [])}
        self.assertIn(shifted_posted_in_march.id, row_ids)
        self.assertIn(shifted_billed_in_march.id, row_ids)
        self.assertIn(amortized.id, row_ids)
        self.assertNotIn(plain.id, row_ids)

        amort_row = next(r for r in res.data["rows"] if r["request_id"] == amortized.id)
        self.assertEqual(amort_row["amortization_months"], 6)
        self.assertIsNotNone(amort_row["amort_current"])


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class DraftRequestPatchSubmitTests(APITestCase):
    """DRAFT-only PATCH and submit-for-approval."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="DraftCo", subdomain="draftco", is_active=True)
        self.admin = User.objects.create_user(username="d_admin", password="x")
        self.requester = User.objects.create_user(username="d_req", password="x")
        self.other = User.objects.create_user(username="d_other", password="x")
        self.approver = User.objects.create_user(username="d_appr", password="x")
        self.approver.telegram_chat_id = 222
        self.approver.save(update_fields=["telegram_chat_id"])
        self.director = User.objects.create_user(username="d_dir", password="x")
        for u in (self.admin, self.requester, self.other, self.approver, self.director):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.other, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "draftco.example.com"

        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=req_form_cfg, payment_type="Наличные", is_enabled=True
        )
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester)

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        apt = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type="Наличные", is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=apt, step=1, step_type=Approval.STEP_TYPE_SERIAL, is_enabled=True
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)

    def _draft_request(self):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.requester,
            requester=self.requester,
            title="Черновик",
            description="",
            amount=Decimal("0"),
            currency="UZS",
            payment_type="Наличные",
            urgency="Обычно",
            billing_date=date(2026, 1, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="Co",
        )

    def test_cannot_patch_non_draft(self):
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
        self.assertEqual(res.status_code, 201)
        rid = res.data["id"]
        res2 = self.client.patch(
            f"/api/requests/{rid}/",
            {"title": "X"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res2.status_code, 400, res2.content)

    def test_admin_can_patch_non_draft(self):
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
        self.assertEqual(res.status_code, 201, res.content)
        rid = res.data["id"]

        self.client.force_authenticate(self.admin)
        res2 = self.client.patch(
            f"/api/requests/{rid}/",
            {"title": "Updated by admin"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res2.status_code, 200, res2.content)
        self.assertEqual(res2.data["title"], self.tenant.name)

    def test_cannot_patch_draft_as_unrelated_user(self):
        req = self._draft_request()
        # Approver видит все заявки в tenant, но не может править чужой черновик
        self.client.force_authenticate(self.approver)
        res = self.client.patch(
            f"/api/requests/{req.id}/",
            {"title": "Stolen"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 403, res.content)

    def test_director_can_patch_others_draft(self):
        req = self._draft_request()
        self.client.force_authenticate(self.director)
        res = self.client.patch(
            f"/api/requests/{req.id}/",
            {"description": "edited by director"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Request.objects.get(pk=req.id).description, "edited by director")

    def test_create_sets_amortization_defaults_from_billing_date(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "Оборудование",
                "description": "",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-02-20",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["amortization_months"], 1)
        self.assertEqual(res.data["amortization_start_date"], "2026-02-01")
        req = Request.objects.get(pk=res.data["id"])
        self.assertEqual(req.amortization_months, 1)
        self.assertEqual(req.amortization_start_date, date(2026, 2, 1))

    def test_title_is_always_derived_from_tenant_name(self):
        self.client.force_authenticate(self.requester)
        created = self.client.post(
            "/api/requests/",
            {
                "title": "Пользовательский заголовок",
                "description": "",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-02-20",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.data["title"], self.tenant.name)

        req = self._draft_request()
        patched = self.client.patch(
            f"/api/requests/{req.id}/",
            {"title": "Новый заголовок"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        self.assertEqual(patched.data["title"], self.tenant.name)
        self.assertEqual(Request.objects.get(pk=req.id).title, self.tenant.name)

    def test_create_allows_custom_amortization_months(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "Оборудование",
                "description": "",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-02-20",
                "amortization_months": 6,
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["amortization_months"], 6)
        self.assertTrue(res.data["is_amortized"])
        self.assertEqual(len(res.data["amortization_schedule"]), 6)
        req = Request.objects.get(pk=res.data["id"])
        self.assertEqual(req.amortization_months, 6)

    def test_create_rejects_amortization_months_above_six(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "Оборудование",
                "description": "",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-02-20",
                "amortization_months": 7,
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("amortization_months", res.data)

    def test_retrieve_returns_amortization_schedule(self):
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.requester,
            requester=self.requester,
            title="Amortized schedule",
            description="",
            amount=Decimal("100"),
            currency="UZS",
            payment_type="Наличные",
            urgency="Обычно",
            billing_date=date(2026, 2, 20),
            amortization_months=3,
            amortization_start_date=date(2026, 2, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="Co",
        )
        self.client.force_authenticate(self.requester)
        res = self.client.get(f"/api/requests/{req.id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.data["is_amortized"])
        schedule = res.data["amortization_schedule"]
        self.assertEqual(len(schedule), 3)
        self.assertEqual(schedule[0]["period_month"], "2026-02-01")
        self.assertEqual(schedule[-1]["period_month"], "2026-04-01")
        total = sum(Decimal(str(item["monthly_amount"])) for item in schedule)
        self.assertEqual(total, Decimal("100"))

    def test_patch_billing_date_recalculates_amortization_start_date(self):
        req = self._draft_request()
        self.client.force_authenticate(self.requester)
        res = self.client.patch(
            f"/api/requests/{req.id}/",
            {"billing_date": "2026-03-20"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["amortization_start_date"], "2026-03-01")
        req.refresh_from_db()
        self.assertEqual(req.billing_date, date(2026, 3, 20))
        self.assertEqual(req.amortization_start_date, date(2026, 3, 1))

    def test_patch_can_disable_amortization_by_setting_one_month(self):
        req = Request.objects.create(
            tenant=self.tenant,
            created_by=self.requester,
            requester=self.requester,
            title="Amortized request",
            description="",
            amount=Decimal("300"),
            currency="UZS",
            payment_type="Наличные",
            urgency="Обычно",
            billing_date=date(2026, 2, 20),
            amortization_months=6,
            amortization_start_date=date(2026, 2, 1),
            status=Request.STATUS_DRAFT,
            submitted_at=timezone.now(),
            company_payer="Co",
        )
        self.client.force_authenticate(self.requester)
        res = self.client.patch(
            f"/api/requests/{req.id}/",
            {"amortization_months": 1},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["amortization_months"], 1)
        self.assertFalse(res.data["is_amortized"])
        req.refresh_from_db()
        self.assertEqual(req.amortization_months, 1)

    @patch("apps.modules.requests.views.dispatch_pending_approvals", return_value=0)
    def test_submit_for_approval_creates_approvals(self, _mock_dispatch):
        req = self._draft_request()
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            f"/api/requests/{req.id}/submit-for-approval/",
            {"amount": "150.00", "title": "Готово"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req.refresh_from_db()
        self.assertNotEqual(req.status, Request.STATUS_DRAFT)
        self.assertGreaterEqual(Approval.objects.filter(request=req).count(), 1)

    def test_submit_for_approval_twice_returns_409(self):
        req = self._draft_request()
        self.client.force_authenticate(self.requester)
        r1 = self.client.post(
            f"/api/requests/{req.id}/submit-for-approval/",
            {"amount": "50"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(r1.status_code, 200, r1.content)
        r2 = self.client.post(
            f"/api/requests/{req.id}/submit-for-approval/",
            {"amount": "60"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(r2.status_code, 409, r2.content)

    @patch("apps.modules.requests.views.dispatch_pending_approvals", return_value=0)
    def test_auto_draft_submit_amount_updates_and_submits(self, _mock_dispatch):
        req = self._draft_request()
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/auto-draft/submit-amount/",
            {"request_id": req.id, "amount": "250.00"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        req.refresh_from_db()
        self.assertEqual(req.amount, Decimal("250.00"))
        self.assertNotEqual(req.status, Request.STATUS_DRAFT)
        self.assertGreaterEqual(Approval.objects.filter(request=req).count(), 1)

    def test_auto_draft_submit_amount_forbidden_for_unrelated_user(self):
        req = self._draft_request()
        self.client.force_authenticate(self.other)
        res = self.client.post(
            "/api/requests/auto-draft/submit-amount/",
            {"request_id": req.id, "amount": "250.00"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 403, res.content)

    def test_auto_draft_submit_amount_field_uses_decimal_min_not_float(self):
        """DRF emits UserWarning if DecimalField.min_value is a float."""
        from apps.modules.requests.serializers import AutoDraftSubmitAmountPayloadSerializer

        ser = AutoDraftSubmitAmountPayloadSerializer()
        min_v = ser.fields["amount"].min_value
        self.assertIsInstance(min_v, Decimal)
        self.assertEqual(min_v, Decimal("0.01"))

    @patch("apps.modules.telegram_approvals.services._post_to_gateway", return_value={"message_id": 1})
    def test_dispatch_draft_notification_payload(self, mock_post):
        from apps.modules.telegram_approvals.services import dispatch_draft_request_notification

        req = self._draft_request()
        ok = dispatch_draft_request_notification(request_obj=req, chat_id=123, template_id=77)
        self.assertTrue(ok)
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "send")
        self.assertEqual(payload["recipient_id"], "123")
        self.assertIn("кнопкой в этом сообщении", payload["text"])
        self.assertIn("📝 Черновик заявки", payload["text"])
        self.assertIn("💰 Финансы", payload["text"])
        self.assertIn("📌 Назначение", payload["text"])
        self.assertIn("⏱ Статус", payload["text"])
        self.assertIn(
            f"https://{self.tenant.subdomain}.example.com/app/requests/auto-config?template_id=77",
            payload["text"],
        )
        self.assertIn(f"https://{self.tenant.subdomain}.example.com/app/requests/{req.id}", payload["text"])


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestContractsRequiredTests(APITestCase):
    """Portal request creation when contracts_required is enabled on the payment type."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="cr_admin", password="x")
        self.requester = User.objects.create_user(username="cr_req", password="x")
        self.approver = User.objects.create_user(username="cr_appr", password="x")
        self.approver.telegram_chat_id = 501
        self.approver.telegram_from_id = 502
        self.approver.save(update_fields=["telegram_chat_id", "telegram_from_id"])

        for u in (self.admin, self.requester, self.approver):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.approver, role=TenantUserRole.ROLE_APPROVER)

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="vendors", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="contracts", is_enabled=True)

        self.host = "acme.example.com"

        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_form_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=req_form_cfg,
            payment_type=Request.PAYMENT_TYPE_CASH,
            is_enabled=True,
            contracts_required=True,
        )
        self.vendor = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_CASH,
            name="Contract Vendor",
            created_by=self.admin,
        )
        RequestFormPaymentTypeVendor.objects.create(payment_type_config=pt_form_cfg, vendor=self.vendor)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_form_cfg, user=self.requester)

        self.other_vendor = Vendor.objects.create(
            tenant=self.tenant,
            kind=Vendor.KIND_CASH,
            name="Other Vendor",
            created_by=self.admin,
        )

        self.contract = Contract.objects.create(
            tenant=self.tenant,
            vendor=self.vendor,
            contract_number="CV-2026-1",
            date_from=date(2026, 1, 10),
            contract_amount=Decimal("1000.00"),
            currency="UZS",
            contract_status=Contract.STATUS_ACCEPTED,
            created_by=self.admin,
        )
        self.contract_other_vendor = Contract.objects.create(
            tenant=self.tenant,
            vendor=self.other_vendor,
            contract_number="OTHER-1",
            date_from=date(2026, 1, 11),
            contract_amount=Decimal("500.00"),
            currency="UZS",
            contract_status=Contract.STATUS_ACCEPTED,
            created_by=self.admin,
        )

        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg, payment_type=Request.PAYMENT_TYPE_CASH, is_enabled=True
        )
        step_cfg = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt_cfg,
            step=1,
            step_type=Approval.STEP_TYPE_SERIAL,
            is_enabled=True,
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=step_cfg, approver_user=self.approver)

    def _payload(self, **extra):
        base = {
            "title": "With contract",
            "description": "",
            "amount": 10,
            "currency": "UZS",
            "payment_type": Request.PAYMENT_TYPE_CASH,
            "urgency": "Обычно",
            "billing_date": "2026-01-15",
            "vendor_ref": self.vendor.id,
        }
        base.update(extra)
        return base

    def test_contract_required_rejects_missing_contract_ref(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post("/api/requests/", self._payload(), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("contract_ref", res.data)

    def test_contract_required_accepts_matching_contract(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            self._payload(contract_ref=self.contract.id),
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(id=res.data["id"])
        self.assertEqual(req.contract_ref_id, self.contract.id)

    def test_contract_must_match_vendor(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            self._payload(vendor_ref=self.vendor.id, contract_ref=self.contract_other_vendor.id),
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400, res.content)

    def test_contracts_module_disabled_skips_contract_requirement(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="contracts").update(is_enabled=False)
        self.client.force_authenticate(self.requester)
        res = self.client.post("/api/requests/", self._payload(), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.content)
        req = Request.objects.get(id=res.data["id"])
        self.assertIsNone(req.contract_ref_id)

    def test_detail_exposes_created_by_username_and_contract_label(self):
        self.client.force_authenticate(self.requester)
        create = self.client.post(
            "/api/requests/",
            self._payload(contract_ref=self.contract.id),
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(create.status_code, 201, create.content)
        request_id = create.data["id"]
        detail = self.client.get(f"/api/requests/{request_id}/", HTTP_HOST=self.host)
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.data["created_by_username"], self.requester.username)
        self.assertEqual(detail.data["contract_label"], "CV-2026-1")


@override_settings(BASE_DOMAIN="example.com", MESSAGING_GATEWAY_SEND_URL="http://gw.example/v1/messaging/send")
class GetRequestsMessagingGatewaySettingsTests(APITestCase):
    def test_resolves_draft_notification_action_without_crashing(self):
        tenant = Tenant.objects.create(name="Co", subdomain="gwsett", is_active=True)
        settings_obj = get_requests_messaging_gateway_settings(tenant=tenant)
        self.assertEqual(settings_obj.draft_notification_action, "send")

    @override_settings(MESSAGING_GATEWAY_DRAFT_ACTION="send_interactive")
    def test_draft_notification_action_from_django_settings(self):
        tenant = Tenant.objects.create(name="Co2", subdomain="gwsett2", is_active=True)
        settings_obj = get_requests_messaging_gateway_settings(tenant=tenant)
        self.assertEqual(settings_obj.draft_notification_action, "send_interactive")


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="integ-token", ALLOWED_HOSTS=["*"])
class RequestAiChatProxyTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.user = User.objects.create_user(username="req_chat", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_REQUESTER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "acme.example.com"
        cfg, _ = TenantIntegrationConfig.objects.get_or_create(tenant=self.tenant)
        cfg.request_ai_chat_webhook_url = "https://dev.kolberg.uz/webhook/uuid/chat"
        cfg.save(update_fields=["request_ai_chat_webhook_url"])

    @patch("apps.modules.requests.views._n8n_session.post")
    def test_proxy_forwards_to_configured_url_with_integration_token(self, mocked_post):
        mocked_response = MagicMock()
        mocked_response.status_code = 200
        mocked_response.content = b'{"output":"ok"}'
        mocked_response.headers = {"Content-Type": "application/json"}
        mocked_post.return_value = mocked_response

        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/requests/ai-chat/",
            {"action": "sendMessage", "chatInput": "hello", "sessionId": "s1"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json(), {"output": "ok"})

        mocked_post.assert_called_once()
        self.assertEqual(mocked_post.call_args.args[0], "https://dev.kolberg.uz/webhook/uuid/chat")
        headers = mocked_post.call_args.kwargs["headers"]
        self.assertEqual(headers["X-N8N-Integration-Token"], "integ-token")
        expected = "Basic " + base64.b64encode(b"X-N8N-Integration-Token:integ-token").decode("ascii")
        self.assertEqual(headers["Authorization"], expected)

    @patch("apps.modules.requests.views._n8n_session.post")
    def test_n8n_auth_failure_returns_502_not_opaque_401(self, mocked_post):
        mocked_response = MagicMock()
        mocked_response.status_code = 401
        mocked_response.content = b"Authorization is required!"
        mocked_response.headers = {"Content-Type": "text/plain"}
        mocked_post.return_value = mocked_response

        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/requests/ai-chat/",
            {"action": "sendMessage"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 502)
        self.assertIn("n8n rejected", res.json()["detail"])

    def test_missing_webhook_url_returns_503(self):
        cfg = TenantIntegrationConfig.objects.get(tenant=self.tenant)
        cfg.request_ai_chat_webhook_url = ""
        cfg.save(update_fields=["request_ai_chat_webhook_url"])

        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/requests/ai-chat/",
            {"action": "sendMessage"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 503)

    def test_requires_auth(self):
        res = self.client.post(
            "/api/requests/ai-chat/",
            {"action": "sendMessage"},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 401)


@override_settings(BASE_DOMAIN="example.com", N8N_INTEGRATION_TOKEN="", ALLOWED_HOSTS=["*"])
class RequestCommentTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.requester = User.objects.create_user(username="req_comment", password="x")
        self.other = User.objects.create_user(username="other_member", password="x")
        self.outsider = User.objects.create_user(username="outsider", password="x")

        for u in (self.requester, self.other):
            TenantMembership.objects.create(tenant=self.tenant, user=u, is_active=True)

        TenantUserRole.objects.create(tenant=self.tenant, user=self.requester, role=TenantUserRole.ROLE_REQUESTER)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.other, role=TenantUserRole.ROLE_APPROVER)

        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)

        self.host = "acme.example.com"

        req_form_cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.requester)
        RequestFormPaymentTypeConfig.objects.create(config=req_form_cfg, payment_type="Наличные", is_enabled=True)

        self.client.force_authenticate(self.requester)
        res = self.client.post(
            "/api/requests/",
            {
                "title": "Test request",
                "description": "",
                "amount": 100,
                "currency": "UZS",
                "payment_type": "Наличные",
                "urgency": "Обычно",
                "billing_date": "2026-01-01",
            },
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.request_id = res.json()["id"]

    def _url(self):
        return f"/api/requests/{self.request_id}/comments/"

    def test_post_comment_creates_and_returns_201(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(self._url(), {"body": "Первый комментарий"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual(data["body"], "Первый комментарий")
        self.assertEqual(data["created_by"], self.requester.pk)
        self.assertTrue(RequestComment.objects.filter(pk=data["id"]).exists())

    def test_get_comments_returns_list(self):
        RequestComment.objects.create(request_id=self.request_id, created_by=self.requester, body="Комментарий A")
        RequestComment.objects.create(request_id=self.request_id, created_by=self.other, body="Комментарий B")
        self.client.force_authenticate(self.requester)
        res = self.client.get(self._url(), HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        bodies = [c["body"] for c in res.json()]
        self.assertIn("Комментарий A", bodies)
        self.assertIn("Комментарий B", bodies)

    def test_post_empty_body_returns_400(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(self._url(), {"body": "   "}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400, res.content)

    def test_post_too_long_body_returns_400(self):
        self.client.force_authenticate(self.requester)
        res = self.client.post(self._url(), {"body": "x" * 4001}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400, res.content)

    def test_outsider_cannot_comment(self):
        self.client.force_authenticate(self.outsider)
        res = self.client.post(self._url(), {"body": "Не должен попасть"}, format="json", HTTP_HOST=self.host)
        self.assertIn(res.status_code, (403, 404))

    def test_unauthenticated_cannot_comment(self):
        self.client.logout()
        res = self.client.post(self._url(), {"body": "Анонимный комментарий"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 401)

    def test_comments_appear_in_request_detail(self):
        RequestComment.objects.create(request_id=self.request_id, created_by=self.requester, body="Видимый")
        self.client.force_authenticate(self.requester)
        res = self.client.get(f"/api/requests/{self.request_id}/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        comments = res.json().get("comments", [])
        self.assertTrue(any(c["body"] == "Видимый" for c in comments))


