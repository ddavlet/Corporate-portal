import requests
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseServerError
from django.conf import settings

def tenant_home(request):
    # TenantMiddleware уже гарантирует:
    # - request.tenant
    # - request.user.is_authenticated
    if not request.user.is_authenticated:
        return redirect("/login/")
    tenant = getattr(request, "tenant", None)

    return render(
        request,
        "portal/tenant_home.html",
        {
            "tenant": tenant,
            "login_host": getattr(settings, "LOGIN_HOST", "login.kolberg.uz"),
        },
    )

def requests_page(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    # пока просто страница-заглушка (позже вставим твой шаблон requests.html)
    return render(request, "requests.html")

def vendors_page(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    # страница-заглушка (позже сделаем список поставщиков)
    return render(request, "vendors.html")

def _proxy_n8n_json(request, endpoint: str):
    if not request.user.is_authenticated:
        return HttpResponseForbidden("Login required")

    tenant = getattr(request, "tenant", None)
    if not tenant:
        return HttpResponseForbidden("No tenant")

    url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}/{endpoint.lstrip('/')}"

    try:
        resp = requests.get(
            url,
            params=request.GET,
            timeout=20,
            headers={
                "Accept": "application/json",
                "X-N8N-Token": settings.N8N_TOKEN,
                "X-Tenant": tenant.subdomain,
                "X-User-Id": str(request.user.id),
            },
        )

        if resp.status_code in (401, 403):
            return HttpResponseForbidden("Forbidden by n8n")
        if resp.status_code >= 400:
            return HttpResponseServerError(f"n8n error {resp.status_code}")

        return JsonResponse(resp.json(), safe=False)
    except requests.RequestException as e:
        return HttpResponseServerError(f"n8n request failed: {e}")

def requests_data(request):
    return _proxy_n8n_json(request, "/requests-data")


def vendors_data(request):
    return _proxy_n8n_json(request, "/vendors-data")

def vendor_request_data(request):
    return _proxy_n8n_json(request, "/vendor-request-data")

