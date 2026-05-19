"""
Django login view for the MCP OAuth flow.

URL: /oauth/login/?t=<signed_params>

Two-step flow:
  Step 1 — username form  → triggers OTP via Telegram
  Step 2 — OTP form       → verifies code, creates authorization code, redirects to client
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.core import signing
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views import View

_SIGN_SALT = "mcp-oauth-authorize"
_SIGN_MAX_AGE = 600  # 10 min


def _decode_params(t: str) -> dict | None:
    try:
        return signing.loads(t, salt=_SIGN_SALT, max_age=_SIGN_MAX_AGE)
    except signing.BadSignature:
        return None


class McpLoginView(View):
    template_name = "mcp_oauth/login.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        t = request.GET.get("t", "")
        params = _decode_params(t)
        if not params:
            return HttpResponseBadRequest("Invalid or expired authorization request.")
        return render(request, self.template_name, {"t": t, "step": "username"})

    def post(self, request: HttpRequest) -> HttpResponse:
        t = request.POST.get("t", "")
        params = _decode_params(t)
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
        from apps.tenants.models import Tenant

        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Пользователь не найден."
            })

        # Send OTP using existing logic
        from apps.accounts.otp import send_otp

        try:
            send_otp(user=user)
        except Exception as exc:
            return render(request, self.template_name, {
                "t": t, "step": "username",
                "error": f"Не удалось отправить OTP: {exc}",
            })

        return render(request, self.template_name, {
            "t": t, "step": "otp", "username": username,
        })

    def _handle_otp(self, request, t, params):
        username = request.POST.get("username", "").strip()
        otp_code = request.POST.get("otp", "").strip()

        from apps.accounts.models import User
        from apps.accounts.otp import verify_otp

        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            return render(request, self.template_name, {
                "t": t, "step": "username", "error": "Пользователь не найден."
            })

        try:
            verify_otp(user=user, code=otp_code)
        except Exception:
            return render(request, self.template_name, {
                "t": t, "step": "otp", "username": username,
                "error": "Неверный или истёкший код.",
            })

        # OTP verified — create authorization code and redirect
        from apps.mcp_server.oauth.provider import create_authorization_code

        code = create_authorization_code(
            client_id=params["client_id"],
            user_id=user.id,
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
