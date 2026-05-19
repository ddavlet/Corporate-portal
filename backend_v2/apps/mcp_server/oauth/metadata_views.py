"""Django views for MCP OAuth discovery at the authorization base URL (host root)."""

from __future__ import annotations

from django.http import JsonResponse
from django.views import View

from .metadata import authorization_server_metadata, protected_resource_metadata


class AuthorizationServerMetadataView(View):
    def get(self, request, *args, **kwargs):
        return JsonResponse(authorization_server_metadata())


class ProtectedResourceMetadataView(View):
    def get(self, request, *args, **kwargs):
        return JsonResponse(protected_resource_metadata())
