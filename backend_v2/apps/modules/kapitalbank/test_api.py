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

    def test_pending_endpoint_isolated_per_tenant(self):
        from apps.tenants.models import Tenant

        self._grant(self.owner, TenantUserRole.ROLE_ADMIN)
        tenant_b = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True)
        KapitalbankConnection.objects.create(tenant=tenant_b, login="IB#b", is_enabled=True)
        BankAccountLink.objects.create(tenant=tenant_b, account_no="20208000111111111111", branch=MFO)

        # Case 1: B's pending link must not leak into A's response.
        data = self._get(self.owner).json()
        self.assertEqual([a["account_no"] for a in data["accounts"]], [ACCOUNT_1])

        # Case 2: A has no connection while B has one -> A is disabled and empty.
        KapitalbankConnection.objects.filter(pk=self.connection.pk).delete()
        res = self._get(self.owner)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"enabled": False, "accounts": []})


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class UntrackedAccountsApiTests(KapitalbankFixtures, APITestCase):
    URL = "/api/kapitalbank/untracked-accounts/"

    def setUp(self):
        self.make_fixtures()
        TenantMembership.objects.create(tenant=self.tenant, user=self.owner, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.owner, role=TenantUserRole.ROLE_ADMIN)

    def _get(self):
        token = str(RefreshToken.for_user(self.owner).access_token)
        return self.client.get(self.URL, HTTP_HOST="kp.example.com", HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_untracked_accounts_pending_and_service(self):
        BankAccountLink.objects.create(
            tenant=self.tenant, account_no="20208000000000000003", branch=MFO, name="Новый", currency="000",
            last_balance="10.5",
        )
        BankAccountLink.objects.create(
            tenant=self.tenant, account_no="20208000000000000002", branch=MFO,
            decision=BankAccountLink.IGNORED, ignore_reason="not ours",
        )
        BankAccountLink.objects.create(
            tenant=self.tenant, account_no="20208000000000000001", branch=MFO,
            decision=BankAccountLink.LINKED, bank_account=self.bank_account1,
        )
        from apps.tenants.models import Tenant

        other = Tenant.objects.create(name="Beta", subdomain="beta", is_active=True)
        BankAccountLink.objects.create(tenant=other, account_no="20208000000000000009", branch=MFO)

        res = self._get()
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual([a["account_no"] for a in data], ["20208000000000000003", "20208000000000000002"])
        self.assertEqual(
            data[0],
            {
                "account_no": "20208000000000000003", "branch": MFO, "name": "Новый", "currency": "000",
                "balance": "10.50", "status": "pending", "reason": "",
            },
        )
        self.assertEqual(data[1]["status"], "service")
        self.assertEqual(data[1]["reason"], "not ours")
        self.assertIsNone(data[1]["balance"])
