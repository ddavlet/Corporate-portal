from django.conf import settings
from django.http import Http404

from apps.tenants.models import Tenant


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
    "/api/investments/approvals/webhook",
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

        from apps.mcp_server.routing import is_mcp_host

        if is_mcp_host(request.get_host()):
            return self.get_response(request)

        sub = _get_subdomain(request.get_host(), getattr(settings, "BASE_DOMAIN", "") or "")
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

