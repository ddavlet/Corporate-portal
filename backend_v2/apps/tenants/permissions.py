from rest_framework.permissions import BasePermission

from apps.tenants.models import TenantMembership, TenantModuleConfig, UserModulePermission
from django.contrib.auth.models import AnonymousUser


class IsTenantAdmin(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not user or not user.is_authenticated or not tenant:
            return False
        return TenantMembership.objects.filter(
            user=user, tenant=tenant, is_active=True, role=TenantMembership.ROLE_TENANT_ADMIN
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

        # Tenant admin bypass.
        if TenantMembership.objects.filter(
            user=user,
            tenant=tenant,
            is_active=True,
            role=TenantMembership.ROLE_TENANT_ADMIN,
        ).exists():
            return True

        tenant_enabled = TenantModuleConfig.objects.filter(
            tenant=tenant, module_key=module_key, is_enabled=True
        ).exists()
        if not tenant_enabled:
            return False

        user_allowed = UserModulePermission.objects.filter(
            tenant=tenant, user=user, module_key=module_key, can_access=True
        ).exists()
        return user_allowed


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

    # Tenant admin bypass.
    if TenantMembership.objects.filter(
        user=user,
        tenant=tenant,
        is_active=True,
        role=TenantMembership.ROLE_TENANT_ADMIN,
    ).exists():
        return True

    tenant_enabled = TenantModuleConfig.objects.filter(
        tenant=tenant, module_key=module_key, is_enabled=True
    ).exists()
    if not tenant_enabled:
        return False

    user_allowed = UserModulePermission.objects.filter(
        tenant=tenant, user=user, module_key=module_key, can_access=True
    ).exists()
    return user_allowed

