from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.modules.clients_debt.models import ClientDebtSnapshot
from apps.modules.clients_debt.serializers import ClientDebtSnapshotSerializer
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ClientDebtApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.admin = User.objects.create_user(username="admin_clients_debt", password="x")
        self.director = User.objects.create_user(username="director_clients_debt", password="x")
        self.cashier = User.objects.create_user(username="cashier_clients_debt", password="x")

        for user in (self.admin, self.director, self.cashier):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.admin, role=TenantUserRole.ROLE_ADMIN)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.director, role=TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.cashier, role=TenantUserRole.ROLE_CASHIER)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="clients_debt", is_enabled=True)

        self.host = "acme.example.com"
        self.row = ClientDebtSnapshot.objects.create(
            tenant=self.tenant,
            snapshot_at=datetime.fromisoformat("2026-04-10T00:00:00+05:00"),
            doc_type="client_debt_total",
            organization="LEMONFIT",
            client="Тураев Артур Таштемирович",
            client_id="000000006",
            debt_sum="8000.00",
            quantity="0.00",
            cert_discount="0.00",
            payload={"source": "test"},
            created_by=self.admin,
        )

    def test_admin_has_access(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/clients-debt/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(len(res.data), 1)

    def test_director_has_access(self):
        self.client.force_authenticate(self.director)
        res = self.client.get("/api/clients-debt/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(len(res.data), 1)

    def test_other_roles_are_forbidden(self):
        self.client.force_authenticate(self.cashier)
        res = self.client.get("/api/clients-debt/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 403, res.content)

    def test_filter_by_client_search(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/clients-debt/?client_search=000000006", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], self.row.id)


@override_settings(TIME_ZONE="Asia/Tashkent", USE_TZ=True)
class ClientDebtSerializerTimezoneTests(APITestCase):
    def test_naive_snapshot_at_is_interpreted_as_tashkent_time(self):
        serializer = ClientDebtSnapshotSerializer(
            data={
                "snapshot_at": "2026-03-01T00:00:00",
                "doc_type": "client_debt_total",
                "organization": "LEMONFIT",
                "client": "Test Client",
                "client_id": "000000001",
                "debt_sum": "100.00",
                "quantity": "1.00",
                "cert_discount": "0.00",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        snapshot_at = serializer.validated_data["snapshot_at"]
        self.assertTrue(timezone.is_aware(snapshot_at))
        self.assertEqual(snapshot_at.utcoffset(), ZoneInfo("Asia/Tashkent").utcoffset(snapshot_at))

