"""Shared portal host (``PORTAL_SHARED_HOST``, e.g. ``app.kolberg.uz``).

On the shared host the company is not taken from the Host subdomain: the client sends
``X-Tenant: <subdomain>`` and ``SharedHostPortalJWTAuthentication`` attaches the tenant only
after checking the user's active membership. Empty setting means the mode is off and every
helper here reports "not shared".
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.tenants.models import Tenant

TENANT_HEADER_META_KEY = "HTTP_X_TENANT"

# Integration paths: on the shared host they behave as on a host without subdomain,
# X-Tenant is never read (n8n prefixes are added from settings in `is_excluded_path`).
SHARED_HOST_EXCLUDED_PREFIXES = (
    "/api/messaging-gateway/webhook",
    "/api/messaging-gateway/events",
    "/api/admin",
    "/mcp",
    "/.well-known",
)

# Paths that need no company on the shared host: JWT without X-Tenant is fine here,
# and X-Tenant is ignored (these views never use request.tenant for authorization).
SHARED_HOST_TENANTLESS_PREFIXES = (
    "/api/auth",
    "/api/me/companies",
    "/api/notifications/action-items/all",
    "/api/portal/config",
    "/api/investments/public",
)

# Always reserved for tenant subdomains, in addition to the first label of PORTAL_SHARED_HOST.
_ALWAYS_RESERVED_SUBDOMAINS = frozenset({"app"})


def _host_no_port(host: str) -> str:
    return (host or "").split(":")[0].lower().rstrip(".")


def shared_host() -> str:
    return (getattr(settings, "PORTAL_SHARED_HOST", "") or "").strip().lower()


def is_shared_host(request) -> bool:
    """Exact host match (no port, case-insensitive); no suffix or regex matching."""
    configured = shared_host()
    if not configured:
        return False
    return _host_no_port(request.get_host()) == configured


def _path_matches(path: str, prefixes) -> bool:
    if not path:
        return False
    for prefix in prefixes:
        p = prefix.rstrip("/")
        if p and (path == p or path.startswith(p + "/")):
            return True
    return False


def _n8n_prefixes() -> frozenset[str]:
    prefixes = getattr(settings, "N8N_INTEGRATION_URL_PREFIXES", None) or frozenset()
    if not prefixes:
        single = (getattr(settings, "N8N_INTEGRATION_URL_PREFIX", None) or "").rstrip("/")
        prefixes = frozenset({single}) if single else frozenset()
    return prefixes


def is_excluded_path(path: str) -> bool:
    return _path_matches(path, SHARED_HOST_EXCLUDED_PREFIXES) or _path_matches(path, _n8n_prefixes())


def is_tenantless_path(path: str) -> bool:
    return _path_matches(path, SHARED_HOST_TENANTLESS_PREFIXES)


def tenant_header(request) -> str:
    return (request.META.get(TENANT_HEADER_META_KEY) or "").strip().lower()


def resolve_member_tenant(*, subdomain: str, user) -> Tenant | None:
    """Active tenant `subdomain` where `user` has an active membership; one query.

    Unknown, inactive and foreign tenants all give None, so callers cannot tell them apart.
    """
    subdomain = (subdomain or "").strip().lower()
    if not subdomain or user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        Tenant.objects.filter(
            subdomain=subdomain,
            is_active=True,
            memberships__user=user,
            memberships__is_active=True,
        )
        .order_by("pk")
        .first()
    )


def member_tenants(*, user):
    """Active tenants where `user` has an active membership, by name (a QuerySet to narrow further)."""
    return Tenant.objects.filter(
        is_active=True,
        memberships__user=user,
        memberships__is_active=True,
    ).order_by("name", "id")


def reserved_subdomains() -> frozenset[str]:
    reserved = set(_ALWAYS_RESERVED_SUBDOMAINS)
    host = shared_host()
    if host:
        reserved.add(host.split(".")[0])
    return frozenset(reserved)


def validate_subdomain_not_reserved(value: str) -> None:
    if (value or "").strip().lower() in reserved_subdomains():
        raise ValidationError(
            "Поддомен «%(value)s» зарезервирован для общего адреса портала.",
            code="reserved_subdomain",
            params={"value": value},
        )


def reserved_tenants_in_use() -> list[str]:
    """Subdomains of active tenants that clash with the reserved slugs, sorted."""
    return sorted(
        Tenant.objects.filter(subdomain__in=reserved_subdomains(), is_active=True).values_list("subdomain", flat=True)
    )
