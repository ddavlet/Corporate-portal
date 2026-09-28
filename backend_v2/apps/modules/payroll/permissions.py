from rest_framework.permissions import BasePermission

from apps.modules.payroll.constants import MODULE_KEY
from apps.tenants.models import TenantModuleConfig
from apps.tenants.permissions import role_allows_module


def _enabled(tenant, key: str) -> bool:
    return TenantModuleConfig.objects.filter(tenant=tenant, module_key=key, is_enabled=True).exists()


class HasPayrollPayoutAccess(BasePermission):
    """Payroll module enabled for the tenant and the user has payroll access, or
    cash access with the cash module enabled (cashier paying from the cash section)."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if not user or not user.is_authenticated or not tenant or not _enabled(tenant, MODULE_KEY):
            return False
        if role_allows_module(user=user, tenant=tenant, module_key=MODULE_KEY):
            return True
        return _enabled(tenant, "cash") and role_allows_module(user=user, tenant=tenant, module_key="cash")
