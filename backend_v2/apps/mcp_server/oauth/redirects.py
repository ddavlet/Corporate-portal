"""Legacy URL redirects for MCP OAuth."""

from django.http import HttpResponsePermanentRedirect
from django.views import View

from .metadata import mcp_oauth_login_url


class McpLoginLegacyRedirectView(View):
    """Redirect old login URLs → canonical /oauth/login/ (preserves query string)."""

    def get(self, request, *args, **kwargs):
        target = mcp_oauth_login_url().rstrip("/") + "/"
        if request.META.get("QUERY_STRING"):
            target = f"{target}?{request.META['QUERY_STRING']}"
        return HttpResponsePermanentRedirect(target)

    def post(self, request, *args, **kwargs):
        return self.get(request, *args, **kwargs)
