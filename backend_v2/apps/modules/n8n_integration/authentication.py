
import secrets

from django.conf import settings
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.tenants.integration_settings import get_n8n_integration_settings


class IntegrationNotConfigured(APIException):
    status_code = 503
    default_detail = "N8N_INTEGRATION_TOKEN is not configured."
    default_code = "integration_not_configured"


class N8nIntegrationAuthentication(JWTAuthentication):
    """
    Requires X-N8N-Integration-Token matching settings, then a valid JWT (tenant admin checked separately).
    """

    def authenticate(self, request):
        tenant = getattr(request, "tenant", None)
        expected = get_n8n_integration_settings(tenant=tenant).integration_token
        if not expected:
            expected = (getattr(settings, "N8N_INTEGRATION_TOKEN", None) or "").strip()
        if not expected:
            raise IntegrationNotConfigured()
        got = request.META.get("HTTP_X_N8N_INTEGRATION_TOKEN", "") or ""
        if not secrets.compare_digest(got, expected):
            raise AuthenticationFailed("Invalid integration token.")
        result = super().authenticate(request)
        if result is None:
            raise AuthenticationFailed("Authentication credentials were not provided.")
        return result
