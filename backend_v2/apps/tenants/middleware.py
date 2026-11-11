import logging

from django.conf import settings
from django.http import Http404

from apps.tenants import shared_host as sh
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)

# Longest X-Tenant value written to the log (the header is client-controlled).
_LOGGED_HEADER_MAX_CHARS = 64


class RewriteDockerInternalHostMiddleware:
    """
    Docker Compose historically used ``django_v2`` / ``backend_v2`` as DNS names.
    Underscores are not valid in RFC 1034/1035 hostnames, so Django rejects
    ``HTTP_HOST`` before ``ALLOWED_HOSTS`` is consulted. Map those names to an
    RFC-valid alias (see ``DOCKER_INTERNAL_BACKEND_DNS_NAME`` in settings).
    """

    _LEGACY_NAMES = frozenset({"django_v2", "backend_v2"})

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.META.get("HTTP_HOST")
        if host:
            domain, _, port = host.partition(":")
            canonical = settings.DOCKER_INTERNAL_BACKEND_DNS_NAME
            if canonical and domain in self._LEGACY_NAMES:
                request.META["HTTP_HOST"] = f"{canonical}:{port}" if port else canonical
        return self.get_response(request)


def _host_no_port(host: str) -> str:
    return (host or "").split(":")[0].lower()


# Forwarded from tg-gateway over Docker DNS (e.g. kolberg_backend_local). Tenant is resolved inside the view from Approval.
_INTERNAL_MESSAGING_CALLBACK_PREFIXES = (
    "/api/messaging-gateway/webhook",
    "/api/messaging-gateway/events",
)


def _is_internal_messaging_gateway_callback(path: str) -> bool:
    if not path:
        return False
    return any(path == p or path.startswith(p + "/") for p in _INTERNAL_MESSAGING_CALLBACK_PREFIXES)


def _get_subdomain(host: str, base_domain: str) -> str:
    h = _host_no_port(host)
    if not h:
        return ""
    if base_domain:
        base_domain = base_domain.lower().strip(".")
        suffix = "." + base_domain
        if h.endswith(suffix):
            prefix = h[: -len(suffix)]
            return prefix.split(".")[0] if prefix else ""
        return ""

    # Fallback: best-effort first label.
    parts = h.split(".")
    if len(parts) < 3:
        return ""
    return parts[0]


class TenantSubdomainMiddleware:
    """
    Extract tenant from the request host subdomain and attach it as `request.tenant`.
    The new tenant-only backend relies on `request.tenant` for module gating.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, "tenant", None) is not None:
            return self.get_response(request)

        if _is_internal_messaging_gateway_callback(request.path or ""):
            return self.get_response(request)

        sub =_get_subdomain(request.get_host(), getattr(settings, "BASE_DOMAIN", "") or "")
        if not sub:
            if getattr(settings, "TENANT_SUBDOMAIN_FALLBACK", True):
                # Keep it explicit: for missing subdomain, treat as unknown tenant.
                raise Http404("Unknown tenant")
            raise Http404("Unknown tenant")

        tenant = Tenant.objects.filter(subdomain=sub, is_active=True).first()
        if not tenant:
            raise Http404("Unknown tenant")

        request.tenant = tenant
        return self.get_response(request)



class SharedHostTenantMiddleware(TenantSubdomainMiddleware):
    """
    ``TenantSubdomainMiddleware`` plus the shared portal host (``PORTAL_SHARED_HOST``).

    - Other hosts (tenant subdomains): base behavior; ``X-Tenant`` is ignored, a mismatch
      with the subdomain is only logged.
    - Shared host, integration path (n8n, messaging-gateway webhook/events, admin, MCP,
      .well-known): treated as a host without subdomain; ``X-Tenant`` is never read and the
      tenant is never resolved from the shared host name.
    - Shared host, any other path: ``request.tenant = None``; the requested company is kept
      in ``request.tenant_header`` and attached only by ``SharedHostPortalJWTAuthentication``
      after the membership check (fail closed: no check, no tenant).
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        self._reserved_tenant_checked = False

    def __call__(self, request):
        if not sh.is_shared_host(request):
            self._warn_header_mismatch(request, sh.tenant_header(request))
            return super().__call__(request)

        self._log_reserved_tenant_once()
        path = request.path or ""
        if sh.is_excluded_path(path):
            # Same as a host without subdomain: only an already resolved tenant (n8n
            # middleware) or the internal messaging callbacks pass; never a Host lookup.
            if getattr(request, "tenant", None) is not None or _is_internal_messaging_gateway_callback(path):
                return self.get_response(request)
            raise Http404("Unknown tenant")

        request.tenant = None
        request.portal_shared_host = True
        request.tenant_header = sh.tenant_header(request)
        return self.get_response(request)

    @staticmethod
    def _warn_header_mismatch(request, header: str) -> None:
        # Only while the shared mode is on: with it off X-Tenant means nothing and the log
        # must not grow on client-controlled values. The value is clipped and quoted (%r).
        if not header or not sh.shared_host():
            return
        sub = _get_subdomain(request.get_host(), getattr(settings, "BASE_DOMAIN", "") or "")
        if header != sub:
            logger.warning(
                "X-Tenant ignored on tenant host: host_subdomain=%s header=%r path=%s",
                sub or "-",
                header[:_LOGGED_HEADER_MAX_CHARS],
                request.path,
            )

    def _log_reserved_tenant_once(self) -> None:
        if self._reserved_tenant_checked:
            return
        self._reserved_tenant_checked = True
        taken = sh.reserved_tenants_in_use()
        if taken:
            logger.error("Active tenant uses a subdomain reserved for the shared portal host: %s", ", ".join(taken))
