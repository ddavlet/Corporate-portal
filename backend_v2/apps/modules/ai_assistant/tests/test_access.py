from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.modules.ai_assistant.access import assistant_enabled, portal_identity, resolve_assistant_user
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()
TG_ID = 777001


class AccessTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)

    def _member(self, username, role, tenant=None, tg_id=TG_ID, active=True, chat_id=None):
        tenant = tenant or self.tenant
        user = User.objects.create_user(username=username, password="x", telegram_from_id=tg_id, telegram_chat_id=chat_id)
        TenantMembership.objects.create(user=user, tenant=tenant, is_active=active)
        if role:
            TenantUserRole.objects.create(tenant=tenant, user=user, role=role)
        return user

    def test_allowed_director_ok(self):
        user = self._member("dir", TenantUserRole.ROLE_DIRECTOR)
        result = resolve_assistant_user(self.tenant, TG_ID)
        self.assertEqual(result.reason, "ok")
        self.assertEqual(result.user, user)
        self.assertIn(TenantUserRole.ROLE_DIRECTOR, result.roles)

    def test_investor_ok(self):
        self._member("inv", TenantUserRole.ROLE_INVESTOR)
        self.assertEqual(resolve_assistant_user(self.tenant, TG_ID).reason, "ok")

    def test_cashier_role_not_allowed(self):
        self._member("cash", TenantUserRole.ROLE_CASHIER)
        self.assertEqual(resolve_assistant_user(self.tenant, TG_ID).reason, "role_not_allowed")

    def test_inactive_membership_not_member(self):
        self._member("dir", TenantUserRole.ROLE_DIRECTOR, active=False)
        self.assertEqual(resolve_assistant_user(self.tenant, TG_ID).reason, "not_member")

    def test_other_tenant_member_not_member(self):
        self._member("dir", TenantUserRole.ROLE_DIRECTOR, tenant=self.other)
        self.assertEqual(resolve_assistant_user(self.tenant, TG_ID).reason, "not_member")

    def test_chat_id_match_is_not_used(self):
        self._member("dir", TenantUserRole.ROLE_DIRECTOR, tg_id=None, chat_id=TG_ID)
        self.assertEqual(resolve_assistant_user(self.tenant, TG_ID).reason, "not_member")

    def test_two_users_same_tg_id_ambiguous(self):
        self._member("dir1", TenantUserRole.ROLE_DIRECTOR)
        self._member("dir2", TenantUserRole.ROLE_ADMIN)
        result = resolve_assistant_user(self.tenant, TG_ID)
        self.assertEqual(result.reason, "ambiguous_user")
        self.assertIsNone(result.user)

    def test_disabled_module_or_mcp_disables_assistant(self):
        self.assertFalse(assistant_enabled(self.tenant))
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="ai_assistant", is_enabled=True)
        self.assertFalse(assistant_enabled(self.tenant))  # mcp disabled
        self.tenant.mcp_enabled = True
        self.tenant.save()
        self.assertTrue(assistant_enabled(self.tenant))
        TenantModuleConfig.objects.filter(tenant=self.tenant).update(is_enabled=False)
        self.assertFalse(assistant_enabled(self.tenant))

    def test_portal_identity_returns_sorted_roles(self):
        user = self._member("dir", TenantUserRole.ROLE_DIRECTOR)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=TenantUserRole.ROLE_ADMIN)
        found, roles = portal_identity(self.tenant, TG_ID)
        self.assertEqual(found, user)
        self.assertEqual(roles, "admin,director")
        self.assertEqual(portal_identity(self.tenant, 1), (None, ""))
