from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.modules.kapitalbank.fixtures import ACCOUNT_1, MFO, KapitalbankFixtures
from apps.modules.kapitalbank.models import BankAccountLink, KapitalbankConnection
from apps.tenants.models import TenantMembership, TenantUserRole

URL = "/api/kapitalbank/pending-accounts/"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class PendingAccountsApiTests(KapitalbankFixtures, APITestCase):
    def setUp(self):
        self.make_fixtures()
        self.connection = KapitalbankConnection.objects.create(tenant=self.tenant, login="IB#u", is_enabled=True)
        BankAccountLink.objects.create(
            tenant=self.tenant, account_no=ACCOUNT_1, branch=MFO, name="Расчетный счет", currency="000",
            last_balance="460000.5",
        )
        BankAccountLink.objects.create(
            tenant=self.tenant, account_no="20208000904843803004", branch=MFO,
            decision=BankAccountLink.IGNORED, ignore_reason="not ours",
        )

    def _get(self, user):
        token = str(RefreshToken.for_user(user).access_token)
        return self.client.get(URL, HTTP_HOST="kp.example.com", HTTP_AUTHORIZATION=f"Bearer {token}")

    def _grant(self, user, role):
        TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)

    def test_pending_endpoint_lists_unresolved_for_bank_users(self):
        self._grant(self.owner, TenantUserRole.ROLE_ADMIN)
        res = self._get(self.owner)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(len(data["accounts"]), 1)
        acc = data["accounts"][0]
        self.assertEqual(acc["account_no"], ACCOUNT_1)
        self.assertEqual(acc["balance"], "460000.50")
        self.assertEqual(set(acc), {"account_no", "branch", "name", "currency", "balance", "first_seen_at"})

    def test_pending_endpoint_forbidden_without_bank_access(self):
        self._grant(self.owner, TenantUserRole.ROLE_REQUESTER)
        self.assertEqual(self._get(self.owner).status_code, 403)

    def test_pending_endpoint_empty_when_disabled(self):
        self._grant(self.owner, TenantUserRole.ROLE_ADMIN)
        KapitalbankConnection.objects.filter(pk=self.connection.pk).update(is_enabled=False)
        res = self._get(self.owner)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"enabled": False, "accounts": []})
