from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.common.test_utils import list_results
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class PortalListPaginationTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PagCo", subdomain="pagco", is_active=True)
        self.admin = User.objects.create_user(username="pag_admin", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.admin, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="requests", is_enabled=True)
        self.host = "pagco.example.com"
        self.client.force_authenticate(self.admin)

    def test_requests_list_returns_cursor_page(self):
        for i in range(3):
            Request.objects.create(
                tenant=self.tenant,
                created_by=self.admin,
                requester=self.admin,
                title=f"Req {i}",
                amount="10.00",
                currency="UZS",
                payment_type=Request.PAYMENT_TYPE_CASH,
                urgency=Request.URGENCY_NORMAL,
                billing_date="2026-01-01",
                status=Request.STATUS_DRAFT,
            )
        res = self.client.get("/api/requests/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("results", res.data)
        self.assertIn("next", res.data)
        rows = list_results(res)
        self.assertEqual(len(rows), 3)
