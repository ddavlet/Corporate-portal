"""
Django login view for the MCP OAuth flow.

URL: https://<tenant>.<BASE_DOMAIN>/mcp/login/?t=<signed_params>

The signed params carry tenant_id; it must match the host tenant, and the user
must be an active member of it. The OTP is delivered via that tenant's bot.

Two-step flow:
  Step 1 — username form  → triggers OTP via Telegram
  Step 2 — OTP form       → verifies code, creates authorization code, redirects to client
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.core import signing
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views import View

from apps.mcp_server.routing import mcp_http_enabled

_SIGN_SALT = "mcp-oauth-authorize"
_SIGN_MAX_AGE = 600  # 10 min


def _decode_params(t: str) -> dict | None:
    try:
        return signing.loads(t, salt=_SIGN_SALT, max_age=_SIGN_MAX_AGE)
    except signing.BadSignature:
        return None


def _is_member(user, tenant) -> bool:
    from apps.tenants.models import TenantMembership

    return TenantMembership.objects.filter(user=user, tenant=tenant, is_active=True).exists()


class McpLoginView(View):
    template_name = "mcp_oauth/login.html"

    def dispatch(self, request, *args, **kwargs):
        tenant = getattr(request, "tenant", None)
        if not mcp_http_enabled() or tenant is None or not tenant.mcp_enabled:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    def _params_for_tenant(self, request, t: str) -> dict | None:
        params = _decode_params(t)
        if not params or params.get("tenant_id") != request.tenant.id:
            return None
        return params

    def get(self, request: HttpRequest) -> HttpResponse:
        t = request.GET.get("t", "")
        params = self._params_for_tenant(request, t)
        if not params:
            return HttpResponseBadRequest("Invalid or expired authorization request.")
        return render(request, self.template_name, {"t": t, "step": "username"})

    def post(self, request: HttpRequest) -> HttpResponse:
        t = request.POST.get("t", "")
        params = self._params_for_tenant(request, t)
        if not params:
            return HttpResponseBadRequest("Invalid or expired authorization request.")

        step = request.POST.get("step", "username")

        if step == "username":
            return self._handle_username(request, t, params)
        if step == "otp":
            return self._handle_otp(request, t, params)
        return HttpResponseBadRequest("Unknown step.")

    # ------------------------------------------------------------------

    def _handle_username(self, request, t, params):
        username = request.POST.get("username", "").strip()
        if not username:
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Введите имя пользователя."
            })

        from apps.accounts.models import User
        from apps.accounts.otp import OtpError, send_otp

        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Пользователь не найден."
            })

        if not _is_member(user, request.tenant):
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Нет доступа к этой компании."
            })

        ip = request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or ""
        try:
            send_otp(user=user, tenant=request.tenant, ip=ip)
        except OtpError as exc:
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": str(exc),
            })

        return render(request, self.template_name, {
            "t": t, "step": "otp", "username": username,
        })

    def _handle_otp(self, request, t, params):
        username = request.POST.get("username", "").strip()
        otp_code = request.POST.get("otp", "").strip()

        from apps.accounts.models import User
        from apps.accounts.otp import OtpError, verify_otp

        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Пользователь не найден."
            })

        if not _is_member(user, request.tenant):
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Нет доступа к этой компании."
            })

        try:
            verify_otp(user=user, code=otp_code, tenant=request.tenant)
        except OtpError as exc:
            return render(request, self.template_name, {
                "t": t, "step": "otp", "username": username,
                "error": str(exc),
            })

        # OTP verified — create authorization code and redirect
        from apps.mcp_server.oauth.provider import create_authorization_code

        code = create_authorization_code(
            client_id=params["client_id"],
            user_id=user.id,
            tenant_id=request.tenant.id,
            redirect_uri=params["redirect_uri"],
            redirect_uri_provided_explicitly=params["redirect_uri_provided_explicitly"],
            code_challenge=params["code_challenge"],
            code_challenge_method="S256",
            scopes=params.get("scopes") or [],
            state=params.get("state") or "",
        )

        qs = urlencode({"code": code, "state": params.get("state") or ""})
        return HttpResponse(
            status=302,
            headers={"Location": f"{params['redirect_uri']}?{qs}"},
        )
