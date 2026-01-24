from urllib.parse import urlparse

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from apps.core.models import Membership, Tenant

BASE_DOMAIN = "kolberg.uz"

def _safe_next(next_url: str) -> str:
    """
    Разрешаем редирект только на *.kolberg.uz, чтобы не было open redirect.
    """
    if not next_url:
        return ""
    try:
        u = urlparse(next_url)
        host = (u.hostname or "").lower()
        if host.endswith("." + BASE_DOMAIN) or host == BASE_DOMAIN:
            return next_url
    except Exception:
        pass
    return ""

def login_view(request):
    if request.method == "GET":
        return render(request, "login.html", {"next": request.GET.get("next", "")})

    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""
    next_url = _safe_next(request.POST.get("next") or request.GET.get("next") or "")

    user = authenticate(request, username=username, password=password)
    if not user:
        return render(request, "login.html", {"error": "Неверный логин или пароль", "next": next_url})

    login(request, user)

    memberships = (
        Membership.objects
        .select_related("tenant")
        .filter(user=user, is_active=True, tenant__is_active=True)
    )
    tenants = [m.tenant for m in memberships]

    if not tenants:
        logout(request)
        return HttpResponseForbidden("Нет доступа ни к одной компании")

    # Если next указывает на конкретный сабдомен, и у пользователя есть доступ — ведём туда
    if next_url:
        host = (urlparse(next_url).hostname or "").lower()
        sub = host.split(".")[0] if host.endswith("." + BASE_DOMAIN) else ""
        if sub and any(t.subdomain == sub for t in tenants):
            return redirect(next_url)

    # Одна компания → сразу туда
    if len(tenants) == 1:
        t = tenants[0]
        return redirect(f"https://{t.subdomain}.kolberg.uz/web/requests")

    # Несколько → выбор компании
    request.session["tenant_choices"] = [t.id for t in tenants]
    if next_url:
        request.session["post_login_next"] = next_url
    return redirect("/choose-tenant/")

def choose_tenant_view(request):
    if not request.user.is_authenticated:
        return redirect("/login/")

    ids = request.session.get("tenant_choices") or []
    tenants = list(Tenant.objects.filter(id__in=ids, is_active=True))

    if request.method == "GET":
        return render(request, "choose_tenant.html", {"tenants": tenants})

    tid = request.POST.get("tenant_id")
    t = next((x for x in tenants if str(x.id) == str(tid)), None)
    if not t:
        return render(request, "choose_tenant.html", {"tenants": tenants, "error": "Выберите компанию"})

    next_url = _safe_next(request.session.get("post_login_next") or "")
    if next_url:
        # если next уже на нужный сабдомен — редиректим туда
        return redirect(next_url)

    return redirect(f"https://{t.subdomain}.{BASE_DOMAIN}/requests")

def logout_view(request):
    logout(request)
    return redirect("/login/")


def requests_page(request):
    # пока просто страница-заглушка (позже вставим твой шаблон requests.html)
    return render(request, "requests.html")

def vendors_page(request):
    # страница-заглушка (позже сделаем список поставщиков)
    return render(request, "vendors.html")

def requests_data(request):
    # временно отдаём пустые данные, чтобы фронт/JS не падал
    return JsonResponse({"requests": [], "approvals": [], "users": []})
