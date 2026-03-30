from django.http import Http404
from apps.tenants.models import Tenant


def _host_no_port(host: str) -> str:
    return (host or "").split(":")[0].lower()


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
        from django.conf import settings

        if getattr(request, "tenant", None) is not None:
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

