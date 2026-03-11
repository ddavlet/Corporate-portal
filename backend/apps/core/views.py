from urllib.parse import urlparse
import requests
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.conf import settings
from apps.core.models import Membership, Tenant
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash

# Create your views here.
def _safe_next(request, next_url: str) -> str:
    if not next_url:
        return ""

    # разрешим относительные ссылки (в рамках login домена)
    if next_url.startswith("/"):
        return next_url

    allowed = {settings.BASE_DOMAIN, f"login.{settings.BASE_DOMAIN}"}
    # можно разрешить любой сабдомен базы:
    # но url_has_allowed_host_and_scheme требует явный host, поэтому проще проверить через парсинг:
    try:
        host = (urlparse(next_url).hostname or "").lower()
        if host.endswith("." + settings.BASE_DOMAIN) or host == settings.BASE_DOMAIN:
            if url_has_allowed_host_and_scheme(next_url, allowed_hosts={host}, require_https=True):
                return next_url
    except Exception:
        pass

    return ""

def login_view(request):
    if request.method == "GET":
        return render(request, "auth/login.html", {"next": request.GET.get("next", "")})

    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""
    next_url = _safe_next(request, request.POST.get("next") or request.GET.get("next") or "")

    user = authenticate(request, username=username, password=password)
    if not user:
        return render(request, "auth/login.html", {"error": "Неверный логин или пароль", "next": next_url})

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
        sub = host.split(".")[0] if host.endswith("." + settings.BASE_DOMAIN) else ""
        if sub and any(t.subdomain == sub for t in tenants):
            return redirect(next_url)

    # Одна компания → сразу туда
    if len(tenants) == 1:
        t = tenants[0]
        return redirect(f"https://{t.subdomain}.{settings.BASE_DOMAIN}/web/requests")

    # Несколько → выбор компании
    request.session["tenant_choices"] = [t.id for t in tenants]
    if next_url:
        request.session["post_login_next"] = next_url
    return redirect("/choose-tenant/")

def choose_tenant_view(request):
    if not request.user.is_authenticated:
        return redirect("/login/")

    memberships = list(
        Membership.objects.select_related("tenant")
        .filter(user=request.user, is_active=True, tenant__is_active=True)
        .order_by("tenant__name")
    )

    # если доступ только к одной компании — сразу туда
    if len(memberships) == 1:
        t = memberships[0].tenant
        return redirect(f"https://{t.subdomain}.{settings.BASE_DOMAIN}/web/requests")

    return render(request, "auth/choose_tenant.html", {"memberships": memberships})

def logout_view(request):
    logout(request)
    return redirect("/login/")

def password_change(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    if request.method == "POST":
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()  # меняет пароль
            update_session_auth_hash(request, user)  # чтобы не разлогинило
            return redirect("password_change_done")
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, "auth/password_change.html", {"form": form})

def password_change_done(request):
    if not request.user.is_authenticated:
        return redirect("/login/")
    return render(request, "auth/password_change_done.html")


def _normalize_investments_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "investments", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def corporate_investments_report(request):
    if not request.user.is_authenticated:
        return redirect("/login/")

    allowed_username = getattr(settings, "CORPORATE_INVESTMENTS_ALLOWED_USER", "").strip()
    if not allowed_username:
        return HttpResponseForbidden("Report user is not configured")

    if request.user.username != allowed_username:
        return HttpResponseForbidden("Access denied")

    sources = getattr(settings, "CORPORATE_INVESTMENTS_SOURCES", [])
    timeout_sec = getattr(settings, "CORPORATE_INVESTMENTS_TIMEOUT_SEC", 15)

    rows = []
    for url in sources:
        try:
            response = requests.get(url, timeout=timeout_sec, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        source_name = str(url).rstrip("/").split("/")[-1] or "unknown"
        for item in _normalize_investments_payload(payload):
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized["company_name"] = (
                normalized.get("company_name")
                or normalized.get("company")
                or source_name
            )
            rows.append(normalized)

    return render(
        request,
        "corporate/investments.html",
        {
            "investments": rows,
            "investment_sources": sources,
        },
    )
