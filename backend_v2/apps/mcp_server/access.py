"""Who may see and call an MCP tool: module + role rules, evaluated per request."""

from __future__ import annotations

from dataclasses import dataclass

from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import ROLE_MODULE_ACCESS

_ADMIN_OR_DIRECTOR = frozenset({TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR})


@dataclass(frozen=True)
class Access:
    kind: str  # "always" | "module" | "admin" | "admin_or_director"
    module_key: str | None = None
    require_admin_or_director: bool = False

    @classmethod
    def always(cls) -> "Access":
        return cls("always")

    @classmethod
    def module(cls, key: str, *, admin_or_director: bool = False) -> "Access":
        return cls("module", key, admin_or_director)

    @classmethod
    def admin(cls) -> "Access":
        return cls("admin")

    @classmethod
    def admin_or_director(cls) -> "Access":
        return cls("admin_or_director")

    def allows(self, roles: set[str], enabled_modules: set[str]) -> bool:
        if self.kind == "always":
            return True
        if self.kind == "admin":
            return TenantUserRole.ROLE_ADMIN in roles
        if self.kind == "admin_or_director":
            return bool(roles & _ADMIN_OR_DIRECTOR)
        if self.module_key not in enabled_modules:
            return False
        if not roles & ROLE_MODULE_ACCESS.get(self.module_key, set()):
            return False
        return not self.require_admin_or_director or bool(roles & _ADMIN_OR_DIRECTOR)


def visible_tools(registry: dict[str, Access], *, user_id: int, tenant_id: int) -> set[str]:
    """Names of tools the user may use in the tenant; empty for non-members."""
    from apps.tenants.models import TenantMembership, TenantModuleConfig

    if not TenantMembership.objects.filter(user_id=user_id, tenant_id=tenant_id, is_active=True).exists():
        return set()
    roles = set(
        TenantUserRole.objects.filter(user_id=user_id, tenant_id=tenant_id).values_list("role", flat=True)
    )
    modules = set(
        TenantModuleConfig.objects.filter(tenant_id=tenant_id, is_enabled=True).values_list("module_key", flat=True)
    )
    return {name for name, access in registry.items() if access.allows(roles, modules)}
