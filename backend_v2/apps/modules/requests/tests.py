from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole
from apps.modules.requests.models import (
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestPaymentPurposeConfig,
)

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com")
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
            "/api/requests/upsert/",
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
            "/api/requests/upsert/",
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
        self.assertEqual(res.data["request"]["category"], "Admin")

    def test_admin_can_assign_requester_outside_form_subset(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester_a)

        self.client.force_authenticate(self.admin)
        res = self.client.post(
            "/api/requests/upsert/",
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
        self.assertEqual(res.data["request"]["requester"], self.requester_b.id)

    def test_non_admin_rejected_when_self_not_in_requester_subset(self):
        cfg = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(config=cfg, payment_type="Наличные", is_enabled=True)
        RequestFormPaymentTypeRequester.objects.create(payment_type_config=pt_cfg, user=self.requester_a)

        self.client.force_authenticate(self.requester_b)
        res = self.client.post(
            "/api/requests/upsert/",
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
            "/api/requests/upsert/",
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
        self.assertEqual(res.data["request"]["requester"], self.requester_a.id)

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

