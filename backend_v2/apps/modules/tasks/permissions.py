from __future__ import annotations

from rest_framework.permissions import BasePermission

from apps.tenants.models import TenantUserRole
from apps.tenants.permissions import _user_has_any_role

# Roles that can see and act on any task inside a tenant.
# OCP extension point: add a new role here to grant tenant-wide access.
# Adding a role is a one-line change in this set — no edits to permission classes.
_WIDE_ACCESS_ROLES: frozenset[str] = frozenset({
    TenantUserRole.ROLE_ADMIN,
    TenantUserRole.ROLE_DIRECTOR,
})


def _is_tenant_admin_or_director(user, tenant) -> bool:
    """Single place that defines which roles have tenant-wide task access."""
    if not tenant:
        return False
    return _user_has_any_role(user=user, tenant=tenant, roles=_WIDE_ACCESS_ROLES)


def tenant_admin_director_user_ids(tenant) -> set[int]:
    """Return the set of user IDs that hold admin/director role in a tenant.

    Used to precompute admin/director membership once per request so that
    serializers do not need to issue per-comment role lookups (N+1 elimination).
    """
    if not tenant:
        return set()
    from apps.tenants.models import TenantUserRole
    return set(
        TenantUserRole.objects.filter(
            tenant=tenant,
            role__in=_WIDE_ACCESS_ROLES,
        ).values_list("user_id", flat=True)
    )


def _is_authenticated(request) -> bool:
    return bool(request.user and request.user.is_authenticated)


def _task_belongs_to_tenant(obj, tenant) -> bool:
    return tenant is not None and obj.tenant_id == tenant.id


class CanViewTask(BasePermission):
    """
    Grants access when:
      - user is the task assignee, OR
      - user is admin/director within the task's tenant.
    """

    def has_permission(self, request, view) -> bool:
        return _is_authenticated(request)

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if obj.assignee_id == user.id:
            return True
        return _task_belongs_to_tenant(obj, tenant) and _is_tenant_admin_or_director(user, tenant)


class CanCommentOnTask(BasePermission):
    """
    Grants comment access when:
      - user is the task assignee, OR
      - user is admin/director within the task's tenant.
    Directors/admins can leave directive comments on other users' tasks.
    """

    def has_permission(self, request, view) -> bool:
        return _is_authenticated(request)

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if obj.assignee_id == user.id:
            return True
        return _task_belongs_to_tenant(obj, tenant) and _is_tenant_admin_or_director(user, tenant)


class CanChangeStatus(BasePermission):
    """
    Grants status-change access when:
      - user is the task assignee, OR
      - user is admin/director within the task's tenant.
    """

    def has_permission(self, request, view) -> bool:
        return _is_authenticated(request)

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        tenant = getattr(request, "tenant", None)
        if obj.assignee_id == user.id:
            return True
        return _task_belongs_to_tenant(obj, tenant) and _is_tenant_admin_or_director(user, tenant)
