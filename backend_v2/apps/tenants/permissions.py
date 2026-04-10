from rest_framework.permissions import SAFE_METHODS, BasePermission

from django.contrib.auth.models import AnonymousUser

from apps.tenants.models import TenantMembership, TenantModuleConfig, TenantUserRole
# ROLE_REQUESTER is intentionally limited to request-related modules (requests, vendors, notes).
# Do not add ROLE_REQUESTER to cash, bank, payroll, corporate_card, or similar unless a real
# request workflow needs it; prefer other roles for finance surfaces.

ROLE_MODULE_ACCESS: dict[str, set[str]] = {
    "requests": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_APPROVER,
        TenantUserRole.ROLE_REQUESTER,
        TenantUserRole.ROLE_ACCOUNTANT,
        TenantUserRole.ROLE_CASHIER,
    },
    "vendors": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_APPROVER,
        TenantUserRole.ROLE_REQUESTER,
        TenantUserRole.ROLE_CASHIER,
        TenantUserRole.ROLE_ACCOUNTANT,
    },
    "cash": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_CASHIER,
    },
    "bank": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_ACCOUNTANT,
    },
    "payroll": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_ACCOUNTANT,
    },
    "corporate_card": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_ACCOUNTANT,
        TenantUserRole.ROLE_CASHIER,
    },
    "wallets": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_ACCOUNTANT,
        TenantUserRole.ROLE_CASHIER,
    },
    "reports": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_ACCOUNTANT,
        TenantUserRole.ROLE_CASHIER,
    },
    "clients_debt": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
    },
    "notes": {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_DIRECTOR,
        TenantUserRole.ROLE_APPROVER,
        TenantUserRole.ROLE_REQUESTER,
        TenantUserRole.ROLE_CASHIER,
        TenantUserRole.ROLE_ACCOUNTANT,
    },
}


def _has_active_membership(*, user, tenant) -> bool:
    return TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists()


def _user_has_any_role(*, user, tenant, roles: set[str]) -> bool:
    if not roles:
        return False
    return TenantUserRole.objects.filter(tenant=tenant, user=user, role__in=roles).exists()


def role_allows_module(*, user, tenant, module_key: str) -> bool:
    """
    Role-based access for a module within a tenant.
    Requires active membership AND at least one role granting the module.
    """
    if not module_key:
        return False
    if not _has_active_membership(user=user, tenant=tenant):
        return False
    roles = ROLE_MODULE_ACCESS.get(module_key, set())
    return _user_has_any_role(user=user, tenant=tenant, roles=roles)


class IsTenantAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not user or not user.is_authenticated or not tenant:
            return False
        # Tenant "admin" is now just a tenant role.
        if not _has_active_membership(user=user, tenant=tenant):
            return False
        return TenantUserRole.objects.filter(
            tenant=tenant,
            user=user,
            role=TenantUserRole.ROLE_ADMIN,
        ).exists()


class IsTenantAdminOrDirector(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not user or not user.is_authenticated or not tenant:
            return False
        if not _has_active_membership(user=user, tenant=tenant):
            return False
        return TenantUserRole.objects.filter(
            tenant=tenant,
            user=user,
            role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR],
        ).exists()


class IsTenantAdminOrApprover(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not user or not user.is_authenticated or not tenant:
            return False
        if not _has_active_membership(user=user, tenant=tenant):
            return False
        return TenantUserRole.objects.filter(
            tenant=tenant,
            user=user,
            role__in=[TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_APPROVER],
        ).exists()


WALLETS_FINANCIAL_WRITE_ROLES = frozenset(
    {
        TenantUserRole.ROLE_ADMIN,
        TenantUserRole.ROLE_ACCOUNTANT,
    }
)


class HasWalletsFinancialWriteAccess(BasePermission):
    """
    Within the wallets module: GET/HEAD/OPTIONS always allowed (after HasEffectiveModuleAccess).
    Mutations require admin or accountant (cashier is read-only for cash registers / wallet metadata).
    """

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not user.is_authenticated or not tenant:
            return False
        return TenantUserRole.objects.filter(
            tenant=tenant, user=user, role__in=WALLETS_FINANCIAL_WRITE_ROLES
        ).exists()


class HasEffectiveModuleAccess(BasePermission):
    """
    Guard DRF views by `module_key`.
    Put `module_key = "requests"` on the view class.
    """

    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        module_key = getattr(view, "module_key", None)
        if not module_key or not user or not user.is_authenticated or not tenant:
            return False

        tenant_enabled = TenantModuleConfig.objects.filter(
            tenant=tenant, module_key=module_key, is_enabled=True
        ).exists()
        if not tenant_enabled:
            return False

        return role_allows_module(user=user, tenant=tenant, module_key=module_key)


def has_effective_module_access(*, user, tenant, module_key: str) -> bool:
    """
    Shared helper for non-view code (e.g. serializers) to check effective access.
    Mirrors `HasEffectiveModuleAccess.has_permission`.
    """
    if not module_key or not user or isinstance(user, AnonymousUser):
        return False
    if not tenant:
        return False
    if not user.is_authenticated:
        return False

    tenant_enabled = TenantModuleConfig.objects.filter(
        tenant=tenant, module_key=module_key, is_enabled=True
    ).exists()
    if not tenant_enabled:
        return False

    return role_allows_module(user=user, tenant=tenant, module_key=module_key)

