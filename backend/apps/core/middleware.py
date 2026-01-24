from urllib.parse import quote

from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from apps.core.models import Tenant, Membership

LOGIN_HOST = "login.kolberg.uz"

def host_no_port(host: str) -> str:
    return (host or "").split(":")[0].lower()

def get_subdomain(host: str) -> str:
    h = host_no_port(host)
    parts = h.split(".")
    if len(parts) < 3:
        return ""
    return parts[0]

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = host_no_port(request.get_host())

        # 1) login-сабдомен НЕ должен требовать tenant
        if host == LOGIN_HOST:
            request.tenant = None
            return self.get_response(request)

        # 2) Определяем tenant по сабдомену
        sub = get_subdomain(host)
        if not sub:
            return HttpResponseForbidden("No subdomain")

        tenant = Tenant.objects.filter(subdomain=sub, is_active=True).first()
        if not tenant:
            return HttpResponseForbidden("Unknown tenant")
        request.tenant = tenant

        # 3) Если не авторизован — редирект на общий логин
        if not request.user.is_authenticated:
            # next = полная ссылка, чтобы после логина вернуть на правильный сабдомен/путь
            next_url = request.build_absolute_uri()
            return redirect(f"https://{LOGIN_HOST}/login/?next={quote(next_url)}")

        # 4) Проверяем membership
        ok = Membership.objects.filter(
            user=request.user, tenant=tenant, is_active=True
        ).exists()
        if not ok:
            return HttpResponseForbidden("No access to this tenant")

        return self.get_response(request)
