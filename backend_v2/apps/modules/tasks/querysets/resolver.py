from __future__ import annotations

from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import _user_has_any_role
from apps.modules.tasks.querysets.base import AbstractTaskScope
from apps.modules.tasks.querysets.own_tasks import OwnTasksScope
from apps.modules.tasks.querysets.tenant_tasks import TenantTasksScope

# OCP extension point: add a new (predicate, scope_class) tuple to grant a
# different scope to a new role. Predicates are evaluated top-to-bottom;
# the first match wins. Never add if/elif chains inside views or services.
_SCOPE_REGISTRY: list[tuple[callable, type[AbstractTaskScope]]] = [
    (
        lambda user, tenant: _user_has_any_role(
            user=user,
            tenant=tenant,
            roles={TenantUserRole.ROLE_ADMIN, TenantUserRole.ROLE_DIRECTOR},
        ),
        TenantTasksScope,
    ),
]

_DEFAULT_SCOPE = OwnTasksScope


def resolve_scope_for_user(user, tenant) -> AbstractTaskScope:
    """Return the correct visibility scope for a user within a tenant.

    To give a new role broader/narrower access, add a (predicate, ScopeClass)
    entry to _SCOPE_REGISTRY above — do not modify this function.
    """
    for predicate, scope_class in _SCOPE_REGISTRY:
        if predicate(user, tenant):
            return scope_class()
    return _DEFAULT_SCOPE()
