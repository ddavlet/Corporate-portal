"""Django views for MCP OAuth discovery at the authorization base URL (host root)."""

from __future__ import annotations

from django.http import Http404, JsonResponse
from django.views import View

from apps.mcp_server.routing import mcp_http_enabled

from .metadata import authorization_server_metadata, protected_resource_metadata


class _McpHttpRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        if not mcp_http_enabled():
            raise Http404()
        return super().dispatch(request, *args, **kwargs)


class AuthorizationServerMetadataView(_McpHttpRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return JsonResponse(authorization_server_metadata())


class ProtectedResourceMetadataView(_McpHttpRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return JsonResponse(protected_resource_metadata())
