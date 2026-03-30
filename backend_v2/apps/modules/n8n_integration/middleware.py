
from django.conf import settings
from django.http import JsonResponse

from apps.tenants.middleware import _get_subdomain
from apps.tenants.models import Tenant


class N8nIntegrationTenantMiddleware:
    """
    For n8n integration URL prefixes, resolve tenant from the request Host subdomain
    (same rules as TenantSubdomainMiddleware + BASE_DOMAIN).
    Must be listed before TenantSubdomainMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        prefixes = getattr(settings, "N8N_INTEGRATION_URL_PREFIXES", None) or frozenset()
        if not prefixes:
            single = (getattr(settings, "N8N_INTEGRATION_URL_PREFIX", None) or "").rstrip("/")
            prefixes = frozenset({single}) if single else frozenset()
        path = request.path or ""
        matched = any(
            p and (path == p or path.startswith(p + "/"))
            for p in prefixes
        )
        if not matched:
            return self.get_response(request)

        sub = _get_subdomain(request.get_host(), getattr(settings, "BASE_DOMAIN", "") or "")
        if not sub:
            return JsonResponse(
                {"detail": "Could not determine tenant from request Host."},
                status=400,
            )
        tenant = Tenant.objects.filter(subdomain=sub, is_active=True).first()
        if not tenant:
            return JsonResponse({"detail": "Unknown tenant."}, status=404)
        request.tenant = tenant
        return self.get_response(request)
